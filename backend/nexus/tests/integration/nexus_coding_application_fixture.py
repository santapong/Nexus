"""Public fresh full10 governance/auth/configuration; no hidden seeds or authority bypass.

Cohesion exception: the complete one-company fixture and exact DB isolation stay
together. All registrations, revisions and citations are actual public returns.
The only inherited unit data are unregistered server profile descriptions.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from unittest.mock import patch
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest
from dbos import DBOS
from litestar import Litestar
from litestar.testing import AsyncTestClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from nexus.builder.contained_query import clock_us
from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange
from nexus.company.brain.access_models import BrainResource
from nexus.company.brain.base import BrainReadScope, SourceTime
from nexus.company.brain.context import ContextSelection
from nexus.company.brain.retrieval import SearchRequest
from nexus.company.brain.scope_support import brain_transaction
from nexus.company.contracts.company import CompanyMandate, DepartmentCharter
from nexus.company.control_store import CompanyControls
from nexus.company.directory_contracts import CompanyRegistration, MembershipChange
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management.api_services import ManagementApiServices
from nexus.company.management.base import RevisionRef
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.coding_publication_contracts import PublishedCodingPatch
from nexus.company.management.coding_publication_store import CodingPublicationStore
from nexus.company.management.coding_repository import CodingRepositorySelection
from nexus.company.management.control_store import ManagementControlStore
from nexus.company.management.cycle_cost_contracts import CycleCostSnapshot
from nexus.company.management.goal_store import GoalRevisionRecord, GoalStore
from nexus.company.management.goals import (
    DueIntent,
    GoalDefinition,
    GoalMetric,
    GoalRevisionRef,
    UnknownBaseline,
)
from nexus.company.management.governance import CharterRevisionRef
from nexus.company.management.lifecycle import PlanRevision
from nexus.company.management.nexus_coding_admission import NexusCodingAdmission
from nexus.company.management.plan_catalog import NamedPlanResource, PlanAdmissionCatalog
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.planning_authority import PlanningRolePolicy
from nexus.company.notifications.worker_identity import (
    AuthenticatedWorkerIdentity,
    NotificationWorkerIdentities,
)
from nexus.company.pilot_session import PilotSessionService
from nexus.company.pilot_session_store import PilotCredential, PilotCredentialFile, save_credentials
from nexus.company.services import CompanyServices
from nexus.company_app import create_company_app
from nexus.core.llm.company_endpoints import SettingsEndpointResolver
from nexus.core.llm.company_registry import ModelRegistry
from nexus.execution.coding_application import (
    CodingApplication,
    coding_app,
    compose_coding_application,
)
from nexus.execution.coding_application_config import CodingApplicationConfig
from nexus.execution.coding_preparation import PreparedCodingAction
from nexus.execution.coding_worker import execute_coding_segment
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.planning_application_config import PlanningApplicationConfig, PlanningStorage
from nexus.execution.planning_worker import execute_planning_segment
from nexus.execution.runtime_contracts import ExecutionLease, ExecutionSnapshot
from nexus.execution.runtime_store import ExecutionStore
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import ActionRecord, CompanyPolicy, LedgerScope
from nexus.settings import Settings, settings
from nexus.tests.integration.nexus_coding_application_sources import (
    DATABASE,
    PORT,
    RELEASE_ROOT,
    SOCKET,
    Sources,
    ingest_sources,
)
from nexus.tests.integration.nexus_coding_application_transport import (
    UpfrontReservation,
    priced_catalog,
    recipe,
    upfront_quotes,
)
from nexus.tests.integration.test_company_directory import migrate
from nexus.tests.integration.test_nexus_planning_runtime import Credentials, login
from nexus.tests.unit.nexus_cycle_fixture import COMPANY as ORIGINAL_COMPANY
from nexus.tests.unit.test_company_provider_conformance import KEY
from nexus.tests.unit.test_nexus_coding_catalog import coding_case

if TYPE_CHECKING:
    from nexus.tests.integration.nexus_coding_application_worker import (
        OwnedWorker,
        PendingSpawn,
        WorkerObservation,
    )

COMPANY = uuid5(NAMESPACE_URL, "nexus-coding-application-v11-20261028")
POLICY = "nexus-c-application-v1"


def key(label: str) -> UUID:
    return uuid5(COMPANY, label)


def fixture_principals(
    initial: NexusCodingAdmission,
) -> tuple[tuple[UUID, ...], tuple[UUID, ...]]:
    """Keep full directory/source recipients separate from the five used public accounts."""
    checked = NexusCodingAdmission.model_validate(initial.model_dump(warnings=False))
    owner = checked.procedure.binding.actor_id
    registered = tuple(sorted({owner, *(slot.child.binding.actor_id for slot in checked.slots)}))
    active = tuple(
        sorted(
            {
                owner,
                *(
                    slot.child.binding.actor_id
                    for slot in checked.slots
                    if slot.role in {"planner", "coder", "engineering", "engineering_check"}
                ),
            }
        )
    )
    if len(registered) != 10 or len(active) != 5 or not set(active) <= set(registered):
        raise ValueError(
            "Fixture requires ten registered principals and five distinct used accounts"
        )
    return registered, active


def _namespace(value: object) -> object:
    if isinstance(value, dict):
        return {name: _namespace(item) for name, item in value.items()}
    if isinstance(value, list):
        return [_namespace(item) for item in value]
    if isinstance(value, str):
        try:
            original = UUID(value)
            return str(COMPANY if original == ORIGINAL_COMPANY else uuid5(COMPANY, str(original)))
        except ValueError:
            return value
    return value


def _namespaced_catalog(template: PlanAdmissionCatalog) -> PlanAdmissionCatalog:
    """Rebind only synthetic registry descriptions after deriving the new company bytes."""
    data = _namespace(template.model_dump(mode="json"))
    assert isinstance(data, dict)
    registry = ModelRegistry.model_validate_json(
        json.dumps(data["models"], ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    )
    assert registry.company_id == COMPANY
    original_digest, digest = canonical_sha256(template.models), canonical_sha256(registry)
    for section in ("native_profiles", "notification_profiles"):
        rows = data[section]
        assert isinstance(rows, list)
        for row in rows:
            assert isinstance(row, dict) and row["registry_sha256"] == original_digest
            row["registry_sha256"] = digest
    admission = data["nexus_coding_admission"]
    assert isinstance(admission, dict) and admission["registry_sha256"] == original_digest
    admission["registry_sha256"] = digest
    return PlanAdmissionCatalog.model_validate_json(
        json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    )


@dataclass
class Database:
    factory: async_sessionmaker[AsyncSession]
    admin: async_sessionmaker[AsyncSession]
    system_url: str
    app_url: str
    applications: list[CodingApplication] = field(default_factory=list)
    retirement_owners: list[asyncio.Task[object]] = field(default_factory=list, repr=False)
    first_error: BaseException | None = field(default=None, repr=False)

    async def require_queue(
        self, command: SegmentCommand, role: Literal["planner", "coder"]
    ) -> None:
        """Actual durable queue metadata/input, no hand-insert or generic workflow fallback."""
        suffix = "planning" if role == "planner" else "coding"
        async with self.admin() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT s.name,s.queue_name,s.application_version,"
                        "s.application_name,s.serialization,i.inputs "
                        "FROM dbos.workflow_status s JOIN dbos.workflow_input i "
                        "ON i.workflow_uuid=s.workflow_uuid "
                        "WHERE s.workflow_uuid=:id"
                    ),
                    {"id": command.workflow_id},
                )
            ).one()
        assert tuple(row[:5]) == (
            f"company.{suffix}.v1",
            f"nexus.{suffix}",
            f"nexus-{suffix}-v1",
            f"nexus-{suffix}",
            "portable_json",
        )
        assert json.loads(row[5]) == {
            "positionalArgs": [command.model_dump_json()],
            "namedArgs": {},
        }


async def open_database() -> AsyncIterator[Database]:
    """Root-created exact new DB only; normal017/admin DBOS install, never create/reset/drop."""
    from nexus.tests.integration.nexus_coding_application_sources import required_source

    if not settings.company_test_database_url:
        pytest.skip("Exact C application release is absent")
    await asyncio.to_thread(required_source)
    claim = RELEASE_ROOT / "TEST_EXECUTION_CLAIM_1.json"
    with claim.open("x") as stream:
        json.dump({"database": DATABASE, "runtime_executions": 1}, stream)
    claim.chmod(0o600)
    old_mask = os.umask(0o077)
    url = make_url(settings.company_test_database_url)
    assert (url.drivername, url.username, url.password, url.host, url.port, url.database) == (
        "postgresql+asyncpg",
        "santapong",
        None,
        None,
        None,
        DATABASE,
    )
    assert dict(url.query) == {"host": SOCKET, "port": str(PORT)}
    assert settings.company_test_database_url != settings.database_url
    admin = create_async_engine(url, poolclass=NullPool)
    app = create_async_engine(url.set(username="nexus_company_app"), poolclass=NullPool)
    value = Database(
        async_sessionmaker(app, expire_on_commit=False),
        async_sessionmaker(admin, expire_on_commit=False),
        url.set(username="nexus_company_app", drivername="postgresql+psycopg").render_as_string(
            hide_password=False
        ),
        url.set(username="nexus_company_app").render_as_string(hide_password=False),
    )
    try:
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "upgrade")
            assert (
                await connection.scalar(text("SELECT version_num FROM company_alembic_version"))
                == "company_017"
            )
            assert (
                await connection.execute(
                    text(
                        "SELECT count(*),bool_and(c.relrowsecurity AND c.relforcerowsecurity) "
                        "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                        "WHERE n.nspname='public' AND c.relkind='r' "
                        "AND c.relname LIKE 'company_%' AND c.relname<>'company_alembic_version'"
                    )
                )
            ).one() == (74, True)
        await asyncio.to_thread(
            DBOS.migrate,
            url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False),
            application_role="nexus_company_app",
        )
        async with app.connect() as connection:
            version = int(await connection.scalar(text("SHOW server_version_num")))
            assert 170000 <= version < 180000
            assert await connection.scalar(text("SELECT current_user")) == "nexus_company_app"
            assert not await connection.scalar(
                text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user")
            )
            for name in ("fsync", "synchronous_commit", "full_page_writes"):
                assert await connection.scalar(text("SHOW " + name)) == "on"
        yield value
    finally:
        unresolved = tuple(
            task
            for task in value.retirement_owners
            if not task.done() or task.cancelled() or task.exception() is not None
        )
        if unresolved:
            first = value.first_error or RuntimeError("Actual scenario retirement is unconfirmed")
            first.__dict__["_nexus_retained_retirement"] = unresolved
            first.__dict__["_nexus_retained_engines"] = (app, admin)
            raise first
        assert all(
            not graph.lifecycle.pending_owners() and not graph.planning.lifecycle.pending_owners()
            for graph in value.applications
        )
        await app.dispose()
        await admin.dispose()
        os.umask(old_mask)


@dataclass
class Case:
    config: CodingApplicationConfig
    source: Sources
    signer: SecretStr
    configured: Settings = field(repr=False)
    tokens: dict[UUID, str] = field(repr=False)
    credentials: dict[str, Credentials] = field(repr=False)
    identities: dict[UUID, AuthenticatedWorkerIdentity] = field(repr=False)
    owner: AuthenticatedWorkerIdentity = field(repr=False)
    headers: dict[str, str] = field(repr=False)
    member_headers: dict[str, str] = field(repr=False)
    quotes: tuple[UpfrontReservation, ...]
    observation_end_us: int
    applications: list[CodingApplication] = field(default_factory=list)
    publishers: list[CodingPublicationStore] = field(default_factory=list)
    children: list[OwnedWorker] = field(default_factory=list, repr=False)
    spawns: list[PendingSpawn] = field(default_factory=list, repr=False)
    retirement_owners: list[asyncio.Task[object]] = field(default_factory=list, repr=False)

    @property
    def source_original(self) -> bytes:
        return self.source.originals

    def owner_scope(self) -> CompanyControlScope:
        return CompanyControlScope(
            company_id=COMPANY,
            principal_id=self.owner.identity.principal_id,
            operation_id=key("owner-read"),
            trace_id=key("owner-read-trace"),
        )

    def compose(self, database: Database) -> CodingApplication:
        value = compose_coding_application(
            database.factory,
            self.config,
            self.configured,
            self.credentials["planner"],
            self.credentials["coder"],
            self.signer,
        )
        self.applications.append(value)
        database.applications.append(value)
        return value

    async def approve_action(self, client: AsyncTestClient[Litestar], action: ActionRecord) -> None:
        proposal = action.proposal
        url = (
            f"/api/v2/companies/{COMPANY}/work/{proposal.task_id}"
            f"/actions/{proposal.action_id}/decision"
        )
        assert (
            await client.post(
                url,
                headers=self.headers,
                json={
                    "trace_id": str(proposal.trace_id),
                    "expected_hash": "f" * 64,
                    "approved": True,
                },
            )
        ).status_code == 409
        response = await client.post(
            url,
            headers=self.headers,
            json={
                "trace_id": str(proposal.trace_id),
                "expected_hash": action.proposal_hash,
                "approved": True,
            },
        )
        assert response.status_code == 200

    async def require_metadata_replays(
        self, app: CodingApplication, planner: SegmentCommand, coder: SegmentCommand
    ) -> None:
        for value in self.credentials.values():
            value.unavailable = True
        with patch.object(
            SettingsEndpointResolver,
            "resolve",
            side_effect=AssertionError("Metadata replay requested an endpoint"),
        ):
            first = await execute_planning_segment(
                app.planning.runtime,
                planner,
                workflow_id=planner.workflow_id,
                end_us=clock_us() + 30_000_000,
            )
            second = await execute_coding_segment(
                app.services, coder, workflow_id=coder.workflow_id, end_us=clock_us() + 30_000_000
            )
        assert all(
            row.replayed
            and row.status == "known_history"
            and row.native_state == "succeeded"
            and not row.resources_pending
            for row in (first, second)
        )


async def _authenticate(
    database: Database,
    root: Path,
    initial: NexusCodingAdmission,
    monkeypatch: pytest.MonkeyPatch,
    price_version: str,
) -> tuple[
    PersistentCompanyDirectory, dict[UUID, str], dict[UUID, AuthenticatedWorkerIdentity], SecretStr
]:
    """Public signup for only the used owner/L/C/E/EV accounts; full directory stays registered."""
    principals, active = fixture_principals(initial)
    owner = initial.procedure.binding.actor_id
    scope = CompanyControlScope(
        company_id=COMPANY,
        principal_id=owner,
        operation_id=key("bootstrap"),
        trace_id=key("bootstrap-trace"),
    )
    await CompanyJournal(database.factory).create_company(
        CompanyPolicy(
            company_id=COMPANY, owner_id=owner, policy_version=POLICY, price_version=price_version
        ),
        LedgerScope(
            company_id=COMPANY,
            principal_id=owner,
            task_id=scope.operation_id,
            trace_id=scope.trace_id,
        ),
    )
    directory = PersistentCompanyDirectory(database.factory)
    await directory.bootstrap(
        CompanyRegistration(
            company_id=COMPANY, workspace_id=initial.procedure.binding.workspace_id, owner_id=owner
        ),
        scope,
    )
    for principal in principals:
        if principal != owner:
            await directory.set_membership(
                MembershipChange(company_id=COMPANY, principal_id=principal, role="member"), scope
            )
    signer = SecretStr(secrets.token_urlsafe(48))
    monkeypatch.setattr(settings, "jwt_secret_key", signer.get_secret_value())
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256")
    invitations = {principal: secrets.token_urlsafe(48) for principal in active}
    passwords = {principal: secrets.token_urlsafe(32) for principal in active}
    account = root / "synthetic-account-hashes.json"
    save_credentials(
        account,
        PilotCredentialFile(
            accounts=tuple(
                PilotCredential(
                    company_id=COMPANY,
                    workspace_id=initial.procedure.binding.workspace_id,
                    principal_id=principal,
                    email=f"{principal}@nexus-planning.example.invalid",
                    display_name="Synthetic isolated C acceptance member",
                    signup_sha256=hashlib.sha256(invitations[principal].encode()).hexdigest(),
                    signup_expires_at=datetime.now(UTC) + timedelta(minutes=15),
                )
                for principal in active
            )
        ),
    )
    sessions = PilotSessionService(directory, account)
    common = CompanyServices(
        directory, CompanyJournal(database.factory), CompanyControls(database.factory)
    )
    tokens = {}
    async with AsyncTestClient(create_company_app(common, pilot_sessions=sessions)) as client:
        for principal in active:
            tokens[principal] = await login(
                client, principal, invitations[principal], passwords[principal]
            )
    identities = {}
    for principal, token in tokens.items():
        identities[principal] = await NotificationWorkerIdentities(
            Credentials(token), signer, enabled=True
        ).current()
    return directory, tokens, identities, signer


async def prepare_case(
    database: Database, root: Path, monkeypatch: pytest.MonkeyPatch, *, observation_end_us: int
) -> Case:
    """Cohesion exception: real public Goal/mandate/10 charters precede frozen r1 config."""
    _, template = coding_case()
    catalog = _namespaced_catalog(template)
    initial = catalog.nexus_coding_admission
    assert initial is not None
    initial = NexusCodingAdmission.model_validate(
        initial.model_dump()
        | {"procedure": initial.procedure.model_copy(update={"allocation_usd": Decimal(1)})}
    )
    catalog = PlanAdmissionCatalog.model_validate(
        catalog.model_dump() | {"nexus_coding_admission": initial}
    )
    catalog = priced_catalog(catalog)
    initial = catalog.nexus_coding_admission
    assert initial is not None
    directory, tokens, identities, signer = await _authenticate(
        database, root, initial, monkeypatch, catalog.models.pricebook_version
    )
    owner = identities[initial.procedure.binding.actor_id]
    audit = CompanyControlScope(
        company_id=COMPANY,
        principal_id=owner.identity.principal_id,
        operation_id=key("owner-setup"),
        trace_id=key("owner-setup-trace"),
    )
    brain = BrainReadScope(
        company_id=COMPANY,
        workspace_id=owner.identity.workspace_id,
        principal_id=audit.principal_id,
        operation_id=audit.operation_id,
        trace_id=audit.trace_id,
    )
    registered_readers, _ = fixture_principals(initial)
    source = await ingest_sources(database, root, owner, brain, registered_readers)
    controls = ManagementControlStore(database.factory)
    mandate = await controls.publish_mandate(
        audit,
        owner.identity,
        CompanyMandate(
            company_id=COMPANY,
            owner_id=owner.identity.principal_id,
            version=POLICY,
            purpose=(
                "Review Nexus L/C protocol and published patch; no builder or company completion"
            ),
            goals=(initial.goal.goal_id,),
        ),
        expected_revision_id=None,
    )
    mref = RevisionRef.model_validate_json(
        mandate.model_dump_json(include=set(RevisionRef.model_fields))
    )
    goals = GoalStore(database.factory, source.retriever)
    definition = GoalDefinition(
        company_id=COMPANY,
        goal_id=initial.goal.goal_id,
        owner_id=owner.identity.principal_id,
        title="Review a governed Nexus code candidate from actual committed source",
        mandate=mref,
        metrics=(
            GoalMetric(
                company_id=COMPANY,
                metric_id="nexus.patch.reviewed",
                unit="count",
                comparator="ge",
                target=Decimal(1),
                baseline=UnknownBaseline(
                    reason="Committed design evidence is not a measured completed cycle",
                    evidence=(source.document_evidence,),
                ),
            ),
        ),
        due=DueIntent(
            source_time=SourceTime(
                precision="unknown",
                value=None,
                basis="No execution date or company completion is asserted",
            )
        ),
    )
    common = CompanyServices(
        directory, CompanyJournal(database.factory), CompanyControls(database.factory)
    )
    management = ManagementApiServices(
        directory, controls, goals, ManagementPlanStore(database.factory, catalog)
    )
    headers = {"Authorization": "Bearer " + tokens[owner.identity.principal_id]}
    async with AsyncTestClient(
        create_company_app(common, management_services=management)
    ) as client:
        response = await client.post(
            f"/api/v2/companies/{COMPANY}/management/goals",
            headers=headers,
            json={
                "definition": definition.model_dump(mode="json"),
                "version": "nexus-c-goal-v1",
                "expected_revision_id": None,
            },
        )
        assert response.status_code == 200
        goal = GoalRevisionRecord.model_validate_json(response.content)
    gref = GoalRevisionRef.model_validate_json(
        goal.model_dump_json(include=set(GoalRevisionRef.model_fields))
    )
    slots = []
    verifiers = {
        "coder": initial.slots[6].child.binding.actor_id,
        "engineering": initial.slots[6].child.binding.actor_id,
        "engineering_check": initial.slots[5].child.binding.actor_id,
        "report": initial.slots[8].child.binding.actor_id,
        "report_check": initial.slots[7].child.binding.actor_id,
    }
    for slot in initial.slots:
        charter = await controls.publish_charter(
            audit,
            owner.identity,
            DepartmentCharter(
                company_id=COMPANY,
                department_id=key("department:" + slot.role),
                name=slot.role,
                version="v1",
                responsibilities=("Nexus fixed " + slot.role + " within independent native gates",),
                allowed_tools=(slot.tool.tool,),
                resource_scopes=(slot.tool.resource, "nexus.knowledge"),
                deliverables=("Reviewable Nexus " + slot.role + " evidence",),
                verifier_id=verifiers.get(slot.role, owner.identity.principal_id),
            ),
            mandate=mref,
            expected_revision_id=None,
        )
        ref = CharterRevisionRef.model_validate_json(
            charter.model_dump_json(include=set(CharterRevisionRef.model_fields))
        )
        slots.append(
            slot.model_copy(update={"child": slot.child.model_copy(update={"charter": ref})})
        )
    admission = NexusCodingAdmission.model_validate(
        initial.model_dump() | {"goal": gref, "mandate": mref, "slots": tuple(slots)}
    )
    resources = tuple(
        NamedPlanResource(
            symbol=symbol,
            resource=source.code_resource
            if symbol != "nexus.knowledge"
            else source.document_resource,
        )
        for symbol in (
            *dict.fromkeys(slot.tool.resource for slot in admission.slots),
            "nexus.knowledge",
        )
    )
    digest = canonical_sha256(catalog.models)
    catalog = PlanAdmissionCatalog.model_validate(
        catalog.model_dump()
        | {
            "resources": resources,
            "nexus_coding_admission": admission,
            "notification_profiles": tuple(
                row.model_copy(
                    update={"registry_sha256": digest, "target_resource": source.code_resource}
                )
                for row in catalog.notification_profiles
            ),
        }
    )
    quotes = upfront_quotes(catalog)
    assert len(quotes) == 5
    # Retain real full-input proofs BEFORE the first r1 request.
    quote_path = root / "maximum-quotes-before-r1.json"
    with quote_path.open("x") as stream:
        json.dump(
            {
                "observed_at": datetime.now(UTC).isoformat(),
                "registry_sha256": canonical_sha256(catalog.models),
                "root_allocation_usd": str(admission.procedure.allocation_usd),
                "quotes": [row.model_dump(mode="json") for row in quotes],
                "scope": "Synthetic catalog; real estimator/ordinary route/price, not permit",
            },
            stream,
            sort_keys=True,
        )
    quote_path.chmod(0o600)
    policies = tuple(
        source.registry.policy(spec.source_symbol) for spec in (source.document, source.code.git)
    )
    planning = PlanningApplicationConfig(
        catalog=catalog,
        policy_version=POLICY,
        role_policy=PlanningRolePolicy(
            company_id=COMPANY,
            workflow_name="company.planning.v1",
            workflow_version="v1",
            model_profile="reasoning",
            data_classification="internal",
            role_system_text=(
                "Plan the fixed Nexus roles from committed evidence; "
                "no actor, allowance or builder authority from model output."
            ),
        ),
        recipe=recipe("reasoning"),
        selection=ContextSelection(
            company_id=COMPANY, search=SearchRequest(company_id=COMPANY, query="Nexus")
        ),
        registry_id=admission.slots[0].tool.resource.removeprefix("model:"),
        max_output_tokens=8192,
        worker_id=key("planner-worker"),
        mapping_revision="nexus-c-application-mapping-v1",
        source_policies=policies,
        storage=PlanningStorage(
            brain_root=root / "brain",
            prepared_root=root / "planning-prepared",
            model_evidence_root=root / "model-evidence",
            brain_storage_symbol=source.blobs.storage_symbol,
            prepared_storage_symbol="nexus.acceptance.planning-prepared.v1",
        ),
    )
    config = CodingApplicationConfig(
        planning=planning,
        role_policy=planning.role_policy.model_copy(
            update={"workflow_name": "company.coding.v1", "model_profile": "engineering"}
        ),
        recipe=recipe("engineering"),
        registry_id=admission.slots[1].tool.resource.removeprefix("model:"),
        max_output_tokens=1024,
        worker_id=key("coder-worker"),
        code_sources=(source.code,),
        repository_selection=CodingRepositorySelection(
            company_id=COMPANY,
            source=source.source,
            files=(source.code.git,),
            allowed_write_paths=(source.code.file.path,),
        ),
        repository_path=source.receipt.repository_path,
        prepared_root=root / "coding-prepared",
        prepared_storage_symbol="nexus.acceptance.coding-prepared.v1",
    )
    configured = Settings(
        _env_file=None,
        jwt_secret_key=signer.get_secret_value(),
        jwt_algorithm="HS256",
        openai_api_key=KEY,
        google_api_key=KEY,
    )
    path = root / "application-config.json"
    with path.open("xb") as stream:
        stream.write(config.model_dump_json(by_alias=True).encode())
    path.chmod(0o600)
    return Case(
        config,
        source,
        signer,
        configured,
        tokens,
        {
            role: Credentials(tokens[admission.slots[index].child.binding.actor_id])
            for index, role in enumerate(("planner", "coder"))
        },
        identities,
        owner,
        headers,
        {"Authorization": "Bearer " + tokens[admission.slots[0].child.binding.actor_id]},
        quotes,
        observation_end_us,
    )


async def decision(
    client: AsyncTestClient[Litestar],
    case: Case,
    plan: PlanRevision,
    *,
    previous: PlanRevision | None = None,
) -> None:
    response = await client.post(
        f"/api/v2/companies/{COMPANY}/management/plans/{plan.plan_revision_id}/approve",
        headers=case.headers,
        json={
            "exact_hash": plan.sha256,
            "expected_current_revision_id": str(
                previous.plan_revision_id if previous else plan.plan_revision_id
            ),
        },
    )
    assert response.status_code == 200


async def recover_coding(
    database: Database,
    case: Case,
    app: CodingApplication,
    client: AsyncTestClient[Litestar],
    selected: dict[str, object],
    root: Path,
) -> tuple[PreparedCodingAction, CodingApplication]:
    """Controlled pending→wait gap; no fixture row/packet/TTL modification or synthetic proof."""
    record: ActionRecord | None = None

    async def stopped(
        store: ExecutionStore, lease: ExecutionLease, identity: VerifiedIdentity, action_id: UUID
    ) -> ExecutionSnapshot:
        nonlocal record
        assert store is app.services.execution and identity.principal_id == lease.actor_id
        record = await CompanyJournal(database.factory).get_action(
            LedgerScope(
                company_id=COMPANY,
                principal_id=lease.actor_id,
                task_id=lease.task_id,
                trace_id=lease.trace_id,
            ),
            action_id,
        )
        raise RuntimeError("Controlled interruption after actual C pending before owner wait")

    path = f"/api/v2/companies/{COMPANY}/coding"
    with patch.object(ExecutionStore, "await_approval", stopped):
        response = await client.post(
            path + f"/goals/{case.config.goal.goal_id}/prepare", headers=case.headers, json=selected
        )
    assert response.status_code == 500 and record is not None
    assert not app.lifecycle.pending_owners()
    cold = case.compose(database)
    assert cold.services is not app.services
    async with AsyncTestClient(coding_app(cold), raise_server_exceptions=False) as second:
        response = await second.post(
            path + f"/actions/{record.proposal.action_id}/recover-wait",
            headers=case.headers,
            json=selected | {"expected_hash": record.proposal_hash},
        )
        assert response.status_code == 200
        recovered = PreparedCodingAction.model_validate_json(response.content)
        assert recovered.action == record
        assert recovered.work.state == "awaiting_approval" and recovered.work.worker_id is None
        assert recovered.work.counters.model_requests == 0
        return recovered, cold


async def revoke_source(database: Database, case: Case) -> None:
    scope = BrainReadScope(
        company_id=COMPANY,
        workspace_id=case.owner.identity.workspace_id,
        principal_id=case.owner.identity.principal_id,
        operation_id=key("source-revoke"),
        trace_id=key("source-revoke-trace"),
    )
    async with brain_transaction(database.factory, scope, case.owner.identity, owner=True) as (
        session,
        _,
        _,
    ):
        resource = await session.get(
            BrainResource, (COMPANY, case.source.code_resource.resource_id)
        )
        assert resource is not None
        generation = resource.acl_generation
    await ResourceAccessStore(database.factory).change(
        scope,
        case.owner.identity,
        ResourceAccessChange(
            company_id=COMPANY,
            resource=case.source.code_resource,
            principal_id=case.owner.identity.principal_id,
            active=False,
            expected_generation=generation,
        ),
    )


def safe_report(
    root: Path,
    started: datetime,
    error: type[BaseException] | None,
    plans: list[PlanRevision],
    workers: list[WorkerObservation],
    publication: PublishedCodingPatch | None,
    costs: CycleCostSnapshot | None,
    *,
    child_facts: tuple[dict[str, object], ...] = (),
    retirement_pending: int = 0,
) -> None:
    """Path-free result metadata; no tokens, requests, prompts or account file."""
    raw = json.dumps(
        {
            "database": DATABASE,
            "started_utc": started.isoformat(),
            "finished_utc": datetime.now(UTC).isoformat(),
            "first_error_type": error.__name__ if error else None,
            "plan_sha256s": [row.sha256 for row in plans],
            "workers": [row.model_dump(mode="json") for row in workers],
            "child_control": child_facts,
            "retirement_pending": retirement_pending,
            "publication": publication.model_dump(mode="json") if publication else None,
            "cost": costs.model_dump(mode="json") if costs else None,
            "scope": (
                "Actual protocol only if executed: synthetic eligibility/prices, "
                "two SDK MockPOSTs; "
                "no provider quality/native E-EV/company completion"
            ),
        },
        sort_keys=True,
        indent=2,
    ).encode()
    path = root / "acceptance-evidence.json"
    with path.open("xb") as stream:
        stream.write(raw + b"\n")
    path.chmod(0o600)

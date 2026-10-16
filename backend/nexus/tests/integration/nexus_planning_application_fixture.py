"""Exact-DB production application inputs and finite SDK transport, not live quality.

Cohesion exception: these helpers reuse v5 public governance/setup and retain its
normal016/RLS/DBOS/conservation checks; no alternate company or authority layer.
Only this module's opt-in runtime calls open the exact new Root-created database.
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid5

import httpx2
import pytest
from dbos import DBOS
from litestar.testing import AsyncTestClient
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange
from nexus.company.brain.access_models import BrainResource
from nexus.company.brain.context import ContextSelection
from nexus.company.brain.retrieval import SearchRequest
from nexus.company.brain.scope_support import brain_transaction
from nexus.company.contracts.actions import ActionProposal
from nexus.company.control_store import CompanyControls
from nexus.company.directory_models import RegisteredWork
from nexus.company.management.plan_models import ManagementProcedure, ManagementRevisionEvent
from nexus.company.management.planning_authority import PlanningRolePolicy
from nexus.company.management.planning_content import PlanningContent, PlanningTask
from nexus.company.notifications.worker_identity import (
    AuthenticatedWorkerIdentity,
    NotificationWorkerIdentities,
)
from nexus.company.pilot_session import PilotSessionService
from nexus.company.pilot_session_store import PilotCredential, PilotCredentialFile, save_credentials
from nexus.company.services import CompanyServices
from nexus.company_app import create_company_app
from nexus.core.llm.company_adapter_contracts import ServerEndpoint
from nexus.core.llm.company_endpoints import SettingsEndpointResolver
from nexus.execution.planning_application import PlanningApplication, compose_planning_application
from nexus.execution.planning_application_config import PlanningApplicationConfig, PlanningStorage
from nexus.execution.planning_owner_reads import PlanningInputReview
from nexus.execution.planning_preparation import PreparedPlanningAction
from nexus.execution.runtime_contracts import ExecutionLease, ExecutionSnapshot
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt, ExecutionWork
from nexus.execution.runtime_store import ExecutionStore
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_models import CostHold, DailyBudget, JournalAction, WorkBudget
from nexus.settings import Settings, settings
from nexus.tests.integration.nexus_planning_runtime_fixture import (
    COMPANY,
    Governance,
    bootstrap,
    brain_owner,
    governance,
    input_recipe,
)
from nexus.tests.integration.test_company_directory import migrate
from nexus.tests.integration.test_nexus_planning_runtime import Credentials, login
from nexus.tests.integration.test_nexus_planning_runtime import Database as Database
from nexus.tests.unit.test_company_provider_conformance import KEY, response

DATABASE = "nexus_company_test_nexus_owner_planning_v1"
SOCKET = "/tmp/nexus-release-tests-2026-10-13/socket"


def key(label: str) -> UUID:
    return uuid5(COMPANY, "nexus-owner-planning-application-v1:" + label)


async def open_database() -> AsyncIterator[Database]:
    """No create/drop/reset: Root must release exactly this empty database separately."""
    if not settings.company_test_database_url:
        pytest.skip("Exact owner application runtime cohort is not released")
    url = make_url(settings.company_test_database_url)
    assert (url.drivername, url.username, url.password, url.host, url.port, url.database) == (
        "postgresql+asyncpg",
        "santapong",
        None,
        None,
        None,
        DATABASE,
    )
    assert dict(url.query) == {"host": SOCKET, "port": "55438"}
    assert settings.company_test_database_url != settings.database_url
    admin = create_async_engine(url, poolclass=NullPool)
    app = create_async_engine(url.set(username="nexus_company_app"), poolclass=NullPool)
    value = Database(
        factory=async_sessionmaker(app, expire_on_commit=False),
        admin=async_sessionmaker(admin, expire_on_commit=False),
        system_url=url.set(
            username="nexus_company_app", drivername="postgresql+psycopg"
        ).render_as_string(hide_password=False),
    )
    try:
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "upgrade")
            assert (
                await connection.scalar(text("SELECT version_num FROM company_alembic_version"))
                == "company_016"
            )
            assert (
                await connection.execute(
                    text(
                        "SELECT count(*),bool_and(c.relrowsecurity AND c.relforcerowsecurity) "
                        "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                        "WHERE n.nspname='public' AND c.relkind='r' AND c.relname LIKE 'company_%' "
                        "AND c.relname<>'company_alembic_version'"
                    )
                )
            ).one() == (74, True)
        await asyncio.to_thread(
            DBOS.migrate,
            url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False),
            application_role="nexus_company_app",
        )
        async with app.connect() as connection:
            assert await connection.scalar(text("SELECT current_user")) == "nexus_company_app"
            assert not await connection.scalar(
                text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user")
            )
            for setting in ("fsync", "synchronous_commit", "full_page_writes"):
                assert await connection.scalar(text(f"SHOW {setting}")) == "on"
        yield value
    finally:
        assert all(not services.pending_owners() for services in value.owners)
        assert all(
            not any(op.running for op in services._operations.values()) for services in value.owners
        )
        await app.dispose()
        await admin.dispose()  # Preserve every schema/row/failure for independent audit.


@dataclass
class Case:
    ready: Governance
    config: PlanningApplicationConfig
    application_settings: Settings
    signer: SecretStr
    credentials: Credentials
    owner: AuthenticatedWorkerIdentity
    engineer: AuthenticatedWorkerIdentity
    headers: dict[str, str]
    member_headers: dict[str, str]
    applications: list[PlanningApplication] = field(default_factory=list)

    def compose(self, database: Database) -> PlanningApplication:
        value = compose_planning_application(
            database.factory, self.config, self.application_settings, self.credentials, self.signer
        )
        self.applications.append(value)
        database.owners.append(value.runtime)
        return value


async def prepare_case(database: Database, root: Path, monkeypatch: pytest.MonkeyPatch) -> Case:
    """Actual public signup/login and immutable Nexus Brain/management setup from v5."""
    initial, directory = await bootstrap(database.factory)
    owner_id = initial.procedure.binding.actor_id
    planner = initial.slots[0].child.binding
    engineer = initial.slots[1].child.binding.actor_id
    signer = secrets.token_urlsafe(48)
    monkeypatch.setattr(settings, "jwt_secret_key", signer)
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256")
    invitations = {
        principal: secrets.token_urlsafe(48) for principal in (owner_id, planner.actor_id, engineer)
    }
    passwords = {principal: secrets.token_urlsafe(32) for principal in invitations}
    account = root / "accounts.json"
    save_credentials(
        account,
        PilotCredentialFile(
            accounts=tuple(
                PilotCredential(
                    company_id=COMPANY,
                    workspace_id=planner.workspace_id,
                    principal_id=principal,
                    email=f"{principal}@nexus-planning.example.invalid",
                    display_name="Isolated Nexus application member",
                    signup_sha256=hashlib.sha256(invitation.encode()).hexdigest(),
                    signup_expires_at=datetime.now(UTC) + timedelta(minutes=10),
                )
                for principal, invitation in invitations.items()
            )
        ),
    )
    common = CompanyServices(
        directory, CompanyJournal(database.factory), CompanyControls(database.factory)
    )
    sessions = PilotSessionService(directory, account)
    tokens: dict[UUID, str] = {}
    async with AsyncTestClient(create_company_app(common, pilot_sessions=sessions)) as client:
        for principal, invitation in invitations.items():
            tokens[principal] = await login(client, principal, invitation, passwords[principal])
    sources = {principal: Credentials(token) for principal, token in tokens.items()}
    identities = {
        principal: NotificationWorkerIdentities(source, SecretStr(signer), enabled=True)
        for principal, source in sources.items()
    }
    owner = await identities[owner_id].current()
    actor = await identities[planner.actor_id].current()
    engineering = await identities[engineer].current()
    assert owner.identity.principal_id != actor.identity.principal_id
    ready = await governance(database.factory, root, initial, owner)
    config = PlanningApplicationConfig(
        catalog=ready.catalog,
        policy_version="nexus-planning-runtime-v1",
        role_policy=PlanningRolePolicy(
            company_id=COMPANY,
            workflow_name="company.planning.v1",
            workflow_version="v1",
            model_profile="reasoning",
            data_classification="internal",
            role_system_text=(
                "Plan a bounded Nexus change from cited evidence; never claim builder completion."
            ),
        ),
        recipe=input_recipe(),
        selection=ContextSelection(
            company_id=COMPANY, search=SearchRequest(company_id=COMPANY, query="Nexus")
        ),
        registry_id="nexus-planner",
        max_output_tokens=512,
        worker_id=key("planner-worker"),
        mapping_revision="nexus-owner-application-mapping-v1",
        source_policies=(ready.registry.policy("nexus.architecture.runtime.v1"),),
        storage=PlanningStorage(
            brain_root=root / "brain",
            prepared_root=root / "prepared",
            model_evidence_root=root / "model-evidence",
            brain_storage_symbol=ready.blobs.storage_symbol,
            prepared_storage_symbol="nexus.planning.application.prepared.v1",
        ),
    )
    configured = Settings(
        _env_file=None,
        jwt_secret_key=signer,
        jwt_algorithm="HS256",
        openai_api_key=KEY,
        google_api_key="",
    )
    return Case(
        ready,
        config,
        configured,
        SecretStr(signer),
        sources[planner.actor_id],
        owner,
        engineering,
        {"Authorization": "Bearer " + tokens[owner_id]},
        {"Authorization": "Bearer " + tokens[planner.actor_id]},
    )


@dataclass
class Probe:
    content: PlanningContent | None = None
    posts: list[str] = field(default_factory=list)
    lookups: int = 0
    unavailable: bool = False
    pending: ActionProposal | None = None
    pending_hash: str | None = None

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Keep actual configured resolver/bindings; inject only the endpoint's SDK transport."""
        original = SettingsEndpointResolver.resolve

        async def resolve(resolver: SettingsEndpointResolver, endpoint_id: str) -> ServerEndpoint:
            assert not self.unavailable, "Historical replay attempted endpoint/credential lookup"
            endpoint = await original(resolver, endpoint_id)
            assert (
                endpoint.endpoint_id,
                endpoint.provider,
                endpoint.api_family,
                endpoint.base_url,
            ) == (
                "fixture.nexus",
                "openai",
                "openai_responses",
                "https://api.openai.com/v1",
            )
            assert endpoint.api_key.get_secret_value() == KEY
            self.lookups += 1
            return replace(endpoint, transport=httpx2.MockTransport(self.wire), timeout_seconds=2)

        monkeypatch.setattr(SettingsEndpointResolver, "resolve", resolve)

    def wire(self, request: httpx2.Request) -> httpx2.Response:
        assert request.method == "POST" and self.content is not None
        assert str(request.url) == "https://api.openai.com/v1/responses"
        self.posts.append(hashlib.sha256(request.content).hexdigest())
        body = response("openai")
        body["model"] = "gpt-5.4-mini-2026-03-17"
        body["output"] = [
            {
                "id": "nexus-application-plan",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": self.content.model_dump_json(),
                        "annotations": [],
                    }
                ],
            }
        ]
        return httpx2.Response(200, json=body)

    def candidate(self, case: Case, review: PlanningInputReview) -> None:
        evidence = review.prepared.context.manifest.inclusions[0].handle.evidence_id
        self.content = PlanningContent(
            tasks=tuple(
                PlanningTask(
                    key=slot.role,
                    title="Nexus " + slot.role + " remains subject to native gates",
                    description="Use cited Nexus architecture to review this fixed bounded role.",
                    acceptance=slot.work.acceptance,
                    depends_on=tuple(
                        other.role
                        for other in case.ready.admission.slots[1:]
                        if other.work.task_id in slot.work.depends_on
                    ),
                    evidence_ids=(evidence,),
                )
                for slot in case.ready.admission.slots[1:]
            ),
            questions=("Owner plan approval does not qualify or start a builder.",),
        )

    def interrupt(
        self,
        database: Database,
        application: PlanningApplication,
    ) -> Callable[
        [ExecutionStore, ExecutionLease, VerifiedIdentity, UUID], Awaitable[ExecutionSnapshot]
    ]:
        async def stopped(
            store: ExecutionStore,
            lease: ExecutionLease,
            identity: VerifiedIdentity,
            action_id: UUID,
        ) -> ExecutionSnapshot:
            assert (
                store is application.runtime.execution and lease.actor_id == identity.principal_id
            )
            async with database.factory() as session, session.begin():
                await session.execute(text("SET TRANSACTION READ ONLY"))
                await session.execute(
                    select(func.set_config("nexus.company_id", str(COMPANY), True))
                )
                row = await session.get(JournalAction, action_id)
                assert (
                    row is not None and row.state == "awaiting_approval" and row.consumed_at is None
                )
                self.pending = ActionProposal.model_validate_json(row.proposal_json)
                self.pending_hash = row.proposal_hash
                assert self.pending.actor_id == identity.principal_id
            raise RuntimeError("Controlled interruption after actual pending publication")

        return stopped


async def revoke_document(database: Database, case: Case) -> None:
    scope = brain_owner(case.ready.admission)
    async with brain_transaction(database.factory, scope, case.owner.identity, owner=True) as (
        session,
        _,
        _,
    ):
        row = await session.get(BrainResource, (COMPANY, case.ready.doc_resource.resource_id))
        assert row is not None
        generation = row.acl_generation
    await ResourceAccessStore(database.factory).change(
        scope,
        case.owner.identity,
        ResourceAccessChange(
            company_id=COMPANY,
            resource=case.ready.doc_resource,
            principal_id=case.owner.identity.principal_id,
            active=False,
            expected_generation=generation,
        ),
    )


async def conserved(
    database: Database, case: Case, recovered: PreparedPlanningAction, action_id: UUID
) -> None:
    """Retain v5's exact native row/money/lease assertions after explicit recovery and replay."""
    async with database.factory() as session, session.begin():
        await session.execute(text("SET TRANSACTION READ ONLY"))
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        root = await session.get(
            ExecutionWork, (COMPANY, case.ready.admission.procedure.binding.task_id)
        )
        planner = await session.get(
            ExecutionWork, (COMPANY, case.ready.admission.slots[0].child.binding.task_id)
        )
        builder = await session.get(
            ExecutionWork, (COMPANY, case.ready.admission.slots[1].child.binding.task_id)
        )
        assert root and planner and builder
        assert (root.model_requests_used, root.tool_attempts_used, root.plan_revisions_used) == (
            0,
            0,
            1,
        )
        assert (root.model_requests_delegated, root.tool_attempts_delegated) == (1, 5)
        assert planner.model_requests_used == 1 and builder.tool_attempts_used == 0
        assert all(
            value.worker_id is None and value.lease_until is None
            for value in (root, planner, builder)
        )
        for model, count in (
            (RegisteredWork, 7),
            (ExecutionWork, 7),
            (ExecutionAttempt, 1),
            (EffectIntent, 1),
            (ManagementProcedure, 1),
            (ManagementRevisionEvent, 1),
        ):
            assert await session.scalar(select(func.count()).select_from(model)) == count
        holds = list((await session.scalars(select(CostHold))).all())
        assert len(holds) == 2
        model_hold = next(row for row in holds if row.action_id == action_id)
        assert model_hold.state == "reconciled" and model_hold.actual_usd is not None
        assert model_hold.amount_usd == recovered.quote.amount_usd
        assert all(row.amount_usd == 0 for row in holds if row is not model_hold)
        budget = await session.get(WorkBudget, (COMPANY, planner.task_id))
        day = await session.scalar(select(DailyBudget))
        assert budget and day and budget.spent_usd == day.spent_usd == model_hold.actual_usd
        assert budget.held_usd == day.held_usd == 0
        effect = await session.get(EffectIntent, (COMPANY, action_id))
        assert (
            effect is not None and effect.state == "succeeded" and effect.receipt_json is not None
        )

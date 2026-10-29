"""One retained restricted-PG/HTTP/DBOS Nexus planner/owner proof, NOT a business cycle.

Cohesion exception: this opt-in sequence retains its one fresh DB, real JWTs,
protected inputs, queue, SDK mock, native gates and exact conservation together.
Synthetic eligibility is fixture-only. No builder/process, live provider, email,
Pi, existing preview/account, database reset/drop or process-restart claim.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import httpx2
import pytest
from dbos import DBOS, WorkflowHandleAsync
from litestar import Litestar
from litestar.testing import AsyncTestClient
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from nexus.builder.contained_query import clock_us
from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange
from nexus.company.brain.context import ContextLimits, ContextSelection
from nexus.company.brain.context_store import PersistentContextAssembler
from nexus.company.brain.retrieval import SearchRequest
from nexus.company.brain.scope_support import brain_transaction
from nexus.company.contracts.actions import ActionProposal
from nexus.company.control_store import CompanyControls
from nexus.company.directory_models import RegisteredWork
from nexus.company.management.action_review_store import OwnerActionReviewStore
from nexus.company.management.api_services import ManagementApiServices
from nexus.company.management.lifecycle import PlanRevision
from nexus.company.management.owner_view_store import ManagementOwnerViews
from nexus.company.management.plan_models import ManagementProcedure, ManagementRevisionEvent
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.planning_authority import (
    ManagementPlanningAuthority,
    PlanningRolePolicy,
)
from nexus.company.management.planning_content import PlanningContent, PlanningTask
from nexus.company.management.planning_prepared_store import PlanningPreparedStore
from nexus.company.management.planning_proposal_bridge import (
    PlanningProposalBridge,
    PlanningProposalTemplate,
    PlanningTaskSlot,
)
from nexus.company.management.planning_source_reader import PlanningSourceReader
from nexus.company.notifications.worker_identity import NotificationWorkerIdentities
from nexus.company.pilot_session import PilotSessionService
from nexus.company.pilot_session_store import PilotCredential, PilotCredentialFile, save_credentials
from nexus.company.services import CompanyServices
from nexus.company_app import create_company_app
from nexus.core.llm.company_adapter_contracts import ServerEndpoint
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.intent_checks import CompositeBeforeIntentCheck
from nexus.execution.planning_dispatch import dispatch
from nexus.execution.planning_owner_reads import (
    PlanningApiServices,
    PlanningInputReader,
    PlanningInputReview,
)
from nexus.execution.planning_preparation import prepare_work
from nexus.execution.planning_services import (
    APPLICATION,
    APPLICATION_VERSION,
    QUEUE,
    VERSION,
    WORKFLOW,
    PlanningServices,
)
from nexus.execution.planning_worker import (
    PlanningSegmentResult,
    configure_planning_worker,
    execute_planning_segment,
    launch_planning_worker,
)
from nexus.execution.runtime_contracts import ExecutionDeniedError
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt, ExecutionWork
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import (
    CompanyControl,
    CostHold,
    DailyBudget,
    JournalAction,
    WorkBudget,
)
from nexus.harness.model_evidence import FileModelEvidenceStore
from nexus.harness.model_input_estimator import FullContextInputEstimator
from nexus.settings import settings
from nexus.tests.integration.nexus_planning_runtime_fixture import (
    COMPANY,
    DOCUMENT_COMMIT,
    DOCUMENT_SHA256,
    Governance,
    bootstrap,
    brain_owner,
    governance,
    input_recipe,
    key,
    owner_scope,
)
from nexus.tests.integration.test_company_directory import migrate
from nexus.tests.unit.test_company_provider_conformance import KEY, response

DATABASE = "nexus_company_test_nexus_planning_runtime_v5"
SOCKET = "/tmp/nexus-release-tests-2026-10-13/socket"


@dataclass
class Database:
    factory: async_sessionmaker[AsyncSession]
    admin: async_sessionmaker[AsyncSession]
    system_url: str
    owners: list[PlanningServices] = field(default_factory=list)


@pytest.fixture
async def database() -> AsyncIterator[Database]:
    """Only the Root-approved fresh DB; collect/static do not execute this fixture."""
    if not settings.company_test_database_url:
        pytest.skip("Exact fresh Nexus planning DB/source cohort is not released")
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
        async_sessionmaker(app, expire_on_commit=False),
        async_sessionmaker(admin, expire_on_commit=False),
        url.set(username="nexus_company_app", drivername="postgresql+psycopg").render_as_string(
            hide_password=False
        ),
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
        # Never dispose resources still owned by an actual SDK/native/file operation.
        assert all(not services.pending_owners() for services in value.owners)
        await app.dispose()
        await admin.dispose()  # Preserve normal schemas, all native rows and failures.


class Credentials:
    def __init__(self, token: str) -> None:
        self.token, self.unavailable = SecretStr(token), False

    async def credential(self) -> SecretStr:
        if self.unavailable:
            raise AssertionError("Historical replay attempted fresh credentials")
        return self.token


class Resolver:
    """Actual pinned OpenAI SDK with one fake-key MockTransport; no provider access."""

    def __init__(self) -> None:
        self.content: PlanningContent | None = None
        self.posts: list[str] = []
        self.lookups = 0
        self.unavailable = False

    async def resolve(self, endpoint_id: str) -> ServerEndpoint:
        assert endpoint_id == "fixture.nexus" and not self.unavailable
        self.lookups += 1

        def wire(request: httpx2.Request) -> httpx2.Response:
            assert request.method == "POST" and self.content is not None
            self.posts.append(hashlib.sha256(request.content).hexdigest())
            body = response("openai")
            body["model"] = "gpt-5.4-mini-2026-03-17"
            body["output"] = [
                {
                    "id": "nexus-planning-message",
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

        return ServerEndpoint(
            endpoint_id=endpoint_id,
            provider="openai",
            api_family="openai_responses",
            base_url="https://api.openai.com/v1",
            api_key=SecretStr(KEY),
            timeout_seconds=2,
            transport=httpx2.MockTransport(wire),
        )


async def queue_row(database: Database, command: SegmentCommand) -> None:
    async with database.admin() as session:
        row = (
            await session.execute(
                text(
                    "SELECT s.name,s.queue_name,s.application_version,s.application_name,"
                    "s.serialization,i.inputs FROM dbos.workflow_status s "
                    "JOIN dbos.workflow_input i ON i.workflow_uuid=s.workflow_uuid "
                    "WHERE s.workflow_uuid=:id"
                ),
                {"id": command.workflow_id},
            )
        ).one()
        assert tuple(row[:5]) == (
            WORKFLOW,
            QUEUE,
            APPLICATION_VERSION,
            APPLICATION,
            "portable_json",
        )
        assert json.loads(row[5]) == {
            "positionalArgs": [command.model_dump_json()],
            "namedArgs": {},
        }


async def result(workflow_id: str) -> PlanningSegmentResult:
    handle: WorkflowHandleAsync[str] = await DBOS.retrieve_workflow_async(workflow_id)
    raw = await asyncio.wait_for(handle.get_result(polling_interval_sec=0.05), timeout=90)
    return PlanningSegmentResult.model_validate_json(raw)


async def login(
    client: AsyncTestClient[Litestar], principal: UUID, invitation: str, password: str
) -> str:
    email = f"{principal}@nexus-planning.example.invalid"
    created = await client.post(
        "/api/v2/company-session/signup",
        json={"email": email, "password": password, "invitation": invitation},
    )
    assert created.status_code == 201
    logged = await client.post(
        "/api/v2/company-session/login", json={"email": email, "password": password}
    )
    assert logged.status_code == 200 and UUID(logged.json()["user"]["user_id"]) == principal
    return str(logged.json()["access_token"])


class WrongBuilderCheck:
    """Negative substitution only; the concrete gate must reject before calling it."""

    async def validate(
        self,
        session: AsyncSession,
        control: CompanyControl,
        work: ExecutionWork,
        action: JournalAction,
        now: datetime,
    ) -> None:
        raise AssertionError("Generic callback crossed the concrete builder gate")


async def denied_builder(
    database: Database,
    ready: Governance,
    identity: VerifiedIdentity,
    client: AsyncTestClient[Litestar],
    headers: dict[str, str],
) -> None:
    """Actual owner-approved zero-cost metadata and lease still cannot start a builder."""
    slot = ready.admission.slots[1]
    bound = slot.child.binding
    scope = LedgerScope(
        company_id=COMPANY,
        principal_id=identity.principal_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
    )
    journal = CompanyJournal(database.factory)
    proposed = await journal.submit(
        ActionProposal(
            company_id=COMPANY,
            action_id=key("unconfigured-builder-action"),
            task_id=bound.task_id,
            trace_id=bound.trace_id,
            actor_id=identity.principal_id,
            revision=1,
            tool=slot.tool.tool,
            tool_version=slot.tool.tool_version,
            resource=slot.tool.resource,
            parameters={},
            policy_version="nexus-planning-runtime-v1",
            price_version="p1",
            estimated_cost_usd=Decimal(0),
        ),
        scope,
    )
    decision = await client.post(
        f"/api/v2/companies/{COMPANY}/work/{bound.task_id}/actions/{proposed.proposal.action_id}/decision",
        headers=headers,
        json={
            "trace_id": str(bound.trace_id),
            "expected_hash": proposed.proposal_hash,
            "approved": True,
        },
    )
    assert decision.status_code == 200
    await journal.authorize_registered(
        scope, proposed.proposal.action_id, datetime.now(UTC), (), identity=identity
    )
    execution = ready.management.execution_store(database.factory)
    lease = await execution.claim(scope, identity, key("denied-builder-worker"), ttl_seconds=30)
    effects = ready.management.effect_store(database.factory)
    try:
        for check in (None, CompositeBeforeIntentCheck((WrongBuilderCheck(), WrongBuilderCheck()))):
            with pytest.raises(ExecutionDeniedError, match="Fresh Nexus intent requires"):
                await effects.begin(
                    lease, identity, proposed.proposal.action_id, before_intent=check
                )
    finally:
        await execution.release(lease, identity, blocked=True)


async def test_actual_owner_planner_and_same_root_revision_without_builder_issuance(
    database: Database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = datetime.now(UTC)
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    initial, directory = await bootstrap(database.factory)
    owner_id = initial.procedure.binding.actor_id
    planner = initial.slots[0].child.binding
    engineering = initial.slots[1].child.binding
    signer = secrets.token_urlsafe(48)
    monkeypatch.setattr(settings, "jwt_secret_key", signer)
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256")
    invitations = {
        principal: secrets.token_urlsafe(48)
        for principal in (owner_id, planner.actor_id, engineering.actor_id)
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
                    display_name="Isolated Nexus runtime member",
                    signup_sha256=hashlib.sha256(invitation.encode()).hexdigest(),
                    signup_expires_at=datetime.now(UTC) + timedelta(minutes=10),
                )
                for principal, invitation in invitations.items()
            )
        ),
    )
    sessions = PilotSessionService(directory, account)
    common = CompanyServices(
        directory, CompanyJournal(database.factory), CompanyControls(database.factory)
    )
    tokens: dict[UUID, str] = {}
    async with AsyncTestClient(create_company_app(common, pilot_sessions=sessions)) as client:
        for principal, invitation in invitations.items():
            tokens[principal] = await login(client, principal, invitation, passwords[principal])
    credential_sources = {principal: Credentials(token) for principal, token in tokens.items()}
    identities = {
        principal: NotificationWorkerIdentities(source, SecretStr(signer), enabled=True)
        for principal, source in credential_sources.items()
    }
    owner = await identities[owner_id].current()
    actor = await identities[planner.actor_id].current()
    engineer = await identities[engineering.actor_id].current()
    assert owner.identity.principal_id != actor.identity.principal_id
    ready = await governance(database.factory, root, initial, owner)
    scope = owner_scope(ready.admission)
    plans = ManagementPlanStore(
        database.factory, ready.catalog, source_freshness=ready.sources.freshness
    )
    base_path = f"/api/v2/companies/{COMPANY}"
    headers = {"Authorization": "Bearer " + tokens[owner_id]}
    member_headers = {"Authorization": "Bearer " + tokens[planner.actor_id]}
    management = ManagementApiServices(directory, ready.controls, ready.goals, plans)
    # Real signed owner HTTP establishes the actual native r1 root and L work.
    async with AsyncTestClient(
        create_company_app(common, pilot_sessions=sessions, management_services=management)
    ) as client:
        proposal = await client.post(
            base_path + "/management/plans",
            headers=headers,
            json={
                "payload": ready.admission.payload("planning").model_dump(mode="json"),
                "expected_current_revision_id": None,
            },
        )
        assert proposal.status_code == 200
        base = PlanRevision.model_validate_json(proposal.content)
        approved = await client.post(
            base_path + f"/management/plans/{base.plan_revision_id}/approve",
            headers=headers,
            json={
                "exact_hash": base.sha256,
                "expected_current_revision_id": str(base.plan_revision_id),
            },
        )
        assert approved.status_code == 200
    template = PlanningProposalTemplate(
        base_plan=base,
        revision="nexus-runtime-mapping-v1",
        slots=tuple(
            PlanningTaskSlot(
                key=slot.role,
                allocation=slot.child,
                department=slot.work.department,
                required_dependencies=slot.work.depends_on,
            )
            for slot in ready.admission.slots[1:]
        ),
        nexus_admission=ready.admission,
    )
    models = FileModelEvidenceStore(root / "model-evidence")
    source_reader = PlanningSourceReader(
        database.factory, models, ready.retriever, ready.sources, template
    )
    plans = ManagementPlanStore(
        database.factory,
        ready.catalog,
        source_freshness=ready.sources.freshness,
        planning_reader=source_reader,
    )
    recipe = input_recipe()
    authority = ManagementPlanningAuthority(
        ready.management,
        PlanningRolePolicy(
            company_id=COMPANY,
            workflow_name=WORKFLOW,
            workflow_version=VERSION,
            model_profile="reasoning",
            data_classification="internal",
            role_system_text=(
                "Plan a bounded Nexus change from cited company evidence. "
                "Never claim builder completion."
            ),
        ),
        recipe,
    )
    contexts = PersistentContextAssembler(
        database.factory,
        ready.retriever,
        authority,
        limits=ContextLimits(policy_version="nexus-planning-runtime-v1"),
    )
    prepared_store = PlanningPreparedStore(
        database.factory,
        type(ready.blobs)(root / "prepared", storage_symbol="nexus.planning.runtime.prepared.v1"),
        ready.sources,
        recipe,
    )
    management = ManagementApiServices(
        directory,
        ready.controls,
        ready.goals,
        plans,
        views=ManagementOwnerViews(database.factory, ready.sources),
        action_reviews=OwnerActionReviewStore(
            database.factory, ready.catalog, ready.sources, planning=prepared_store
        ),
    )
    resolver = Resolver()
    services = PlanningServices(
        database.factory,
        ready.management,
        contexts,
        prepared_store,
        FullContextInputEstimator(ready.catalog.models, recipe),
        recipe,
        identities[planner.actor_id],
        resolver,
        models,
        key("planning-worker"),
        "nexus-planner",
        512,
        ContextSelection(
            company_id=COMPANY, search=SearchRequest(company_id=COMPANY, query="Nexus")
        ),
    )
    database.owners.append(services)
    api = PlanningApiServices(PlanningInputReader(prepared_store, ready.catalog.models))
    command: SegmentCommand | None = None
    outcomes: list[PlanningSegmentResult] = []
    revised: PlanRevision | None = None
    dbos_attempted = False
    try:
        app = create_company_app(
            common, pilot_sessions=sessions, management_services=management, planning_services=api
        )
        async with AsyncTestClient(app, raise_server_exceptions=True) as client:
            work_scope = LedgerScope(
                company_id=COMPANY,
                principal_id=planner.actor_id,
                task_id=planner.task_id,
                trace_id=planner.trace_id,
            )
            prepared = await prepare_work(services, work_scope, end_us=clock_us() + 120_000_000)
            assert prepared.work.state == "awaiting_approval" and prepared.work.worker_id is None
            assert prepared.work.counters.model_requests == 0 and not resolver.posts
            action = prepared.action.proposal
            path = base_path + f"/planning/actions/{action.action_id}/input"
            assert (await client.get(path)).status_code == 401
            assert (await client.get(path, headers=member_headers)).status_code == 403
            viewed = await client.get(path, headers=headers)
            assert viewed.status_code == 200
            review = PlanningInputReview.model_validate_json(viewed.content)
            assert review.prepared.input_estimate and review.prepared.input_estimate.whole_request
            assert review.prepared.input_estimate.total_tokens == 400_000
            assert review.maximum_reservation_usd == prepared.quote.amount_usd
            assert (
                review.prepared.context.manifest.inclusions
                and "Nexus" in review.prepared.request.input_text
            )
            assert KEY not in viewed.text and str(root) not in viewed.text
            generic = await client.get(
                base_path + f"/management/actions/{action.action_id}/review", headers=headers
            )
            assert generic.status_code == 200 and generic.json()["availability"] == "available"
            wrong = ready.catalog.models.model_copy(
                update={
                    "models": (
                        ready.catalog.models.models[0].model_copy(
                            update={"model_id": "crossed-model"}
                        ),
                    )
                }
            )
            with pytest.raises(ValueError, match="original registry/model"):
                await PlanningInputReader(prepared_store, wrong).input(
                    scope, owner.identity, action.action_id, end_us=clock_us() + 30_000_000
                )
            with pytest.raises(TimeoutError):
                await api.reads.input(
                    scope, owner.identity, action.action_id, end_us=clock_us() - 1
                )
            decision_path = (
                base_path + f"/work/{planner.task_id}/actions/{action.action_id}/decision"
            )
            wrong_hash = await client.post(
                decision_path,
                headers=headers,
                json={
                    "trace_id": str(planner.trace_id),
                    "expected_hash": "f" * 64,
                    "approved": True,
                },
            )
            assert wrong_hash.status_code == 409
            decision = await client.post(
                decision_path,
                headers=headers,
                json={
                    "trace_id": str(planner.trace_id),
                    "expected_hash": prepared.action.proposal_hash,
                    "approved": True,
                },
            )
            assert decision.status_code == 200 and not resolver.posts
            dispatch_scope = review.prepared.scope.model_copy(
                update={"operation_id": key("dispatch-read")}
            )
            sent = await dispatch(
                services,
                dispatch_scope,
                action.action_id,
                prepared.action.proposal_hash,
                end_us=clock_us() + 30_000_000,
            )
            command = sent.command
            await queue_row(database, command)
            assert await dispatch(
                services,
                dispatch_scope,
                action.action_id,
                prepared.action.proposal_hash,
                end_us=clock_us() + 30_000_000,
            ) == sent.model_copy(update={"disposition": "existing"})
            evidence_ids = tuple(
                row.handle.evidence_id for row in review.prepared.context.manifest.inclusions
            )
            resolver.content = PlanningContent(
                tasks=tuple(
                    PlanningTask(
                        key=slot.role,
                        title="Nexus " + slot.role + " remains subject to native gates",
                        description=(
                            "Use the cited Nexus architecture to review the fixed bounded role."
                        ),
                        acceptance=slot.work.acceptance,
                        depends_on=tuple(
                            other.role
                            for other in ready.admission.slots[1:]
                            if other.work.task_id in slot.work.depends_on
                        ),
                        evidence_ids=(evidence_ids[0],),
                    )
                    for slot in ready.admission.slots[1:]
                ),
                questions=("Owner approval of this plan does not qualify or start a builder.",),
            )
            dbos_attempted = True
            configure_planning_worker(services, database.system_url)
            await launch_planning_worker()
            observed = await result(command.workflow_id)
            outcomes.append(observed)
            assert (
                observed.status == "historical_candidate" and observed.native_state == "succeeded"
            )
            assert (
                observed.lease_released
                and not observed.resources_pending
                and len(resolver.posts) == 1
            )
            assert not services.pending_owners()
            bridge = PlanningProposalBridge(plans, source_reader)
            revised = await bridge.propose(
                scope,
                owner.identity,
                action.action_id,
                expected_goal=ready.admission.goal,
                expected_current_revision_id=base.plan_revision_id,
                end_us=clock_us() + 30_000_000,
                credential=owner,
            )
            assert revised.revision == 2 and revised.payload.procedure == base.payload.procedure
            assert (
                revised.payload.children[0] == base.payload.children[0]
                and len(revised.payload.children) == 6
            )
            approved = await client.post(
                base_path + f"/management/plans/{revised.plan_revision_id}/approve",
                headers=headers,
                json={
                    "exact_hash": revised.sha256,
                    "expected_current_revision_id": str(base.plan_revision_id),
                },
            )
            assert approved.status_code == 200
            assert (
                await plans.approve_and_register(
                    scope,
                    owner.identity,
                    revised.plan_revision_id,
                    revised.sha256,
                    expected_current_revision_id=revised.plan_revision_id,
                    credential=owner,
                    end_us=clock_us() + 30_000_000,
                )
                == revised
            )
            resolver.unavailable = True
            credential_sources[planner.actor_id].unavailable = True
            replay = await execute_planning_segment(
                services, command, workflow_id=command.workflow_id, end_us=clock_us() + 30_000_000
            )
            outcomes.append(replay)
            assert (
                replay.replayed
                and replay.status == "known_history"
                and replay.native_state == "succeeded"
            )
            assert not replay.resources_pending and len(resolver.posts) == resolver.lookups == 1
            await denied_builder(database, ready, engineer.identity, client, headers)
            assert len(resolver.posts) == 1
            # A current source revoke is last; no grant restoration/new context/request is minted.
            async with brain_transaction(
                database.factory, brain_owner(ready.admission), owner.identity, owner=True
            ) as (session, _, _):
                from nexus.company.brain.access_models import BrainResource

                resource = await session.get(
                    BrainResource, (COMPANY, ready.doc_resource.resource_id)
                )
                assert resource is not None
                generation = resource.acl_generation
            await ResourceAccessStore(database.factory).change(
                brain_owner(ready.admission),
                owner.identity,
                ResourceAccessChange(
                    company_id=COMPANY,
                    resource=ready.doc_resource,
                    principal_id=owner_id,
                    active=False,
                    expected_generation=generation,
                ),
            )
            with pytest.raises(ValueError):
                await plans.approve_and_register(
                    scope,
                    owner.identity,
                    revised.plan_revision_id,
                    revised.sha256,
                    expected_current_revision_id=revised.plan_revision_id,
                    credential=owner,
                    end_us=clock_us() + 30_000_000,
                )
            async with database.factory() as session, session.begin():
                await session.execute(
                    select(func.set_config("nexus.company_id", str(COMPANY), True))
                )
                root_work = await session.get(
                    ExecutionWork, (COMPANY, ready.admission.procedure.binding.task_id)
                )
                planner_work = await session.get(ExecutionWork, (COMPANY, planner.task_id))
                builder = await session.get(ExecutionWork, (COMPANY, engineering.task_id))
                assert root_work and planner_work and builder
                assert (
                    root_work.model_requests_used,
                    root_work.tool_attempts_used,
                    root_work.plan_revisions_used,
                ) == (0, 0, 1)
                assert (root_work.model_requests_delegated, root_work.tool_attempts_delegated) == (
                    1,
                    5,
                )
                assert planner_work.model_requests_used == 1 and builder.tool_attempts_used == 0
                assert all(
                    value.worker_id is None and value.lease_until is None
                    for value in (root_work, planner_work, builder)
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
                model_hold = next(hold for hold in holds if hold.action_id == action.action_id)
                assert model_hold.state == "reconciled" and model_hold.actual_usd is not None
                assert model_hold.amount_usd == prepared.quote.amount_usd
                assert all(hold.amount_usd == 0 for hold in holds if hold is not model_hold)
                budget = await session.get(WorkBudget, (COMPANY, planner.task_id))
                day = await session.scalar(select(DailyBudget))
                assert budget and day and budget.spent_usd == day.spent_usd == model_hold.actual_usd
                assert budget.held_usd == day.held_usd == 0
    finally:
        error = sys.exc_info()[0]
        report = {
            "database": DATABASE,
            "started_utc": started.isoformat(),
            "finished_utc": datetime.now(UTC).isoformat(),
            "source_document_sha256": DOCUMENT_SHA256,
            "source_document_commit": DOCUMENT_COMMIT,
            "command": command.model_dump(mode="json") if command else None,
            "outcomes": [value.model_dump(mode="json") for value in outcomes],
            "mock_post_sha256s": resolver.posts,
            "first_error_type": error.__name__ if error else None,
            "revised_plan_sha256": revised.sha256 if revised else None,
            "limitations": [
                "synthetic eligibility, not genuine model quality",
                "SDK MockTransport only",
                "in-process DBOS, no restart proof",
                "builder gates denied, no actual native builder/patch/business cycle",
            ],
        }
        report_path = root / "runtime-evidence.json"
        with report_path.open("x") as stream:
            json.dump(report, stream, sort_keys=True, indent=2)
            stream.write("\n")
        report_path.chmod(0o600)
        while services.pending_owners() and any(
            clock_us() < op.end for op in services._operations.values()
        ):
            await asyncio.sleep(0.05)
        assert not services.pending_owners(), (
            "Actual pending resources retained; no normal disposal"
        )
        assert not ready.blobs.pending_owners() and not prepared_store.blobs.pending_owners()
        if dbos_attempted:
            await asyncio.to_thread(DBOS.destroy, workflow_completion_timeout_sec=1)

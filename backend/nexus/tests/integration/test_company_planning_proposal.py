"""Restricted real PostgreSQL/Brain/governed SDK-mock/proposal flow, never live model quality.

One coherent retained DB and its exact native conservation/negative sequence stay
together under the explanatory >400-line integration exception. No raw row seeds,
provider calls, owner-browser acceptance or production planner activation are used.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import httpx2
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from nexus.builder.contained_query import clock_us
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.context import ContextLimits, ContextSelection
from nexus.company.brain.context_store import PersistentContextAssembler
from nexus.company.brain.retrieval import SearchRequest
from nexus.company.brain.scope_support import brain_transaction
from nexus.company.contracts.actions import ActionProposal
from nexus.company.directory_models import RegisteredWork
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.owner_view_sources import OwnerViewSources
from nexus.company.management.plan_models import (
    ManagementPlanRevision,
    ManagementProcedure,
    ManagementRevisionEvent,
)
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.planning_consumer import RegisteredPlanningConsumer
from nexus.company.management.planning_content import (
    PlanningBinding,
    PlanningContent,
    PlanningTask,
    planning_annotation,
    planning_schema,
)
from nexus.company.management.planning_intent import prepare_planning_request
from nexus.company.management.planning_proposal_bridge import (
    PlanningProposalBridge,
    PlanningProposalTemplate,
    PlanningTaskSlot,
    map_content,
)
from nexus.company.management.planning_source_reader import PlanningSourceReader
from nexus.core.llm.company_adapter_contracts import CompanyModelRequest, ServerEndpoint
from nexus.core.llm.company_pricing import TokenBounds, quote_cost
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt, ExecutionWork
from nexus.execution.runtime_support import registration_digest
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import CostHold, DailyBudget, WorkBudget
from nexus.harness.model_authorizer_contracts import model_action_parameters
from nexus.harness.model_evidence import FileModelEvidenceStore
from nexus.harness.model_input_estimator import FullContextInputEstimator
from nexus.tests.integration.planning_proposal_fixture import Authority, key, recipe, setup
from nexus.tests.integration.test_company_directory import (
    ACTOR,
    COMPANY,
    OWNER,
    WORKSPACE,
    control,
    migrate,
)
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.unit.test_company_provider_conformance import KEY, EndpointResolver, response

DATABASE = "nexus_company_test_planning_proposal_v1"
SOCKET = "/tmp/nexus-release-tests-2026-10-13/socket"


@pytest.fixture
async def factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    configured = os.environ.get("COMPANY_TEST_DATABASE_URL")
    if configured is None:
        pytest.skip("Explicit isolated planning proposal database is not configured")
    url = make_url(configured)
    assert (url.drivername, url.username, url.password, url.host, url.port, url.database) == (
        "postgresql+asyncpg",
        "santapong",
        None,
        None,
        None,
        DATABASE,
    )
    assert dict(url.query) == {"host": SOCKET, "port": "55438"}
    admin = create_async_engine(url, poolclass=NullPool)
    app = create_async_engine(url.set(username="nexus_company_app"), poolclass=NullPool)
    try:
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "upgrade")
            assert (
                await connection.scalar(text("SELECT version_num FROM company_alembic_version"))
                == "company_016"
            )
            row = (
                await connection.execute(
                    text(
                        "SELECT count(*),bool_and(c.relrowsecurity AND c.relforcerowsecurity) "
                        "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                        "WHERE n.nspname='public' AND c.relkind='r' AND c.relname LIKE 'company_%' "
                        "AND c.relname <> 'company_alembic_version'"
                    )
                )
            ).one()
            assert tuple(row) == (74, True)
        async with app.connect() as connection:
            assert await connection.scalar(text("SELECT current_user")) == "nexus_company_app"
            assert not await connection.scalar(
                text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user")
            )
            for setting in ("fsync", "synchronous_commit", "full_page_writes"):
                assert await connection.scalar(text(f"SHOW {setting}")) == "on"
        yield async_sessionmaker(app, expire_on_commit=False)
    finally:
        await app.dispose()
        await admin.dispose()  # Preserve all rows/files on either outcome.


async def test_actual_governed_candidate_promotes_once_under_same_permanent_goal_root(
    factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    started = datetime.now(UTC)
    ready = await setup(factory, tmp_path)
    planner = ready.planner
    signed = identity(ACTOR)
    brain = BrainReadScope(
        company_id=COMPANY,
        workspace_id=WORKSPACE,
        principal_id=ACTOR,
        operation_id=key("assemble"),
        trace_id=key("context-audit"),
        task_id=planner.task_id,
        task_trace_id=planner.trace_id,
        actor_id=ACTOR,
    )
    assembler = PersistentContextAssembler(
        factory,
        ready.retriever,
        Authority(),
        limits=ContextLimits(policy_version="planning-context-v1"),
    )
    context = await assembler.assemble(
        brain,
        signed,
        ContextSelection(
            company_id=COMPANY, search=SearchRequest(company_id=COMPANY, query="Nexus")
        ),
    )
    assert context.manifest.inclusions
    actual = await ready.retriever.materialize(
        brain, signed, tuple(row.handle for row in context.manifest.inclusions)
    )
    assert actual and "Nexus" in actual[0].text
    frozen = PlanningBinding(
        goal=ready.goal,
        plan_id=ready.base.plan_id,
        expected_plan_revision_id=ready.base.plan_revision_id,
        context_manifest_sha256=canonical_sha256(context.manifest),
    )
    call = CompanyModelRequest(
        company_id=COMPANY,
        task_id=planner.task_id,
        trace_id=planner.trace_id,
        actor_id=ACTOR,
        action_id=key("model-action"),
        attempt_id=key("model-action"),
        request_id=key("model-request"),
        registry_id="nexus-planner",
        registry_revision=ready.services.catalog.models.revision,
        price_version="fixture-prices",
        input_text=context.input_text,
        system_text=context.system_text,
        output_schema=planning_schema(frozen, manifest=context.manifest),
        data_classification="internal",
        bounds=TokenBounds(
            input_tokens=400_000, max_output_tokens=512, input_bound_kind="model_input_ceiling_v1"
        ),
    )
    prepared = prepare_planning_request(call, context, frozen, scope=brain, input_recipe=recipe())
    estimator = FullContextInputEstimator(ready.services.catalog.models, recipe())
    estimate = estimator.estimate(call, ready.services.catalog.models, recipe())
    assert estimate.whole_request and estimate.whole_request.tokens == 400_000
    async with brain_transaction(factory, brain, signed) as (session, current, now):
        resources = await assembler.revalidate_context(
            session, current, brain, signed, context.manifest, now
        )
    model = ready.services.catalog.models.models[0]
    quote = quote_cost(model.price, call.bounds, now=datetime.now(UTC))
    action = ActionProposal(
        company_id=COMPANY,
        task_id=planner.task_id,
        trace_id=planner.trace_id,
        actor_id=ACTOR,
        action_id=call.action_id,
        revision=1,
        tool="model.request.v1",
        tool_version="v1",
        resource=f"model:{call.registry_id}",
        parameters=model_action_parameters(call, recipe()),
        preconditions=resources,
        policy_version="fixture-policy",
        price_version="fixture-prices",
        estimated_cost_usd=quote.amount_usd,
    )
    journal = CompanyJournal(factory)
    scope = LedgerScope(
        company_id=COMPANY, principal_id=ACTOR, task_id=planner.task_id, trace_id=planner.trace_id
    )
    submitted = await journal.submit(action, scope)
    await journal.approve_registered(
        scope.model_copy(update={"principal_id": OWNER}),
        call.action_id,
        submitted.proposal_hash,
        datetime.now(UTC),
        identity=identity(OWNER),
    )
    await journal.authorize_registered(
        scope, call.action_id, datetime.now(UTC), resources, identity=signed
    )
    execution = ready.services.execution_store(factory)
    lease = await execution.claim(scope, signed, key("worker"), ttl_seconds=60)
    emitted = PlanningContent(
        tasks=(
            PlanningTask(
                key="delivery",
                title="Review the Nexus owner planning proposal",
                description="Use materialized evidence to prepare a reviewable Nexus change.",
                acceptance=("Retain cited evidence and obtain owner approval",),
                depends_on=(),
                evidence_ids=(context.manifest.inclusions[0].handle.evidence_id,),
            ),
        ),
        questions=("Which Nexus implementation scope should the owner approve?",),
    )
    posts = []

    def wire(request: httpx2.Request) -> httpx2.Response:
        assert request.method == "POST"
        posts.append(hashlib.sha256(request.content).hexdigest())
        payload = response("openai")
        payload["model"] = model.model_id
        payload["output"] = [
            {
                "id": "planning-message",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {"type": "output_text", "text": emitted.model_dump_json(), "annotations": []}
                ],
            }
        ]
        return httpx2.Response(200, json=payload)

    endpoint = ServerEndpoint(
        endpoint_id=model.endpoint_id,
        provider=model.provider,
        api_family=model.api_family,
        base_url="https://api.openai.com/v1",
        api_key=SecretStr(KEY),
        timeout_seconds=2,
        transport=httpx2.MockTransport(wire),
    )
    models = FileModelEvidenceStore(tmp_path / "model-evidence")
    consumer = RegisteredPlanningConsumer(
        factory,
        ready.services.catalog.models,
        EndpointResolver(endpoint),
        ready.services,
        assembler,
        models,
        estimator,
        recipe(),
        lease,
        signed,
        resources=resources,
        allowed_classification="internal",
    )
    attempt = await consumer.request_once(prepared, now=datetime.now(UTC))
    assert attempt.candidate is not None and attempt.denial is None
    assert attempt.governed.recorded is not None
    assert not attempt.company_completed and not attempt.stop_required and len(posts) == 1
    assert (
        attempt.governed.release_status == "released"
        and not consumer.evidence_reads[-1].cancelled()
    )
    released = await execution.get(scope, signed)
    assert (
        released.worker_id is None
        and released.expires_at is None
        and released.counters.model_requests == 1
    )
    original_registration = registration_digest(released.registration)
    stored = await models.load(attempt.candidate.artifact)
    assert stored.request.output_schema is not None
    binding, manifest = planning_annotation(stored.request.output_schema)
    assert (
        binding == frozen
        and manifest == context.manifest
        and stored.input_estimate.whole_request == estimate.whole_request
    )
    policy = PlanningProposalTemplate(
        base_plan=ready.base,
        revision="nexus-model-only-v1",
        slots=(
            PlanningTaskSlot(
                key="delivery",
                allocation=ready.delivery,
                department="planning",
                required_dependencies=(planner.task_id,),
            ),
        ),
    )
    owner_scope = control()
    # Fresh concrete reader/store: no old execute lease or EffectStore.get is supplied.
    reader = PlanningSourceReader(
        factory,
        FileModelEvidenceStore(tmp_path / "model-evidence"),
        ready.retriever,
        OwnerViewSources(ready.services.artifacts, ready.services.freshness),
        policy,
    )
    plans = ManagementPlanStore(
        factory,
        ready.services.catalog,
        source_freshness=ready.services.freshness,
        planning_reader=reader,
    )
    bridge = PlanningProposalBridge(plans, reader)
    end = clock_us() + 30_000_000
    source = await reader.load(
        owner_scope,
        identity(OWNER),
        call.action_id,
        expected_goal=ready.goal,
        expected_current_revision_id=ready.base.plan_revision_id,
        end_us=end,
    )
    assert source.content == emitted and source.origin.receipt_id == attempt.candidate.receipt_id
    mapped = map_content(source.content, source.origin, policy)
    with pytest.raises(ValueError):
        await reader.load(
            owner_scope,
            identity(OWNER),
            call.action_id,
            expected_goal=ready.goal,
            expected_current_revision_id=key("foreign-cas"),
            end_us=end,
        )
    for change in ({"artifact_sha256": "f" * 64}, {"action_id": key("foreign-action")}):
        forged = mapped.model_copy(
            update={"planning_origin": source.origin.model_copy(update=change)}
        )
        with pytest.raises(ValueError):
            await plans.propose(
                owner_scope,
                identity(OWNER),
                forged,
                expected_current_revision_id=ready.base.plan_revision_id,
                end_us=end,
            )
    proposal = await bridge.propose(
        owner_scope,
        identity(OWNER),
        call.action_id,
        expected_goal=ready.goal,
        expected_current_revision_id=ready.base.plan_revision_id,
        end_us=end,
    )
    approved = await plans.approve_and_register(
        owner_scope,
        identity(OWNER),
        proposal.plan_revision_id,
        proposal.sha256,
        expected_current_revision_id=ready.base.plan_revision_id,
        end_us=end,
    )
    assert approved == proposal and approved.payload.procedure == ready.base.payload.procedure
    assert approved.payload.children[0] == ready.base.payload.children[0]
    assert approved.payload.plan.items[1].depends_on == (planner.task_id,)
    assert (
        await plans.approve_and_register(
            owner_scope,
            identity(OWNER),
            proposal.plan_revision_id,
            proposal.sha256,
            expected_current_revision_id=proposal.plan_revision_id,
            end_us=end,
        )
        == approved
    )
    assert (
        await plans.propose(
            owner_scope,
            identity(OWNER),
            proposal.payload,
            expected_current_revision_id=ready.base.plan_revision_id,
            end_us=end,
        )
        == approved
    )
    with pytest.raises(ValueError):
        await reader.load(
            owner_scope,
            identity(OWNER),
            call.action_id,
            expected_goal=ready.goal,
            expected_current_revision_id=ready.base.plan_revision_id,
            end_us=end,
        )
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        root = await session.get(
            ExecutionWork, (COMPANY, ready.base.payload.procedure.binding.task_id)
        )
        planner_row = await session.get(ExecutionWork, (COMPANY, planner.task_id))
        hold = await session.get(CostHold, call.action_id)
        assert root and planner_row and hold
        assert root.model_requests_delegated == 2 and root.plan_revisions_used == 1
        assert root.model_requests_used == root.tool_attempts_used == 0
        assert planner_row.model_requests_used == 1 and planner_row.tool_attempts_used == 0
        assert (
            planner_row.lease_until is None
            and planner_row.registration_hash == original_registration
        )
        assert (
            hold.state == "reconciled" and hold.actual_usd == attempt.governed.recorded.actual_usd
        )
        counts = {
            model.__tablename__: await session.scalar(select(func.count()).select_from(model))
            for model in (
                RegisteredWork,
                ExecutionWork,
                EffectIntent,
                ExecutionAttempt,
                ManagementProcedure,
                ManagementRevisionEvent,
                ManagementPlanRevision,
            )
        }
        assert tuple(counts.values()) == (3, 3, 1, 1, 1, 1, 2)
        budgets = (await session.scalars(select(WorkBudget))).all()
        daily = await session.scalar(select(DailyBudget))
        assert daily and daily.held_usd == 0 and daily.spent_usd == hold.actual_usd
        assert sum(row.spent_usd for row in budgets) == hold.actual_usd
    # Protected bytes remain necessary even after approval; no retained process-local proof.
    path = Path(attempt.candidate.artifact.reference)
    original = path.read_bytes()
    path.chmod(0o600)
    path.write_bytes(b"{}")
    with pytest.raises(ValueError):
        await plans.approve_and_register(
            owner_scope,
            identity(OWNER),
            proposal.plan_revision_id,
            proposal.sha256,
            expected_current_revision_id=proposal.plan_revision_id,
            end_us=end,
        )
    path.write_bytes(original)
    path.chmod(0o400)
    assert (
        await plans.approve_and_register(
            owner_scope,
            identity(OWNER),
            proposal.plan_revision_id,
            proposal.sha256,
            expected_current_revision_id=proposal.plan_revision_id,
            end_us=end,
        )
        == approved
    )
    summary = {
        "started": started.isoformat(),
        "finished": datetime.now(UTC).isoformat(),
        "database": DATABASE,
        "company": str(COMPANY),
        "goal": str(ready.goal.goal_id),
        "model_action": str(call.action_id),
        "receipt": str(source.origin.receipt_id),
        "base_plan": str(ready.base.plan_revision_id),
        "formal_plan": str(proposal.plan_revision_id),
        "formal_sha256": proposal.sha256,
        "protected_model_sha256": source.origin.artifact_sha256,
        "request_sha256": source.origin.request_sha256,
        "context_manifest_sha256": source.origin.context_manifest_sha256,
        "counts": counts,
        "mock_posts": len(posts),
        "provider_calls": 0,
        "actual_usd": str(hold.actual_usd),
        "root_revision_used": 1,
        "company_completed": False,
        "scope": "restricted PG +SDK MockTransport; no live quality/HTTP/browser acceptance",
    }
    report = tmp_path / "planning-proposal-summary.json"
    report.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    report.chmod(0o600)

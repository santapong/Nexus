"""Actual public native reporting fixture; no raw plan/receipt/acceptance insert or owner echo."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.retrieval import RetrievalLimits
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.brain.scope_support import brain_transaction
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.acceptance import VerificationSpec
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.acceptance_support import acceptance_scope, resolve_target
from nexus.company.management.check_contracts import (
    ReportCheckInput,
    SourceQuoteClaim,
    StructuredInternalReport,
)
from nexus.company.management.operating_report_contracts import SavedOperatingReport
from nexus.company.management.operating_report_store import OperatingReportStore
from nexus.company.management.plans import PlanPayload, RunBinding
from nexus.company.management.report_artifact_reader import ReportArtifactReader
from nexus.company.management.report_inputs import PersistentReportInputLoader
from nexus.execution.effect_store import EffectStore
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_store import ExecutionStore
from nexus.execution.runtime_support import db_now, runtime_transaction
from nexus.harness.canonical import action_hash
from nexus.tests.integration.management_acceptance_fixture import add_ordinary_dependency, ledger
from nexus.tests.integration.management_acceptance_source_fixture import Policies, protected_text
from nexus.tests.integration.operating_report_fixture_sources import (
    current_input_source,
    register_immutable_input,
)
from nexus.tests.integration.test_company_directory import OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.management_plan_support import authorized_action, configured_plan


@dataclass(frozen=True)
class ReportScenario:
    store: OperatingReportStore
    reader: PersistentBrainRetriever
    artifacts: BoundedArtifactReader
    freshness: RegisteredSourceFreshness
    execution: ExecutionStore
    effects: EffectStore
    payload: PlanPayload
    saved: SavedOperatingReport
    report: StructuredInternalReport
    target: VerificationSpec
    verifier_lease: ExecutionLease
    inputs: PersistentReportInputLoader
    selected_action_id: UUID | None
    policies: Policies


async def configured_report(
    factory: async_sessionmaker[AsyncSession],
    root: Path,
    *,
    selected_bill: Decimal | None = Decimal("0.015000"),
    issue_selected: bool = False,
    source_no_ttl: bool = False,
    release_selected: bool = False,
    after_selected: Callable[[Policies, BoundedArtifactReader], Awaitable[None]] | None = None,
    before_snapshot: Callable[[], Awaitable[None]] | None = None,
) -> ReportScenario:
    # Complete public native fixture keeps the author/verifier/output identities together.
    plans, data = await configured_plan(factory, root)
    data = add_ordinary_dependency(data)
    third = data.plan.items[2].model_copy(update={"depends_on": ()})
    data = PlanPayload.model_validate_json(
        data.model_copy(
            update={"plan": data.plan.model_copy(update={"items": (*data.plan.items[:2], third)})}
        ).model_dump_json(by_alias=True)
    )
    proposed = await plans.propose(
        control(), identity(OWNER), data, expected_current_revision_id=None
    )
    await plans.approve_and_register(
        control(),
        identity(OWNER),
        proposed.plan_revision_id,
        proposed.sha256,
        expected_current_revision_id=proposed.plan_revision_id,
    )
    blobs = ProtectedBlobStore(root, storage_symbol="fixture.blobs.v1")
    reader = PersistentBrainRetriever(factory, blobs, limits=RetrievalLimits())
    artifacts = BoundedArtifactReader(factory, blobs)
    policies = Policies()
    if source_no_ttl:
        await register_immutable_input(factory, root, policies)
    freshness = RegisteredSourceFreshness(factory, policies)
    execution = ExecutionStore(
        factory,
        management_catalog=plans.catalog,
        management_artifacts=artifacts,
        management_freshness=freshness,
    )
    effects = EffectStore(
        factory,
        management_catalog=plans.catalog,
        management_artifacts=artifacts,
        management_freshness=freshness,
    )
    selected_id = (
        await issue_work(
            factory,
            execution,
            effects,
            data.children[2].binding,
            selected_bill,
            release=release_selected,
        )
        if issue_selected
        else None
    )
    if after_selected is not None:
        await after_selected(policies, artifacts)
    if before_snapshot is not None:
        await before_snapshot()
    store = OperatingReportStore(factory, plans.catalog, artifacts, freshness)
    observed = datetime.now(UTC)
    saved = await store.save_snapshot(
        control(),
        identity(OWNER),
        proposed.plan_revision_id,
        data.children[0].binding.task_id,
        (data.children[2].binding.task_id,),
        period_start=observed - timedelta(days=1),
        period_end=observed,
    )
    assert await prepare_saved_author(factory, store, data, saved) == saved
    source, handles = await current_input_source(factory, reader)
    record = handles[0].record
    report = StructuredInternalReport(
        schema_version="nexus.company.internal-report.v1",
        company_id=saved.company_id,
        operating=saved.projection,
        claims=(
            SourceQuoteClaim(
                kind="source_quote",
                evidence_id=record.evidence_id,
                source_revision_id=record.source.source_revision_id,
                artifact_revision_id=record.artifact.artifact_revision_id,
                span_sha256=record.span_sha256,
                quote=source.text,
                source_event=record.source_event,
                source_state="current",
                freshness="fresh",
            ),
        ),
    )
    output = await protected_text(factory, blobs, policies, report.model_dump_json(), 200)
    author, verifier = data.children[0].binding, data.children[1].binding
    action = await issue_work(factory, execution, effects, author, Decimal("0.025000"), output)
    lease = await execution.claim(ledger(verifier), identity(verifier.actor_id), uuid4())
    async with runtime_transaction(factory, ledger(verifier), identity(verifier.actor_id)) as (
        session,
        current,
        _,
    ):
        target = await resolve_target(session, current, lease, action, await db_now(session))
    return ReportScenario(
        store,
        reader,
        artifacts,
        freshness,
        execution,
        effects,
        data,
        saved,
        report,
        target,
        lease,
        PersistentReportInputLoader(
            factory, ReportArtifactReader(reader, artifacts), store, source_policies=policies
        ),
        selected_id,
        policies,
    )


async def issue_work(
    factory: async_sessionmaker[AsyncSession],
    execution: ExecutionStore,
    effects: EffectStore,
    binding: RunBinding,
    bill: Decimal | None,
    output: ArtifactRevisionRef | None = None,
    *,
    release: bool = False,
) -> UUID:
    action = await authorized_action(factory, binding)
    lease = await execution.claim(ledger(binding), identity(binding.actor_id), uuid4())
    await effects.begin(lease, identity(binding.actor_id), action.action_id)
    receipt = ActionReceipt(
        company_id=binding.company_id,
        receipt_id=uuid4(),
        action_id=action.action_id,
        task_id=binding.task_id,
        trace_id=binding.trace_id,
        proposal_hash=action_hash(action),
        outcome="succeeded",
        recorded_at=datetime.now(UTC),
        artifacts=()
        if output is None
        else (
            ArtifactRef(
                company_id=output.company_id,
                artifact_id=output.artifact_id,
                reference="protected:actual-native-report",
                sha256=output.sha256,
                revision=output.revision,
            ),
        ),
    )
    await effects.record_receipt(lease, identity(binding.actor_id), receipt, actual_usd=bill)
    if release:
        await execution.release(lease, identity(binding.actor_id))
    return action.action_id


async def loaded_report(scenario: ReportScenario) -> ReportCheckInput:
    verifier = scenario.payload.children[1].binding
    return await scenario.inputs.load(
        acceptance_scope(scenario.verifier_lease, scenario.target.action_id),
        identity(verifier.actor_id),
        scenario.target,
    )


async def prepare_saved_author(
    factory: async_sessionmaker[AsyncSession],
    store: OperatingReportStore,
    payload: PlanPayload,
    saved: SavedOperatingReport,
) -> SavedOperatingReport:
    author = saved.selection.author
    scope = BrainReadScope(
        company_id=author.company_id,
        workspace_id=author.workspace_id,
        principal_id=author.actor_id,
        operation_id=uuid4(),
        trace_id=uuid4(),
        task_id=author.task_id,
        task_trace_id=author.trace_id,
        actor_id=author.actor_id,
    )
    async with brain_transaction(factory, scope, identity(author.actor_id)) as (
        session,
        current,
        _,
    ):
        prepared = await store.prepare_author_output(
            session, current, scope, identity(author.actor_id), saved.report_id
        )
        exact, inputs = await store.prepare_author_inputs(
            session, current, scope, identity(author.actor_id), saved.report_id
        )
        assert prepared == exact and 0 < len(inputs) <= 33
        assert len({row.artifact_revision_id for row in inputs}) == len(inputs)
        return exact

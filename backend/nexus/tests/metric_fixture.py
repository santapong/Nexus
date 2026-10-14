"""Synthetic metric conformance uses actual public native producers/publishers, never pass SQL."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.acceptance import WorkAcceptance
from nexus.company.management.acceptance_evidence import ProtectedReportEvidenceResolver
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.acceptance_store import WorkAcceptanceStore
from nexus.company.management.check_contracts import ReportCheckResult
from nexus.company.management.generated_artifact_contracts import (
    GeneratedArtifactActionParameters,
    GeneratedArtifactPayload,
    GeneratedArtifactRule,
)
from nexus.company.management.generated_artifact_store import GeneratedArtifactPublisher
from nexus.company.management.goals import GoalDefinition
from nexus.company.management.governance_models import ManagementGoalRevision
from nexus.company.management.metric_contracts import NATIVE_REPORT_COUNT, MetricObservationRequest
from nexus.company.management.metric_store import MetricStore
from nexus.company.management.native_report_producer import NativeReportProducer
from nexus.company.management.native_report_validator import NativeReportValidator
from nexus.company.management.operating_report_store import OperatingReportStore
from nexus.company.management.plans import PlanPayload, RunBinding
from nexus.company.management.report_artifact_reader import ReportArtifactReader
from nexus.company.management.report_inputs import PersistentReportInputLoader
from nexus.company.management.revision_store import plan_reference
from nexus.company.management.transactions import management_owner_transaction
from nexus.execution.effect_store import EffectStore
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_store import ExecutionStore
from nexus.harness.canonical import action_hash
from nexus.harness.journal import CompanyJournal
from nexus.tests.generated_artifact_fixture import ledger
from nexus.tests.integration.operating_report_fixture_sources import current_input_source
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.metric_plan_fixture import declared_metric_plan


@dataclass(frozen=True)
class MetricScenario:
    store: MetricStore
    request: MetricObservationRequest
    payload: PlanPayload
    publisher: GeneratedArtifactPublisher
    producer: NativeReportProducer
    execution: ExecutionStore
    effects: EffectStore
    retriever: PersistentBrainRetriever


async def configured_metric(
    factory: async_sessionmaker[AsyncSession],
    root: Path,
    *,
    recipe: str | None = NATIVE_REPORT_COUNT,
    unit: str = "count",
) -> MetricScenario:
    plans, payload, rules, policies, retriever, blobs, approved = await declared_metric_plan(
        factory, root, recipe=recipe, unit=unit
    )
    artifacts = BoundedArtifactReader(factory, blobs)
    freshness = RegisteredSourceFreshness(factory, policies)
    reports = OperatingReportStore(factory, plans.catalog, artifacts, freshness)
    inputs = PersistentReportInputLoader(
        factory, ReportArtifactReader(retriever, artifacts), reports, source_policies=policies
    )
    producer = NativeReportProducer(factory, reports, inputs)
    publisher = GeneratedArtifactPublisher(
        factory,
        blobs,
        plans.catalog,
        artifacts,
        policies,
        NativeReportValidator(producer),
        rules=rules,
    )
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
    request = MetricObservationRequest(
        company_id=COMPANY,
        observation_id=uuid4(),
        goal=payload.goal,
        plan=plan_reference(approved),
        metric_id=approved.payload.goal.goal_id.hex,
        task_ids=(payload.children[0].binding.task_id,),
    )
    # Native declaration supplies the actual metric name, never a fixture count.
    async with management_owner_transaction(factory, control(), identity(OWNER)) as (session, _, _):
        row = await session.get(ManagementGoalRevision, (COMPANY, payload.goal.revision_id))
        assert row is not None
        metric = GoalDefinition.model_validate_json(row.payload_json).metrics[0]
    request = request.model_copy(update={"metric_id": metric.metric_id})
    return MetricScenario(
        MetricStore(factory, plans.catalog, artifacts, freshness),
        request,
        payload,
        publisher,
        producer,
        execution,
        effects,
        retriever,
    )


def brain_scope(bound: RunBinding) -> BrainReadScope:
    return BrainReadScope(
        company_id=bound.company_id,
        workspace_id=bound.workspace_id,
        principal_id=bound.actor_id,
        operation_id=uuid4(),
        trace_id=uuid4(),
        task_id=bound.task_id,
        task_trace_id=bound.trace_id,
        actor_id=bound.actor_id,
    )


async def prepared_author(
    factory: async_sessionmaker[AsyncSession],
    scenario: MetricScenario,
) -> tuple[GeneratedArtifactPayload, GeneratedArtifactActionParameters]:
    observed = datetime.now(UTC)
    author = scenario.payload.children[0].binding
    saved = await scenario.producer.reports.save_snapshot(
        control(),
        identity(OWNER),
        scenario.request.plan.plan_revision_id,
        author.task_id,
        (),
        period_start=observed - timedelta(days=1),
        period_end=observed,
    )
    _, handles = await current_input_source(factory, scenario.retriever)
    evidence = tuple(row.evidence_id for row in handles)
    prepared = await scenario.producer.prepare_report(
        brain_scope(author), identity(author.actor_id), saved.report_id, evidence
    )
    parameters = GeneratedArtifactActionParameters(
        recipe_version=prepared.recipe_version,
        output_sha256=prepared.output_sha256,
        input_snapshot_sha256=prepared.input_snapshot_sha256,
        report_id=saved.report_id,
        evidence_ids=evidence,
    )
    return prepared, parameters


async def issue_native(
    factory: async_sessionmaker[AsyncSession],
    scenario: MetricScenario,
    bound: RunBinding,
    prepared: GeneratedArtifactPayload,
    parameters: GeneratedArtifactActionParameters,
    rule: GeneratedArtifactRule,
) -> tuple[ActionProposal, ExecutionLease, ArtifactRevisionRef]:
    action = ActionProposal(
        company_id=COMPANY,
        action_id=uuid4(),
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        actor_id=bound.actor_id,
        revision=1,
        tool=rule.tool,
        tool_version="v1",
        resource=rule.resource_symbol,
        parameters=parameters.model_dump(mode="json", exclude_none=True),
        policy_version="fixture-policy",
        price_version="fixture-prices",
        estimated_cost_usd=Decimal(".03"),
    )
    journal = CompanyJournal(factory)
    await journal.submit(action, ledger(bound))
    await journal.approve_registered(
        ledger(bound).model_copy(update={"principal_id": OWNER}),
        action.action_id,
        action_hash(action),
        datetime.now(UTC),
        identity=identity(OWNER),
    )
    await journal.authorize_registered(
        ledger(bound), action.action_id, datetime.now(UTC), (), identity=identity(bound.actor_id)
    )
    lease = await scenario.execution.claim(ledger(bound), identity(bound.actor_id), uuid4())
    await scenario.effects.begin(lease, identity(bound.actor_id), action.action_id)
    output = await scenario.publisher.publish(
        lease, identity(bound.actor_id), action.action_id, prepared
    )
    receipt = ActionReceipt(
        company_id=COMPANY,
        receipt_id=uuid4(),
        action_id=action.action_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        proposal_hash=action_hash(action),
        outcome="succeeded",
        recorded_at=datetime.now(UTC),
        artifacts=(
            ArtifactRef(
                company_id=COMPANY,
                artifact_id=output.artifact_id,
                reference="protected:metric-conformance",
                revision=output.revision,
                sha256=output.sha256,
            ),
        ),
    )
    await scenario.effects.record_receipt(
        lease, identity(bound.actor_id), receipt, actual_usd=Decimal(0)
    )
    return action, lease, output


async def accept_report(
    factory: async_sessionmaker[AsyncSession],
    scenario: MetricScenario,
) -> WorkAcceptance:
    prepared, parameters = await prepared_author(factory, scenario)
    author = scenario.payload.children[0].binding
    action, author_lease, _ = await issue_native(
        factory,
        scenario,
        author,
        prepared,
        parameters,
        scenario.publisher.rules["company.report.write.v1"],
    )
    await scenario.execution.release(author_lease, identity(author.actor_id))
    verifier = scenario.payload.children[1].binding
    lease = await scenario.execution.claim(ledger(verifier), identity(verifier.actor_id), uuid4())
    prepared = await scenario.producer.prepare_check(
        lease, identity(verifier.actor_id), action.action_id
    )
    await scenario.execution.release(lease, identity(verifier.actor_id))
    result = ReportCheckResult.model_validate_json(prepared.raw_bytes)
    parameters = GeneratedArtifactActionParameters(
        recipe_version=prepared.recipe_version,
        output_sha256=prepared.output_sha256,
        input_snapshot_sha256=prepared.input_snapshot_sha256,
        author_action_id=action.action_id,
        verification_target_sha256=result.target_sha256,
    )
    _, verifier_lease, output = await issue_native(
        factory,
        scenario,
        verifier,
        prepared,
        parameters,
        scenario.publisher.rules["company.report.check.v1"],
    )
    resolver = ProtectedReportEvidenceResolver(
        scenario.publisher.artifacts, scenario.producer.inputs, scenario.publisher.freshness
    )
    accepted = await WorkAcceptanceStore(factory, resolver).publish_verified_result(
        verifier_lease,
        identity(verifier.actor_id),
        action_id=action.action_id,
        protected_result=output,
    )
    await scenario.execution.release(verifier_lease, identity(verifier.actor_id))
    assert accepted.verdict == "pass" and accepted.target.author == author
    return accepted

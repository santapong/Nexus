"""Source-derived actual pending/approved UAT native report proposals; no effect invocation."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.evidence_models import BrainEvidence
from nexus.company.brain.scope_support import brain_transaction
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.base import SourceTime
from nexus.company.management.generated_artifact_contracts import GeneratedArtifactActionParameters
from nexus.company.management.goals import DueIntent
from nexus.company.management.lifecycle import PlanRevision
from nexus.company.management.native_report_producer import NativeReportProducer
from nexus.company.management.operating_report_contracts import SavedOperatingReport
from nexus.company.management.operations import CommitmentDefinition
from nexus.company.management.plans import PlanPayload, RunBinding
from nexus.company.management.report_artifact_reader import ReportArtifactReader
from nexus.company.management.report_inputs import PersistentReportInputLoader
from nexus.company.management.revision_store import plan_reference
from nexus.company.pilot_catalog import REPORT_TARGET
from nexus.company.pilot_composition import PilotServices
from nexus.company.pilot_config import PilotConfig
from nexus.company.pilot_sources import pilot_sources
from nexus.harness.canonical import action_hash
from nexus.harness.journal_contracts import LedgerScope


def actor_scope(config: PilotConfig, author: RunBinding) -> BrainReadScope:
    return BrainReadScope(
        company_id=config.company_id,
        workspace_id=config.workspace_id,
        principal_id=author.actor_id,
        operation_id=uuid4(),
        trace_id=uuid4(),
        task_id=author.task_id,
        task_trace_id=author.trace_id,
        actor_id=author.actor_id,
    )


async def populate_proposals(
    factory: async_sessionmaker[AsyncSession],
    services: PilotServices,
    config: PilotConfig,
    revision: PlanRevision,
    payload: PlanPayload,
) -> None:
    saved = await saved_report(services, config, revision, payload)
    scope = actor_scope(config, payload.children[0].binding)
    actor = VerifiedIdentity(principal_id=scope.principal_id, workspace_id=scope.workspace_id)
    evidence = await source_evidence(factory, config, scope, actor)
    loader = PersistentReportInputLoader(
        factory,
        ReportArtifactReader(services.brain.retriever, services.artifacts),
        services.reports,
        source_policies=pilot_sources(config),
    )
    producer = NativeReportProducer(factory, services.reports, loader)
    prepared = await producer.prepare_report(scope, actor, saved.report_id, evidence)
    parameters = GeneratedArtifactActionParameters(
        recipe_version=prepared.recipe_version,
        output_sha256=prepared.output_sha256,
        input_snapshot_sha256=prepared.input_snapshot_sha256,
        report_id=saved.report_id,
        evidence_ids=evidence,
    )
    await submit_proposals(services, config, scope, actor, parameters)
    await publish_commitment(services, config, revision, payload)


async def saved_report(
    services: PilotServices, config: PilotConfig, revision: PlanRevision, payload: PlanPayload
) -> SavedOperatingReport:
    observed = datetime.now(UTC)
    return await services.reports.save_snapshot(
        config.control(),
        config.identity(),
        revision.plan_revision_id,
        payload.children[0].binding.task_id,
        (),
        period_start=observed - timedelta(days=1),
        period_end=observed,
    )


async def source_evidence(
    factory: async_sessionmaker[AsyncSession],
    config: PilotConfig,
    scope: BrainReadScope,
    actor: VerifiedIdentity,
) -> tuple[UUID, ...]:
    async with brain_transaction(factory, scope, actor) as (session, _, _):
        return tuple(
            (
                await session.scalars(
                    select(BrainEvidence.evidence_id)
                    .where(
                        BrainEvidence.company_id == config.company_id,
                        BrainEvidence.source_id == config.public_source_id,
                    )
                    .order_by(BrainEvidence.evidence_id)
                )
            ).all()
        )


async def submit_proposals(
    services: PilotServices,
    config: PilotConfig,
    scope: BrainReadScope,
    actor: VerifiedIdentity,
    parameters: GeneratedArtifactActionParameters,
) -> None:
    assert (
        scope.task_id is not None and scope.task_trace_id is not None and scope.actor_id is not None
    )
    for label, approve in (("approved", True), ("pending", False)):
        action = ActionProposal(
            company_id=config.company_id,
            action_id=uuid5(config.company_id, "uat-report-action:" + label),
            task_id=scope.task_id,
            trace_id=scope.task_trace_id,
            actor_id=scope.actor_id,
            revision=1,
            tool="company.report.write.v1",
            tool_version="v1",
            resource=REPORT_TARGET,
            parameters=parameters.model_dump(mode="json"),
            policy_version="uat-supervised-v1",
            price_version="uat-offline-v1",
            estimated_cost_usd=Decimal("0.020000"),
        )
        ledger = LedgerScope(
            company_id=config.company_id,
            principal_id=actor.principal_id,
            task_id=action.task_id,
            trace_id=action.trace_id,
        )
        await services.base.journal.submit(action, ledger)
        if approve:
            await services.base.journal.approve_registered(
                ledger.model_copy(update={"principal_id": config.owner_id}),
                action.action_id,
                action_hash(action),
                datetime.now(UTC),
                identity=config.identity(),
            )


async def publish_commitment(
    services: PilotServices, config: PilotConfig, revision: PlanRevision, payload: PlanPayload
) -> None:
    assert services.management.commitments is not None
    await services.management.commitments.publish(
        config.control(),
        config.identity(),
        CommitmentDefinition(
            company_id=config.company_id,
            commitment_id=uuid5(config.company_id, "uat-commitment"),
            goal=payload.goal,
            plan=plan_reference(revision),
            responsible_id=config.author_id,
            deliverable="Synthetic native UAT report; no customer commitment",
            due=DueIntent(
                source_time=SourceTime(
                    precision="unknown", value=None, basis="Disposable UAT has no business deadline"
                )
            ),
            work=(payload.children[0].binding, payload.children[1].binding),
        ),
        version="uat-commitment-v1",
        expected_revision_id=None,
    )

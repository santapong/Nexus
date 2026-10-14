"""Explicit one-shot local UAT report effect; no worker, provider or acceptance promotion."""

import json
from datetime import UTC, datetime
from uuid import uuid4, uuid5

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.generated_artifact_contracts import (
    GeneratedArtifactActionParameters,
    GeneratedArtifactPayload,
    GeneratedArtifactRule,
)
from nexus.company.management.generated_artifact_identity import require_action_payload
from nexus.company.management.generated_artifact_store import GeneratedArtifactPublisher
from nexus.company.management.native_report_producer import (
    REPORT_RENDER_RECIPE,
    NativeReportProducer,
)
from nexus.company.management.native_report_validator import NativeReportValidator
from nexus.company.management.report_artifact_reader import ReportArtifactReader
from nexus.company.management.report_inputs import PersistentReportInputLoader
from nexus.company.pilot_catalog import REPORT_TARGET
from nexus.company.pilot_composition import PilotServices
from nexus.company.pilot_config import PilotConfig
from nexus.company.pilot_plan import bound
from nexus.company.pilot_sources import pilot_sources
from nexus.execution.effect_store import EffectStore
from nexus.execution.runtime_store import ExecutionStore
from nexus.harness.canonical import action_hash
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.lifecycle import ActionState


def report_rule(config: PilotConfig) -> GeneratedArtifactRule:
    return GeneratedArtifactRule(
        company_id=config.company_id,
        tool="company.report.write.v1",
        resource_symbol=REPORT_TARGET,
        target=ResourceRef(company_id=config.company_id, resource_id=config.report_resource_id),
        source_policy="generated.report.v1",
        recipe_version=REPORT_RENDER_RECIPE,
    )


def native_producer(
    factory: async_sessionmaker[AsyncSession], services: PilotServices, config: PilotConfig
) -> NativeReportProducer:
    loader = PersistentReportInputLoader(
        factory,
        ReportArtifactReader(services.brain.retriever, services.artifacts),
        services.reports,
        source_policies=pilot_sources(config),
    )
    return NativeReportProducer(factory, services.reports, loader)


async def execute_report(
    factory: async_sessionmaker[AsyncSession], services: PilotServices, config: PilotConfig
) -> ActionReceipt:
    """Only the already approved exact report proposal can enter this bounded native effect."""
    from nexus.company.pilot_actions import actor_scope

    author = bound(config, "author", config.author_id)
    scope = LedgerScope(
        company_id=config.company_id,
        principal_id=author.actor_id,
        task_id=author.task_id,
        trace_id=author.trace_id,
    )
    actor = VerifiedIdentity(principal_id=author.actor_id, workspace_id=author.workspace_id)
    record = await services.base.journal.get_action(
        scope, uuid5(config.company_id, "uat-report-action:approved")
    )
    if record.state != ActionState.AWAITING_APPROVAL or record.approval is None:
        raise ValueError("UAT direct execution requires its unconsumed approved proposal")
    pins = GeneratedArtifactActionParameters.model_validate_json(
        json.dumps(record.proposal.parameters)
    )
    if pins.report_id is None:
        raise ValueError("UAT report selector is unavailable")
    producer = native_producer(factory, services, config)
    prepared = await producer.prepare_report(
        actor_scope(config, author), actor, pins.report_id, pins.evidence_ids
    )
    require_action_payload(record.proposal, report_rule(config), prepared)
    execution, effects, publisher = native_execution(factory, services, config, producer)
    return await issue_report(
        services, scope, actor, record.proposal, prepared, execution, effects, publisher
    )


def native_execution(
    factory: async_sessionmaker[AsyncSession],
    services: PilotServices,
    config: PilotConfig,
    producer: NativeReportProducer,
) -> tuple[ExecutionStore, EffectStore, GeneratedArtifactPublisher]:
    from nexus.company.pilot_catalog import pilot_catalog

    catalog = pilot_catalog(config)
    execution = ExecutionStore(
        factory,
        management_catalog=catalog,
        management_artifacts=services.artifacts,
        management_freshness=services.freshness,
    )
    effects = EffectStore(
        factory,
        management_catalog=catalog,
        management_artifacts=services.artifacts,
        management_freshness=services.freshness,
    )
    publisher = GeneratedArtifactPublisher(
        factory,
        ProtectedBlobStore(config.blob_root, storage_symbol="uat.local-blobs.v1"),
        catalog,
        services.artifacts,
        pilot_sources(config),
        NativeReportValidator(producer),
        rules=(report_rule(config),),
    )
    return execution, effects, publisher


async def issue_report(
    services: PilotServices,
    scope: LedgerScope,
    actor: VerifiedIdentity,
    action: ActionProposal,
    prepared: GeneratedArtifactPayload,
    execution: ExecutionStore,
    effects: EffectStore,
    publisher: GeneratedArtifactPublisher,
) -> ActionReceipt:
    await services.base.journal.authorize_registered(
        scope,
        action.action_id,
        datetime.now(UTC),
        (),
        identity=actor,
    )
    lease = await execution.claim(scope, actor, uuid4(), ttl_seconds=300)
    start = await effects.begin(lease, actor, action.action_id)
    if not start.permit_external_call:
        raise ValueError("UAT effect already has an issued intent; automatic reissue is denied")
    output = await publisher.publish(lease, actor, action.action_id, prepared)
    receipt = ActionReceipt(
        company_id=scope.company_id,
        receipt_id=uuid4(),
        action_id=action.action_id,
        task_id=scope.task_id,
        trace_id=scope.trace_id,
        proposal_hash=action_hash(action),
        outcome="succeeded",
        recorded_at=datetime.now(UTC),
        external_id="uat-local-generated-report",
        artifacts=(
            ArtifactRef(
                company_id=scope.company_id,
                artifact_id=output.artifact_id,
                reference="protected:uat-native-report",
                sha256=output.sha256,
                revision=output.revision,
            ),
        ),
    )
    await effects.record_receipt(lease, actor, receipt, actual_usd=None)
    await execution.release(lease, actor)
    return receipt

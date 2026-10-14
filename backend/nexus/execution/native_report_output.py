"""Known native publication/read receipts; pending preparation bytes cannot resolve an effect."""

import json
from decimal import Decimal
from uuid import uuid5

from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.generated_artifact_contracts import GeneratedArtifactActionParameters
from nexus.company.management.generated_artifact_identity import (
    generated_artifact_id,
    generated_derivation_id,
)
from nexus.company.management.generated_artifact_scope import generated_scope
from nexus.company.management.report_input_sources import protected_bytes
from nexus.execution.native_report_context import NativeReportContext
from nexus.execution.runtime_contracts import EffectRecord, ExecutionDeniedError
from nexus.execution.runtime_support import db_now, lease_scope, runtime_transaction
from nexus.harness.canonical import action_hash


async def native_receipt(
    context: NativeReportContext, reference: ArtifactRevisionRef
) -> ActionReceipt:
    """Describe actual published bytes with stable receipt identity and native database clock."""
    async with context.services.factory() as session:
        now = await db_now(session)
    command = context.command
    return ActionReceipt(
        company_id=command.company_id,
        receipt_id=uuid5(command.action_id, "native-report-receipt:v1"),
        action_id=command.action_id,
        task_id=command.task_id,
        trace_id=command.trace_id,
        proposal_hash=action_hash(context.action),
        outcome="succeeded",
        recorded_at=now,
        artifacts=(
            ArtifactRef(
                company_id=reference.company_id,
                artifact_id=reference.artifact_id,
                reference="protected:native-generated-artifact",
                sha256=reference.sha256,
                revision=reference.revision,
            ),
        ),
    )


async def recover_known_output(context: NativeReportContext) -> EffectRecord:
    """Only actual native metadata plus protected exact bytes may resolve an unknown receipt."""
    services, lease, signed, command = (
        context.services,
        context.lease,
        context.identity,
        context.command,
    )
    record = await services.effects.get(lease, signed, command.action_id)
    if record.receipt is not None:
        return record
    reference = await issued_reference(context)
    if reference is None:
        return record
    scope = generated_scope(lease, command.action_id)
    raw = await protected_bytes(
        services.producer.inputs.reader, scope, signed, reference, max_bytes=262144
    )
    if len(raw) != reference.byte_length:
        raise ExecutionDeniedError("Native issued bytes are incomplete")
    receipt = await native_receipt(context, reference)
    return await services.effects.reconcile(lease, signed, receipt, actual_usd=Decimal(0))


async def issued_reference(context: NativeReportContext) -> ArtifactRevisionRef | None:
    """A stable artifact/derivation from the actual action is required; no blob-only inference."""
    lease, command = context.lease, context.command
    pins = GeneratedArtifactActionParameters.model_validate_json(
        json.dumps(context.action.parameters)
    )
    key = generated_artifact_id(command.company_id, command.action_id)
    async with runtime_transaction(
        context.services.factory,
        lease_scope(lease),
        context.identity,
        allow_paused=True,
        allow_inactive=True,
    ) as (session, _, _):
        row = await session.get(
            BrainArtifactRevision, (command.company_id, uuid5(key, "revision:v1"))
        )
        if row is None:
            return None
        if (
            row.artifact_id != key
            or row.revision != "generated-v1"
            or row.derivation_id != generated_derivation_id(command.company_id, command.action_id)
            or row.sha256 != pins.output_sha256
            or row.media_type != "application/json"
        ):
            raise ExecutionDeniedError("Native issued output binding differs from original action")
        return ArtifactRevisionRef(
            company_id=command.company_id,
            artifact_id=row.artifact_id,
            artifact_revision_id=row.artifact_revision_id,
            revision=row.revision,
            sha256=row.sha256,
            byte_length=row.byte_length,
        )

"""One non-retrying compiler/publication/receipt/proof effect within a durable step."""

import json
from decimal import Decimal

from nexus.company.contracts.actions import ResourceRevision
from nexus.company.management.generated_artifact_contracts import (
    GeneratedArtifactActionParameters,
    GeneratedArtifactPayload,
)
from nexus.company.management.generated_artifact_identity import require_action_payload
from nexus.company.management.generated_artifact_scope import generated_scope
from nexus.company.management.report_inputs import native_author
from nexus.execution.native_report_context import NativeReportContext
from nexus.execution.native_report_contracts import NativeReportResult
from nexus.execution.native_report_intent import NativeReportIntent
from nexus.execution.native_report_output import native_receipt, recover_known_output
from nexus.execution.runtime_contracts import EffectRecord, ExecutionDeniedError
from nexus.execution.runtime_support import execution_row, lease_scope, runtime_transaction


async def run_native_effect(context: NativeReportContext) -> NativeReportResult:
    """Read known issuance or perform exactly one freshly governed native publication."""
    record = (
        await recover_known_output(context)
        if context.lease.mode == "reconcile"
        else await publish_once(context)
    )
    if record.receipt is None or record.receipt.outcome != "succeeded":
        return result(context, "outcome_unknown", record)
    if context.action.tool == "company.report.write.v1":
        return result(context, "published", record)
    pins = GeneratedArtifactActionParameters.model_validate_json(
        json.dumps(context.action.parameters)
    )
    if pins.author_action_id is None:
        raise ExecutionDeniedError("Native check requires an actual author receipt selector")
    if context.lease.mode == "reconcile":
        accepted = await context.services.recovery.reconcile_verified_result(
            context.lease, context.identity, check_action_id=context.command.action_id
        )
    else:
        from nexus.execution.native_report_output import issued_reference

        protected = await issued_reference(context)
        if protected is None:
            raise ExecutionDeniedError("Native issued check is unavailable")
        accepted = await context.services.acceptance.publish_verified_result(
            context.lease,
            context.identity,
            action_id=pins.author_action_id,
            protected_result=protected,
        )
    await context.services.observe("acceptance_recorded", context.command)
    return NativeReportResult(
        company_id=context.command.company_id,
        task_id=context.command.task_id,
        action_id=context.command.action_id,
        segment_id=context.command.segment_id,
        status="accepted" if accepted.verdict == "pass" else accepted.verdict,
        receipt_id=record.receipt.receipt_id,
        acceptance_id=accepted.acceptance_id,
        limitations=accepted.limitations,
    )


async def publish_once(context: NativeReportContext) -> EffectRecord:
    """Resolve selectors before intent; fresh publication revalidates complete native inputs."""
    prepared = await compile_action(context)
    resources = await current_resources(context)
    begin = await context.services.effects.begin(
        context.lease,
        context.identity,
        context.command.action_id,
        resources=resources,
        before_intent=NativeReportIntent(context, prepared, resources),
    )
    if not begin.permit_external_call:
        return begin.record
    await context.services.observe("intent_committed", context.command)
    output = await context.services.publisher.publish(
        context.lease, context.identity, context.command.action_id, prepared
    )
    await context.services.observe("artifact_published", context.command)
    record = await context.services.effects.record_receipt(
        context.lease,
        context.identity,
        await native_receipt(context, output),
        actual_usd=Decimal(0),
    )
    await context.services.observe("receipt_recorded", context.command)
    return record


async def compile_action(context: NativeReportContext) -> GeneratedArtifactPayload:
    """Regenerate from durable exact selectors; never use a serialized one-time permit."""
    pins = GeneratedArtifactActionParameters.model_validate_json(
        json.dumps(context.action.parameters)
    )
    scope = generated_scope(context.lease, context.command.action_id)
    if context.action.tool == "company.report.write.v1" and pins.report_id is not None:
        prepared = await context.services.producer.prepare_report(
            scope, context.identity, pins.report_id, pins.evidence_ids
        )
    elif context.action.tool == "company.report.check.v1" and pins.author_action_id is not None:
        prepared = await context.services.producer.prepare_check(
            context.lease, context.identity, pins.author_action_id
        )
    else:
        raise ExecutionDeniedError("Native compiler tool/selector is unregistered")
    rule = context.services.publisher.rules.get(context.action.tool)
    if rule is None:
        raise ExecutionDeniedError("Native output rule is unregistered")
    require_action_payload(context.action, rule, prepared)
    return prepared


async def current_resources(context: NativeReportContext) -> tuple[ResourceRevision, ...]:
    """Read actual resource conditions under the same current signed native work scope."""
    async with runtime_transaction(
        context.services.factory, lease_scope(context.lease), context.identity
    ) as (session, _, _):
        binding, _ = native_author(await execution_row(session, lease_scope(context.lease)))
        return await context.services.resources.current(
            session, binding, context.action, context.identity
        )


def result(context: NativeReportContext, status: str, record: EffectRecord) -> NativeReportResult:
    """A workflow return records known facts only; no business outcome is inferred."""
    return NativeReportResult.model_validate(
        {
            "company_id": context.command.company_id,
            "task_id": context.command.task_id,
            "action_id": context.command.action_id,
            "segment_id": context.command.segment_id,
            "status": status,
            "receipt_id": record.receipt.receipt_id if record.receipt else None,
            "limitations": ("native_mechanical_only", "business_readiness_unproven"),
        }
    )

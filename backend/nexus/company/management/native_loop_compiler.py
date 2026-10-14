"""DB-only full native pending-action rederivation before exact approval consumption."""

import json
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.base import BrainReadScope
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.generated_artifact_contracts import (
    GeneratedArtifactActionParameters,
    GeneratedArtifactPayload,
)
from nexus.company.management.generated_artifact_identity import require_action_payload
from nexus.company.management.native_registered_target import read_registered_verification_target
from nexus.company.management.plans import RunBinding
from nexus.company.management.transactions import ManagementDeniedError
from nexus.execution.native_report_services import NativeReportServices
from nexus.harness.journal_contracts import ActionRecord
from nexus.harness.journal_models import CompanyControl


def action_scope(binding: RunBinding, record: ActionRecord) -> BrainReadScope:
    """Retain the exact current configured actor/work and durable action audit identity."""
    return BrainReadScope(
        company_id=binding.company_id,
        workspace_id=binding.workspace_id,
        principal_id=binding.actor_id,
        operation_id=record.proposal.action_id,
        trace_id=binding.trace_id,
        task_id=binding.task_id,
        task_trace_id=binding.trace_id,
        actor_id=binding.actor_id,
    )


async def compile_authorization(
    session: AsyncSession,
    control: CompanyControl,
    native: NativeReportServices,
    binding: RunBinding,
    identity: VerifiedIdentity,
    record: ActionRecord,
    phase: Literal["author", "verifier"],
) -> GeneratedArtifactPayload:
    """Resolve actual sources/native target and compare every exact action recipe/hash pin."""
    pins = GeneratedArtifactActionParameters.model_validate_json(
        json.dumps(record.proposal.parameters)
    )
    scope = action_scope(binding, record)
    producer = native.producer
    if phase == "author":
        if pins.report_id is None:
            raise ManagementDeniedError("Native author authorization lacks its report selector")
        sources = await producer.inputs.resolve_sources(
            session, control, scope, identity, pins.evidence_ids
        )
        saved, references = await producer.reports.prepare_author_inputs(
            session, control, scope, identity, pins.report_id
        )
        prepared = await producer.report_payload(session, scope, saved, sources, references)
    else:
        if pins.author_action_id is None:
            raise ManagementDeniedError(
                "Native verifier authorization lacks its actual author selector"
            )
        target = await read_registered_verification_target(
            session,
            control,
            binding,
            identity,
            pins.author_action_id,
            native.publisher.catalog,
            native.artifacts,
            native.publisher.freshness,
        )
        if canonical_sha256(target) != pins.verification_target_sha256:
            raise ManagementDeniedError("Native check authorization target changed")
        command = await producer.inputs.load_native(session, control, scope, identity, target)
        prepared = await producer.check_payload(session, scope, command)
    rule = native.publisher.rules.get(record.proposal.tool)
    if rule is None:
        raise ManagementDeniedError("Native authorization output rule is unavailable")
    require_action_payload(record.proposal, rule, prepared)
    return prepared

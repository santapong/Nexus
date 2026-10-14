"""Actual succeeded verifier check receipt and selector, never caller-supplied result authority."""

import json
from datetime import datetime
from uuid import UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.acceptance import VerificationSpec
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_evidence import PreparedReportCheck
from nexus.company.management.acceptance_support import (
    actual_receipt,
    receipt_artifacts,
    resolve_native_target,
)
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.generated_artifact_contracts import (
    GeneratedArtifactActionParameters,
    GeneratedArtifactPayload,
)
from nexus.company.management.generated_artifact_identity import (
    generated_artifact_id,
    generated_derivation_id,
)
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_support import db_now, execution_row, lease_scope, require_lease
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CompanyControl, JournalAction


async def recovery_target(
    session: AsyncSession,
    control: CompanyControl,
    lease: ExecutionLease,
    check_action_id: UUID,
    now: datetime,
) -> tuple[VerificationSpec, ArtifactRevisionRef]:
    """Require a current reconciliation fence and actual exact successful check receipt."""
    work = await execution_row(session, lease_scope(lease))
    require_lease(work, lease, now)
    require_acceptance(lease.mode == "reconcile")
    row = await session.get(JournalAction, check_action_id)
    require_acceptance(row is not None)
    assert row is not None
    action = ActionProposal.model_validate_json(row.proposal_json)
    require_acceptance(
        action.company_id == lease.company_id == row.company_id
        and action.task_id == lease.task_id == row.task_id
        and action.trace_id == lease.trace_id == row.trace_id
        and action.actor_id == lease.actor_id
        and action.tool == "company.report.check.v1"
        and action.tool_version == "v1"
        and row.proposal_hash == action_hash(action)
        and row.state == "authorized"
        and row.consumed_at is not None
    )
    parameters = GeneratedArtifactActionParameters.model_validate_json(
        json.dumps(action.parameters)
    )
    require_acceptance(parameters.author_action_id is not None)
    assert parameters.author_action_id is not None
    target = await resolve_native_target(session, control, lease, parameters.author_action_id, now)
    require_acceptance(parameters.verification_target_sha256 == canonical_sha256(target))
    receipt = await actual_receipt(session, work, check_action_id)
    require_acceptance(receipt.proposal_hash == action_hash(action))
    references = await receipt_artifacts(session, receipt)
    require_acceptance(len(references) == 1)
    reference = references[0]
    await exact_check_output(session, lease, check_action_id, parameters, reference)
    require_lease(work, lease, await db_now(session))
    return target, reference


async def exact_check_output(
    session: AsyncSession,
    lease: ExecutionLease,
    action_id: UUID,
    parameters: GeneratedArtifactActionParameters,
    reference: ArtifactRevisionRef,
) -> None:
    """A pending blob or unrelated protected result cannot replace actual native publication."""
    artifact = await session.get(
        BrainArtifactRevision, (lease.company_id, reference.artifact_revision_id)
    )
    require_acceptance(artifact is not None)
    assert artifact is not None
    expected = generated_artifact_id(lease.company_id, action_id)
    require_acceptance(
        reference.artifact_id == expected
        and reference.artifact_revision_id == uuid5(expected, "revision:v1")
        and reference.revision == "generated-v1"
        and reference.sha256 == parameters.output_sha256
        and artifact.derivation_id == generated_derivation_id(lease.company_id, action_id)
        and artifact.media_type == "application/json"
    )


async def require_recovered_payload(
    session: AsyncSession,
    scope: BrainReadScope,
    check_action_id: UUID,
    prepared: PreparedReportCheck,
    current: GeneratedArtifactPayload,
) -> None:
    """Recomputed full production inputs must match the original immutable action pins."""
    row = await session.get(JournalAction, check_action_id)
    require_acceptance(row is not None and row.company_id == scope.company_id)
    assert row is not None
    action = ActionProposal.model_validate_json(row.proposal_json)
    pins = GeneratedArtifactActionParameters.model_validate_json(json.dumps(action.parameters))
    require_acceptance(
        current.company_id == scope.company_id
        and current.raw_bytes == prepared.protected.text.encode()
        and pins.recipe_version == current.recipe_version
        and pins.output_sha256 == current.output_sha256
        and pins.input_snapshot_sha256 == current.input_snapshot_sha256
    )

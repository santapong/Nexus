"""Actual succeeded SV receipt binding; no plan resolution, protected READ or acceptance write."""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.acceptance import VerificationSpec
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_provenance import exact_artifact
from nexus.company.management.acceptance_support import acceptance_scope, actual_receipt
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.report_input_contracts import native_author
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.company.strategy.artifact_contracts import StrategyArtifactRule, StrategyCheckParameters
from nexus.company.strategy.artifact_identity import strategy_artifact_id, strategy_derivation_id
from nexus.company.strategy.contracts import STRATEGY_CHECK_CRITERIA, STRATEGY_CHECK_RECIPE
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt
from nexus.execution.runtime_support import db_now, execution_row, lease_scope, require_lease
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CompanyControl, JournalAction


@dataclass(frozen=True)
class StrategyVerifierReceipt:
    """Facts read from native rows; neither a permit nor a passing mechanical check."""

    action: ActionProposal
    receipt: ActionReceipt
    original_intent_fence: int
    protected_result: ArtifactRevisionRef
    parameters: StrategyCheckParameters


def _require_action(
    row: JournalAction, lease: ExecutionLease, target: VerificationSpec, rule: StrategyArtifactRule
) -> tuple[ActionProposal, StrategyCheckParameters]:
    action = ActionProposal.model_validate_json(row.proposal_json)
    parameters = StrategyCheckParameters.model_validate_json(
        json.dumps(action.parameters, allow_nan=False)
    )
    require_acceptance(
        row.company_id == lease.company_id == target.company_id == rule.company_id
        and row.state == "authorized"
        and row.consumed_at is not None
        and (row.id, row.task_id, row.trace_id, row.proposal_hash)
        == (action.action_id, action.task_id, action.trace_id, action_hash(action))
        and (action.company_id, action.task_id, action.trace_id, action.actor_id)
        == (lease.company_id, lease.task_id, lease.trace_id, lease.actor_id)
        and (action.tool, action.tool_version, action.resource)
        == (rule.tool, rule.tool_version, rule.resource_symbol)
        and rule.tool == "company.cycle-artifact.check.v1"
        and parameters.author_action_id == target.action_id
        and parameters.author_action_id != action.action_id
        and parameters.verification_target_sha256 == canonical_sha256(target)
        and target.check_recipe == STRATEGY_CHECK_RECIPE
        and target.criterion_ids == STRATEGY_CHECK_CRITERIA
    )
    return action, parameters


async def _require_result(
    session: AsyncSession,
    lease: ExecutionLease,
    action: ActionProposal,
    parameters: StrategyCheckParameters,
    receipt: ActionReceipt,
    reference: ArtifactRevisionRef,
    rule: StrategyArtifactRule,
    effect_created_at: datetime,
) -> None:
    artifact_id = strategy_artifact_id(lease.company_id, action.action_id)
    require_acceptance(
        reference.company_id == lease.company_id
        and reference.artifact_id == artifact_id
        and reference.artifact_revision_id == uuid5(artifact_id, "revision:v1")
        and reference.revision == "strategy-v1"
        and reference.sha256 == parameters.output_sha256
        and len(receipt.artifacts) == 1
        and receipt.artifacts[0].company_id == reference.company_id
        and (
            receipt.artifacts[0].artifact_id,
            receipt.artifacts[0].revision,
            receipt.artifacts[0].sha256,
        )
        == (reference.artifact_id, reference.revision, reference.sha256)
        and receipt.proposal_hash == action_hash(action)
    )
    row = await exact_artifact(session, acceptance_scope(lease, action.action_id), reference)
    require_acceptance(
        row.derivation_id == strategy_derivation_id(lease.company_id, action.action_id)
        and row.resource_id == rule.target.resource_id
        and row.media_type == "application/json"
        and row.data_classification in {"internal", "confidential", "restricted"}
        and effect_created_at <= row.recorded_at <= receipt.recorded_at
        and hashlib.sha256(row.raw_text.encode()).hexdigest() == parameters.output_sha256
    )


async def _require_original_attempt(
    session: AsyncSession, lease: ExecutionLease, effect: EffectIntent
) -> None:
    attempt = await session.get(
        ExecutionAttempt, (lease.company_id, lease.task_id, effect.action_id)
    )
    require_acceptance(
        attempt is not None
        and (
            attempt.company_id,
            attempt.task_id,
            attempt.trace_id,
            attempt.attempt_id,
            attempt.kind,
            attempt.fence,
        )
        == (
            lease.company_id,
            lease.task_id,
            lease.trace_id,
            effect.action_id,
            "tool_attempts",
            effect.intent_fence,
        )
        and attempt.reserved_at <= effect.created_at
    )


async def require_strategy_verifier_receipt(
    session: AsyncSession,
    control: CompanyControl,
    lease: ExecutionLease,
    identity: VerifiedIdentity,
    target: VerificationSpec,
    *,
    verifier_action_id: UUID,
    protected_result: ArtifactRevisionRef,
    rule: StrategyArtifactRule,
    credential: AuthenticatedWorkerIdentity,
) -> StrategyVerifierReceipt:
    """Caller separately proves current S/SV plan, sources and protected check contents."""
    # Keep this >50-line receipt/fence and final credential/lease clock boundary together.
    target = VerificationSpec.model_validate(target.model_dump(warnings=False))
    rule = StrategyArtifactRule.model_validate(rule.model_dump(warnings=False))
    reference = ArtifactRevisionRef.model_validate(protected_result.model_dump(warnings=False))
    require_acceptance(
        session.in_transaction()
        and control.company_id == lease.company_id
        and isinstance(credential, AuthenticatedWorkerIdentity)
        and credential.identity == identity
        and (identity.principal_id, identity.workspace_id) == (lease.actor_id, lease.workspace_id)
    )
    work = await execution_row(session, lease_scope(lease))
    now = await db_now(session)
    require_lease(work, lease, now, execute=True)
    credential.require_time(now)
    binding, _ = native_author(work)
    require_acceptance(binding == target.verifier)
    row = await session.get(JournalAction, verifier_action_id)
    require_acceptance(row is not None and row.id == verifier_action_id)
    assert row is not None
    action, parameters = _require_action(row, lease, target, rule)
    effect = await session.get(EffectIntent, (lease.company_id, verifier_action_id))
    require_acceptance(
        effect is not None
        and effect.company_id == lease.company_id
        and effect.action_id == verifier_action_id
        and effect.attempt_kind == "tool_attempts"
        and type(effect.intent_fence) is int
        and 0 < effect.intent_fence <= lease.fence
    )
    assert effect is not None
    await _require_original_attempt(session, lease, effect)
    receipt = await actual_receipt(session, work, verifier_action_id)
    await _require_result(
        session, lease, action, parameters, receipt, reference, rule, effect.created_at
    )
    now = await db_now(session)
    require_acceptance(
        effect.created_at <= receipt.recorded_at <= now
        and row.consumed_at is not None
        and row.consumed_at <= effect.created_at
    )
    require_lease(work, lease, now, execute=True)
    credential.require_time(now)
    return StrategyVerifierReceipt(action, receipt, effect.intent_fence, reference, parameters)

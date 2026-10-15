"""Read-only actual SV receipt facts, under the real reader's current protected READ."""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.scope_support import require_brain_scope
from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.acceptance import VerificationSpec
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_provenance import exact_artifact
from nexus.company.management.acceptance_support import actual_receipt
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.report_input_contracts import native_author
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.company.strategy.application_role import require_strategy_application_role
from nexus.company.strategy.artifact_contracts import StrategyArtifactRule, StrategyCheckParameters
from nexus.company.strategy.artifact_identity import strategy_artifact_id, strategy_derivation_id
from nexus.company.strategy.contracts import STRATEGY_CHECK_CRITERIA, STRATEGY_CHECK_RECIPE
from nexus.company.strategy.publication_protection import require_credential
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt, ExecutionWork
from nexus.execution.runtime_support import db_now
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CompanyControl, JournalAction


@dataclass(frozen=True)
class StrategyVerifierReceipt:
    """Immutable native facts; neither an execute permit nor a mechanical passing verdict."""

    action: ActionProposal
    receipt: ActionReceipt
    original_intent_fence: int
    protected_result: ArtifactRevisionRef
    parameters: StrategyCheckParameters


def _require_action(
    row: JournalAction, work: ExecutionWork, target: VerificationSpec, rule: StrategyArtifactRule
) -> tuple[ActionProposal, StrategyCheckParameters]:
    action = ActionProposal.model_validate_json(row.proposal_json)
    parameters = StrategyCheckParameters.model_validate_json(
        json.dumps(action.parameters, allow_nan=False)
    )
    require_acceptance(
        row.company_id == work.company_id == target.company_id == rule.company_id
        and row.state == "authorized"
        and row.consumed_at is not None
        and (row.id, row.task_id, row.trace_id, row.proposal_hash)
        == (action.action_id, action.task_id, action.trace_id, action_hash(action))
        and (action.company_id, action.task_id, action.trace_id, action.actor_id)
        == (work.company_id, work.task_id, work.trace_id, work.actor_id)
        and (action.tool, action.tool_version, action.resource)
        == (rule.tool, rule.tool_version, rule.resource_symbol)
        and rule.tool == "company.cycle-artifact.check.v1"
        and parameters.author_action_id == target.action_id != action.action_id
        and parameters.verification_target_sha256 == canonical_sha256(target)
        and target.check_recipe == STRATEGY_CHECK_RECIPE
        and target.criterion_ids == STRATEGY_CHECK_CRITERIA
    )
    return action, parameters


async def _require_result(
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    artifacts: BoundedArtifactReader,
    action: ActionProposal,
    parameters: StrategyCheckParameters,
    receipt: ActionReceipt,
    reference: ArtifactRevisionRef,
    rule: StrategyArtifactRule,
    effect: EffectIntent,
) -> None:
    # Keep the exact metadata -> complete READ -> raw bytes order at one cohesive boundary.
    artifact_id = strategy_artifact_id(scope.company_id, action.action_id)
    require_acceptance(
        reference.company_id == scope.company_id
        and reference.artifact_id == artifact_id
        and reference.artifact_revision_id == uuid5(artifact_id, "revision:v1")
        and reference.revision == "strategy-v1"
        and reference.sha256 == parameters.output_sha256
        and len(receipt.artifacts) == 1
        and (
            receipt.artifacts[0].company_id,
            receipt.artifacts[0].artifact_id,
            receipt.artifacts[0].revision,
            receipt.artifacts[0].sha256,
        )
        == (reference.company_id, reference.artifact_id, reference.revision, reference.sha256)
        and receipt.proposal_hash == action_hash(action)
    )
    metadata = (
        await session.execute(
            select(
                BrainArtifactRevision.artifact_id,
                BrainArtifactRevision.artifact_revision_id,
                BrainArtifactRevision.revision,
                BrainArtifactRevision.sha256,
                BrainArtifactRevision.byte_length,
                BrainArtifactRevision.resource_id,
            ).where(
                BrainArtifactRevision.company_id == scope.company_id,
                BrainArtifactRevision.artifact_revision_id == reference.artifact_revision_id,
            )
        )
    ).one_or_none()
    require_acceptance(metadata is not None)
    assert metadata is not None
    require_acceptance(
        tuple(metadata)
        == (
            reference.artifact_id,
            reference.artifact_revision_id,
            reference.revision,
            reference.sha256,
            reference.byte_length,
            rule.target.resource_id,
        )
    )
    await artifacts.revalidate_artifact_reference(
        session, control, scope, identity, reference, await db_now(session)
    )
    row = await exact_artifact(session, scope, reference)
    require_acceptance(
        row.derivation_id == strategy_derivation_id(scope.company_id, action.action_id)
        and row.resource_id == rule.target.resource_id
        and row.media_type == "application/json"
        and row.data_classification in {"internal", "confidential", "restricted"}
        and effect.created_at <= row.recorded_at <= receipt.recorded_at
        and hashlib.sha256(row.raw_text.encode()).hexdigest() == parameters.output_sha256
    )


async def _require_attempt(
    session: AsyncSession, work: ExecutionWork, effect: EffectIntent, consumed_at: datetime
) -> None:
    attempt = await session.get(ExecutionAttempt, (work.company_id, work.task_id, effect.action_id))
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
            work.company_id,
            work.task_id,
            work.trace_id,
            effect.action_id,
            "tool_attempts",
            effect.intent_fence,
        )
        and consumed_at <= attempt.reserved_at <= effect.created_at
    )


async def require_strategy_verifier_facts_locked(
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    work: ExecutionWork,
    target: VerificationSpec,
    *,
    verifier_action_id: UUID,
    protected_result: ArtifactRevisionRef,
    rule: StrategyArtifactRule,
    artifacts: BoundedArtifactReader,
    credential: AuthenticatedWorkerIdentity,
) -> StrategyVerifierReceipt:
    """Prove native SV facts without impersonating its actor or manufacturing an execute lease.

    The caller must retain source/target grant windows through later awaits. This function
    performs current READ but returns no portable permission or captured grant substitute.
    """
    # The original attempt/receipt/result and final current credential clock stay together.
    target = VerificationSpec.model_validate(target.model_dump(warnings=False))
    rule = StrategyArtifactRule.model_validate(rule.model_dump(warnings=False))
    reference = ArtifactRevisionRef.model_validate(protected_result.model_dump(warnings=False))
    require_acceptance(
        session.in_transaction()
        and not control.paused
        and control.company_id == scope.company_id == work.company_id == target.company_id
        and scope.workspace_id == work.workspace_id
    )
    await require_strategy_application_role(session)
    require_credential(credential, identity, scope, await db_now(session))
    await require_brain_scope(session, control, scope, identity)
    actual = await session.get(ExecutionWork, (scope.company_id, target.verifier.task_id))
    require_acceptance(actual is work and work.state not in {"blocked", "outcome_unknown"})
    binding, _ = native_author(work)
    require_acceptance(binding == target.verifier)
    row = await session.get(JournalAction, verifier_action_id)
    require_acceptance(row is not None and row.id == verifier_action_id)
    assert row is not None
    action, parameters = _require_action(row, work, target, rule)
    effect = await session.get(EffectIntent, (scope.company_id, verifier_action_id))
    require_acceptance(
        effect is not None
        and effect.company_id == scope.company_id
        and effect.action_id == verifier_action_id
        and effect.attempt_kind == "tool_attempts"
        and type(effect.intent_fence) is int
        and type(work.fence) is int
        and 0 < effect.intent_fence <= work.fence
    )
    assert effect is not None
    assert row.consumed_at is not None
    await _require_attempt(session, work, effect, row.consumed_at)
    receipt = await actual_receipt(session, work, verifier_action_id)
    await _require_result(
        session,
        control,
        scope,
        identity,
        artifacts,
        action,
        parameters,
        receipt,
        reference,
        rule,
        effect,
    )
    now = await db_now(session)
    require_acceptance(
        effect.created_at <= receipt.recorded_at <= now
        and row.consumed_at is not None
        and row.consumed_at <= effect.created_at
    )
    require_credential(credential, identity, scope, now)
    return StrategyVerifierReceipt(action, receipt, effect.intent_fence, reference, parameters)

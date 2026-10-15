"""Actual issued P/C attempt/hold and succeeded verifier facts; no permission or mutation."""

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.results import ActionReceipt
from nexus.company.cycle_artifacts.action_parameters import (
    PresentationCheckParameters,
    SupportCheckParameters,
    decode_cycle_action,
)
from nexus.company.cycle_artifacts.common import criteria_for
from nexus.company.cycle_artifacts.model_issuance_facts import (
    require_canonical_model_issuance_locked,
)
from nexus.company.management.acceptance import VerificationSpec
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_provenance import exact_artifact
from nexus.company.management.acceptance_support import actual_receipt
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.report_input_contracts import native_author
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.company.strategy.application_role import require_strategy_application_role
from nexus.company.strategy.publication_protection import require_credential
from nexus.execution.cycle_deliverable_partition import require_cycle_deliverable_partition_locked
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt, ExecutionWork
from nexus.execution.runtime_support import db_now, require_lease, snapshot
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CompanyControl, CostHold, JournalAction

if TYPE_CHECKING:
    from nexus.company.cycle_artifacts.original_reader import CycleOriginalReader


@dataclass(frozen=True)
class CycleIssuedFacts:
    """Store-resolved rows; never an invocation permit or current effect authorization."""

    action: ActionProposal
    record: JournalAction
    effect: EffectIntent
    attempt: ExecutionAttempt
    hold: CostHold


@dataclass(frozen=True)
class CycleVerifierFacts:
    action: ActionProposal
    receipt: ActionReceipt
    original_intent_fence: int
    protected_result: ArtifactRevisionRef
    parameters: PresentationCheckParameters | SupportCheckParameters


async def _publication_candidates(session: AsyncSession, work: ExecutionWork, key: UUID) -> None:
    values = tuple(
        (
            await session.scalars(
                select(EffectIntent.action_id)
                .where(
                    EffectIntent.company_id == work.company_id,
                    EffectIntent.task_id == work.task_id,
                    EffectIntent.trace_id == work.trace_id,
                    EffectIntent.run_id == work.run_id,
                )
                .limit(3)
            )
        ).all()
    )
    limits = (work.model_requests_limit, work.model_requests_used, work.model_requests_delegated)
    quota = snapshot(work).registration.quota.model_requests
    require_acceptance(
        1 <= len(values) <= 2
        and len(set(values)) == len(values)
        and key in values
        and all(type(value) is int for value in limits)
        and limits[0] == quota
        and quota in {0, 1}
        and limits[2] == 0
    )
    others = tuple(value for value in values if value != key)
    if others:
        require_acceptance(limits == (1, 1, 0))
        await require_canonical_model_issuance_locked(session, work, others[0])
    else:
        require_acceptance(limits[1] == 0)


async def require_cycle_publication_intent_locked(
    session: AsyncSession,
    work: ExecutionWork,
    action: ActionProposal,
    record: JournalAction,
) -> CycleIssuedFacts:
    """Count all exact-run candidates before checking one original attempt and positive hold."""
    # Keep the complete journal/attempt/fence/hold comparison in one read-only >50-line boundary.
    await _publication_candidates(session, work, action.action_id)
    effect = await session.get(EffectIntent, (work.company_id, action.action_id))
    require_acceptance(effect is not None and record.consumed_at is not None)
    assert effect is not None and record.consumed_at is not None
    require_acceptance(
        record.state == "authorized"
        and ActionProposal.model_validate_json(record.proposal_json) == action
        and (record.id, record.company_id, record.task_id, record.trace_id, record.proposal_hash)
        == (action.action_id, work.company_id, work.task_id, work.trace_id, action_hash(action))
        and (action.company_id, action.task_id, action.trace_id, action.actor_id)
        == (work.company_id, work.task_id, work.trace_id, work.actor_id)
        and action.tool in {"company.cycle-artifact.write.v1", "company.cycle-artifact.check.v1"}
        and action.tool_version == "v1"
        and (
            effect.company_id,
            effect.action_id,
            effect.task_id,
            effect.trace_id,
            effect.run_id,
            effect.proposal_hash,
            effect.attempt_kind,
        )
        == (
            work.company_id,
            action.action_id,
            work.task_id,
            work.trace_id,
            work.run_id,
            action_hash(action),
            "tool_attempts",
        )
        and type(effect.intent_fence) is type(work.fence) is int
        and 0 < effect.intent_fence <= work.fence
        and all(
            type(getattr(work, "tool_attempts_" + key)) is int
            for key in ("limit", "used", "delegated")
        )
        and (work.tool_attempts_limit, work.tool_attempts_used, work.tool_attempts_delegated)
        == (1, 1, 0)
    )
    attempt = await session.get(ExecutionAttempt, (work.company_id, work.task_id, action.action_id))
    hold = await session.get(CostHold, action.action_id)
    require_acceptance(attempt is not None and hold is not None)
    assert attempt is not None and hold is not None
    require_acceptance(
        type(attempt.fence) is int
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
            action.action_id,
            "tool_attempts",
            effect.intent_fence,
        )
        and record.consumed_at <= attempt.reserved_at <= effect.created_at <= await db_now(session)
        and (hold.company_id, hold.task_id, hold.amount_usd)
        == (action.company_id, action.task_id, action.estimated_cost_usd)
        and hold.amount_usd > 0
        and hold.state in {"held", "unknown", "reconciled"}
        and ((hold.state == "reconciled") == (hold.actual_usd is not None))
    )
    return CycleIssuedFacts(action, record, effect, attempt, hold)


async def require_cycle_verifier_facts_locked(
    reader: "CycleOriginalReader",
    session: AsyncSession,
    control: CompanyControl,
    work: ExecutionWork,
    lease: ExecutionLease,
    identity: VerifiedIdentity,
    target: VerificationSpec,
    verifier_action_id: UUID,
    protected_result: ArtifactRevisionRef,
    *,
    credential: AuthenticatedWorkerIdentity,
) -> CycleVerifierFacts:
    """Require actual current independent PV/CV issuance and protected succeeded output."""
    # One >50-line boundary keeps native facts, complete READ and original chronology together.
    scope = reader.scope(lease, identity, verifier_action_id)
    await require_strategy_application_role(session)
    require_lease(work, lease, await db_now(session), execute=True)
    require_credential(credential, identity, scope, await db_now(session))
    rule, binding = reader.rules.bind(work), native_author(work)[0]
    require_acceptance(rule.phase == "check" and binding == target.verifier)
    admission = reader.catalog.cycle_admission
    require_acceptance(admission is not None)
    assert admission is not None
    await require_cycle_deliverable_partition_locked(
        session, control, work, identity, admission=admission, registry=reader.catalog.models
    )
    record = await session.get(JournalAction, verifier_action_id)
    require_acceptance(record is not None)
    assert record is not None
    action = ActionProposal.model_validate_json(record.proposal_json)
    pins = decode_cycle_action(
        action, expected_kind=rule.kind, phase="check", binding=binding, permission=rule.permission
    )
    require_acceptance(isinstance(pins, (PresentationCheckParameters, SupportCheckParameters)))
    assert isinstance(pins, (PresentationCheckParameters, SupportCheckParameters))
    require_acceptance(
        pins.author_action_id == target.action_id != verifier_action_id
        and pins.verification_target_sha256 == canonical_sha256(target)
        and target.criterion_ids == criteria_for(rule.kind)
        and target.check_recipe == rule.recipe_version
        and len(target.artifacts) == 2
    )
    author = await session.get(ExecutionWork, (work.company_id, target.author.task_id))
    require_acceptance(author is not None and native_author(author)[0] == target.author)
    assert author is not None
    author_receipt = await actual_receipt(session, author, target.action_id)
    require_acceptance(
        author_receipt.receipt_id == target.receipt_id
        and canonical_sha256(author_receipt) == target.receipt_sha256
        and author_receipt.proposal_hash == target.proposal_sha256
        and tuple(
            (r.company_id, r.artifact_id, r.revision, r.sha256) for r in author_receipt.artifacts
        )
        == tuple((r.company_id, r.artifact_id, r.revision, r.sha256) for r in target.artifacts)
    )
    for part, output in zip(
        ("json", "html" if rule.kind == "presentation" else "markdown"),
        target.artifacts,
        strict=True,
    ):
        expected = uuid5(
            work.company_id, f"cycle-deliverable:{rule.kind}:{target.action_id}:{part}"
        )
        require_acceptance(
            (output.artifact_id, output.artifact_revision_id, output.revision)
            == (expected, uuid5(expected, "revision:v1"), f"stockflow-{rule.kind}-{part}-v1")
        )
        await reader.artifacts.revalidate_artifact_reference(
            session, control, scope, identity, output, await db_now(session)
        )
    issued = await require_cycle_publication_intent_locked(session, work, action, record)
    receipt = await actual_receipt(session, work, verifier_action_id)
    reference = protected_result
    key = uuid5(work.company_id, f"cycle-check:{rule.kind}:{verifier_action_id}")
    require_acceptance(
        issued.effect.state == "succeeded"
        and len(receipt.artifacts) == 1
        and (
            reference.company_id,
            reference.artifact_id,
            reference.artifact_revision_id,
            reference.revision,
            reference.sha256,
        )
        == (
            work.company_id,
            key,
            uuid5(key, "revision:v1"),
            f"stockflow-{rule.kind}-check-v1",
            pins.output_sha256,
        )
        and tuple((r.company_id, r.artifact_id, r.revision, r.sha256) for r in receipt.artifacts)
        == ((reference.company_id, reference.artifact_id, reference.revision, reference.sha256),)
        and receipt.proposal_hash == action_hash(action)
    )
    await reader.artifacts.revalidate_artifact_reference(
        session, control, scope, identity, reference, await db_now(session)
    )
    row: BrainArtifactRevision = await exact_artifact(session, scope, reference)
    require_acceptance(
        row.resource_id == rule.target.resource_id
        and row.media_type == "application/json"
        and row.storage_symbol == reader.blobs.storage_symbol
        and row.data_classification == rule.policy("check").data_classification
        and row.derivation_id == uuid5(reference.artifact_id, "derivation:v1")
        and issued.effect.created_at
        <= row.recorded_at
        <= receipt.recorded_at
        <= await db_now(session)
    )
    require_lease(work, lease, await db_now(session), execute=True)
    require_credential(credential, identity, scope, await db_now(session))
    return CycleVerifierFacts(action, receipt, issued.effect.intent_fence, reference, pins)

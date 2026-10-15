"""Recognize a spent canonical native model allowance from immutable ledger metadata.

This is limited to FileModelEvidenceStore's artifact namespace/revision, not arbitrary
ModelEvidenceStore implementations. No model body/path read or current reauthorization.
"""

import json
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.contracts.actions import ActionProposal, ApprovalDecision
from nexus.company.contracts.base import Name
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_support import actual_receipt
from nexus.company.management.base import SHA256
from nexus.execution.cycle_partition_support import _same
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt, ExecutionWork
from nexus.execution.runtime_support import db_now
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CostHold, JournalAction


class _ModelPins(BaseModel):
    """Exact metadata shape emitted by model_authorizer_contracts.model_action_parameters."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    request_hash: SHA256
    request_id: UUID
    attempt_id: UUID
    registry_id: Name
    registry_revision: Name
    price_version: Name
    input_recipe_id: Name
    input_recipe_revision: Name
    input_recipe_hash: SHA256


async def require_canonical_model_issuance_locked(
    session: AsyncSession, work: ExecutionWork, key: UUID
) -> None:
    """Recognize canonical FileModelEvidenceStore metadata, never fresh authority or body proof."""
    # This cohesive >50-line original-footprint comparison excludes no failed/unknown model.
    record = await session.get(JournalAction, key)
    effect = await session.get(EffectIntent, (work.company_id, key))
    attempt = await session.get(ExecutionAttempt, (work.company_id, work.task_id, key))
    hold = await session.get(CostHold, key)
    require_acceptance(
        record is not None and effect is not None and attempt is not None and hold is not None
    )
    assert record is not None and effect is not None and attempt is not None and hold is not None
    action = ActionProposal.model_validate_json(record.proposal_json)
    pins = _ModelPins.model_validate_json(json.dumps(action.parameters, allow_nan=False))
    approval = ApprovalDecision.model_validate_json(record.approval_json or "")
    require_acceptance(
        _same(
            record,
            "id company_id task_id trace_id proposal_hash state",
            (key, work.company_id, work.task_id, work.trace_id, action_hash(action), "authorized"),
        )
        and _same(
            action,
            "action_id company_id task_id trace_id actor_id tool tool_version resource",
            (
                key,
                work.company_id,
                work.task_id,
                work.trace_id,
                work.actor_id,
                "model.request.v1",
                "v1",
                f"model:{pins.registry_id}",
            ),
        )
        and work.model_profile == "routine"
        and pins.attempt_id == key
        and pins.registry_revision == work.model_registry_version
        and pins.price_version == action.price_version
        and record.consumed_at is not None
        and _same(
            approval,
            "company_id action_id action_revision action_hash decision",
            (work.company_id, key, action.revision, action_hash(action), "approved"),
        )
        and approval.issued_at <= record.consumed_at < approval.expires_at
        and effect.created_at < approval.expires_at
        and _same(
            effect,
            "company_id action_id task_id trace_id run_id proposal_hash attempt_kind state",
            (
                work.company_id,
                key,
                work.task_id,
                work.trace_id,
                work.run_id,
                action_hash(action),
                "model_requests",
                "succeeded",
            ),
        )
        and type(effect.intent_fence) is type(attempt.fence) is int
        and 0 < effect.intent_fence <= work.fence
        and _same(
            attempt,
            "company_id task_id trace_id attempt_id kind fence",
            (
                work.company_id,
                work.task_id,
                work.trace_id,
                key,
                "model_requests",
                effect.intent_fence,
            ),
        )
        and record.consumed_at <= attempt.reserved_at <= effect.created_at
        and _same(
            hold,
            "company_id task_id amount_usd state",
            (work.company_id, work.task_id, action.estimated_cost_usd, "reconciled"),
        )
        and hold.amount_usd > 0
        and hold.actual_usd is not None
        and hold.actual_usd >= 0
    )
    receipt = await actual_receipt(session, work, key)
    require_acceptance(
        receipt.receipt_id == uuid5(key, "model-receipt-v1")
        and len(receipt.artifacts) == 1
        and receipt.artifacts[0].artifact_id == uuid5(key, str(pins.request_id))
        and receipt.artifacts[0].revision == "model-result-envelope-v1"
        and effect.created_at <= receipt.recorded_at <= await db_now(session)
    )

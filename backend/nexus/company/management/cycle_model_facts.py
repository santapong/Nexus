"""Pure historical model-charge joins, never current READ, issuance or report acceptance.

Supplied native rows/DTOs and evidence are data, not proof that a caller read an
actual database/protected file. A real reader must enforce permission, the full
expected family, original clocks and fresh native rechecks separately. No current
eligibility, credentials or vendor invoice is inferred here. Known ledger spend
survives missing/mismatched provenance and failed/stopped/domain-invalid output.

Cohesion exception: the complete historical native/receipt/protected-envelope/
price join and path-free projection exceed400 lines; splitting that ordered
financial invariant would obscure partial-charge retention. No extra framework.
"""

from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal
from typing import Literal, Self
from uuid import UUID, uuid5

from pydantic import AwareDatetime, model_validator

from nexus.company.contracts.base import USD
from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.directory_models import RegisteredWork
from nexus.company.management.base import SHA256, ManagementContract, Name
from nexus.company.management.canonical import canonical_sha256
from nexus.core.llm.company_adapter_contracts import CompanyModelRequest, request_hash
from nexus.core.llm.company_pricing import quote_cost, reconcile_cost
from nexus.core.llm.company_registry import ModelRegistry
from nexus.execution.runtime_contracts import EffectRecord, ExecutionSnapshot
from nexus.execution.runtime_models import ExecutionAttempt
from nexus.harness.canonical import action_hash
from nexus.harness.journal_budget import billing_day
from nexus.harness.journal_contracts import ActionRecord
from nexus.harness.journal_models import CostHold
from nexus.harness.lifecycle import ActionState
from nexus.harness.model_authorizer_contracts import ModelInputRecipe, model_action_parameters
from nexus.harness.model_evidence import ModelEvidence


class CycleModelFact(ManagementContract):
    root_task_id: UUID
    task_id: UUID
    trace_id: UUID
    run_id: UUID
    actor_id: UUID
    action_id: UUID
    request_id: UUID
    attempt_id: UUID
    proposal_sha256: SHA256
    request_sha256: SHA256
    recipe_sha256: SHA256
    registry_sha256: SHA256
    model_sha256: SHA256 | None
    artifact_sha256: SHA256 | None
    artifact_reference_sha256: SHA256 | None
    receipt_id: UUID | None
    intent_fence: int | None
    intent_at: AwareDatetime | None
    billing_at: AwareDatetime | None
    day: date | None
    native_state: Name | None
    provider_state: Name | None
    hold_state: Name | None
    reserved_usd: USD | None
    ledger_actual_usd: USD | None
    reported_usd: USD | None
    billing: Literal["known", "unconfirmed"]
    blockers: tuple[Name, ...]

    @model_validator(mode="after")
    def exact_confirmation(self) -> Self:
        if self.billing == "known":
            if (
                self.blockers
                or self.hold_state != "reconciled"
                or self.ledger_actual_usd is None
                or self.reported_usd != self.ledger_actual_usd
                or self.receipt_id is None
                or self.artifact_sha256 is None
                or self.intent_fence is None
                or self.native_state not in {"succeeded", "failed"}
            ):
                raise ValueError("Known model cost lacks its complete exact join")
        elif not self.blockers:
            raise ValueError("Unconfirmed model cost needs explicit blockers")
        return self


class CycleModelTotals(ManagementContract):
    root_task_id: UUID
    action_count: int
    known_spent_usd: USD
    held_usd: USD | None
    actual_total_usd: USD | None
    unconfirmed_action_ids: tuple[UUID, ...]


def _native_frame(
    registered: RegisteredWork,
    work: ExecutionSnapshot,
    action: ActionRecord,
    request: CompanyModelRequest,
    hold: CostHold | None,
) -> None:
    """Never attribute another native charge to this leaf/root; do not inspect active status."""
    item = work.registration.work
    if (
        (
            registered.company_id,
            registered.task_id,
            registered.trace_id,
            registered.actor_id,
            registered.workspace_id,
            registered.parent_task_id,
            registered.allocation_usd,
        )
        != (
            work.company_id,
            item.task_id,
            item.trace_id,
            work.actor_id,
            work.workspace_id,
            work.parent_task_id,
            item.budget_usd,
        )
        or item.company_id != work.company_id
        or registered.parent_task_id is None
        or registered.root_task_id == item.task_id
        or (request.company_id, request.task_id, request.trace_id, request.actor_id)
        != (work.company_id, item.task_id, item.trace_id, work.actor_id)
        or (
            action.company_id,
            action.proposal.company_id,
            action.proposal.action_id,
            action.proposal.task_id,
            action.proposal.trace_id,
            action.proposal.actor_id,
        )
        != (
            work.company_id,
            work.company_id,
            request.action_id,
            item.task_id,
            item.trace_id,
            work.actor_id,
        )
        or request.attempt_id != request.action_id
        or action_hash(action.proposal) != action.proposal_hash
        or work.registration.quota.model_requests < 1
        or (
            hold is not None
            and (hold.company_id, hold.task_id, hold.action_id)
            != (work.company_id, item.task_id, request.action_id)
        )
    ):
        raise ValueError("Crossed native model charge/root identity")


def _issuance(
    work: ExecutionSnapshot,
    action: ActionRecord,
    request: CompanyModelRequest,
    attempt: ExecutionAttempt | None,
    intent: EffectRecord | None,
    hold: CostHold | None,
) -> list[str]:
    blockers = []
    if intent is None:
        blockers.append("intent_missing")
    elif (
        (
            intent.company_id,
            intent.task_id,
            intent.trace_id,
            intent.run_id,
            intent.action_id,
            intent.proposal_hash,
            intent.attempt_kind,
        )
        != (
            request.company_id,
            request.task_id,
            request.trace_id,
            work.registration.run_id,
            request.action_id,
            action.proposal_hash,
            "model_requests",
        )
        or not 0 < intent.intent_fence <= work.fence
        or work.counters.model_requests < 1
    ):
        blockers.append("intent_mismatch")
    if attempt is None:
        blockers.append("attempt_missing")
    elif intent is None or (
        (
            attempt.company_id,
            attempt.task_id,
            attempt.trace_id,
            attempt.attempt_id,
            attempt.kind,
            attempt.fence,
            attempt.reserved_at,
        )
        != (
            request.company_id,
            request.task_id,
            request.trace_id,
            request.attempt_id,
            "model_requests",
            intent.intent_fence,
            intent.created_at,
        )
    ):
        blockers.append("attempt_mismatch")
    if intent is not None:
        approval = action.approval
        if (
            action.state != ActionState.AUTHORIZED
            or action.consumed_at is None
            or approval is None
            or approval.decision != "approved"
            or (
                approval.company_id,
                approval.action_id,
                approval.action_revision,
                approval.action_hash,
            )
            != (
                request.company_id,
                request.action_id,
                action.proposal.revision,
                action.proposal_hash,
            )
            or not approval.issued_at
            <= action.consumed_at
            <= intent.created_at
            < approval.expires_at
        ):
            blockers.append("approval_mismatch")
        if hold is not None and hold.day != billing_day(intent.created_at):
            blockers.append("day_mismatch")
    if hold is None:
        blockers.append("hold_missing")
    elif (
        hold.state not in {"held", "unknown", "reconciled"}
        or (hold.state == "reconciled") != (hold.actual_usd is not None)
        or hold.amount_usd != action.proposal.estimated_cost_usd
    ):
        blockers.append("hold_mismatch")
    return blockers


def join_cycle_model_fact(
    registered: RegisteredWork,
    work: ExecutionSnapshot,
    action: ActionRecord,
    request: CompanyModelRequest,
    recipe: ModelInputRecipe,
    registry: ModelRegistry,
    *,
    attempt: ExecutionAttempt | None,
    intent: EffectRecord | None,
    hold: CostHold | None,
    artifact: ArtifactRef | None = None,
    evidence: ModelEvidence | None = None,
    wire: bytes | None = None,
) -> CycleModelFact:
    """Join original issuance snapshots; post-anchor proof errors cannot erase ledger spend.

    Cohesion exception: this single pure join keeps original model/price, native
    receipt and protected bytes visibly ordered. It grants no candidate or permit.
    """
    work = ExecutionSnapshot.model_validate_json(work.model_dump_json())
    action = ActionRecord.model_validate_json(action.model_dump_json(by_alias=True))
    request = CompanyModelRequest.model_validate_json(request.model_dump_json(by_alias=True))
    recipe = ModelInputRecipe.model_validate_json(recipe.model_dump_json())
    registry = ModelRegistry.model_validate_json(registry.model_dump_json())
    _native_frame(registered, work, action, request, hold)
    if artifact is not None and type(artifact) is not ArtifactRef:
        raise ValueError("Model envelope reference cannot be a Brain artifact reference")
    malformed: list[str] = []
    if intent is not None:
        try:
            intent = EffectRecord.model_validate_json(intent.model_dump_json(by_alias=True))
        except ValueError:
            intent = None
            malformed.append("intent_malformed")
    if artifact is not None:
        try:
            artifact = ArtifactRef.model_validate_json(artifact.model_dump_json())
        except ValueError:
            artifact = None
            malformed.append("artifact_malformed")
    blockers = [*malformed, *_issuance(work, action, request, attempt, intent, hold)]
    if (
        action.proposal.parameters != model_action_parameters(request, recipe)
        or (action.proposal.tool, action.proposal.tool_version, action.proposal.resource)
        != ("model.request.v1", "v1", "model:" + request.registry_id)
        or (work.registration.model_profile, work.registration.model_registry_version)
        != (recipe.profile, request.registry_revision)
        or (registry.company_id, registry.revision, registry.pricebook_version)
        != (request.company_id, request.registry_revision, request.price_version)
        or action.proposal.price_version != request.price_version
    ):
        blockers.append("request_recipe_registry_mismatch")
    model = next((row for row in registry.models if row.registry_id == request.registry_id), None)
    reported = None
    receipt = intent.receipt if intent is not None else None
    if evidence is None:
        blockers.append("evidence_missing")
    else:
        try:
            if wire is None:
                evidence = ModelEvidence.model_validate_json(
                    evidence.model_dump_json(by_alias=True)
                )
            else:
                # Actual reader supplies original immutable bytes, never a
                # regenerated ordering of decoded Python frozensets.
                if type(wire) is not bytes or not 0 < len(wire) <= 2_000_000:
                    raise ValueError("Original model evidence wire exceeds its bound")
                decoded = ModelEvidence.model_validate_json(wire)
                decoded.require_binding()
                if decoded != evidence:
                    raise ValueError("Original model wire differs from supplied semantic evidence")
                evidence = decoded
            evidence.require_binding()
            whole = evidence.input_estimate.whole_request
            if (
                evidence.request != request
                or evidence.recipe != recipe
                or evidence.model != model
                or evidence.action_hash != action.proposal_hash
                or (whole is not None and whole.registry_sha256 != canonical_sha256(registry))
                or intent is None
                or evidence.source_event_at < intent.created_at
                or (
                    action.approval is not None and evidence.owner_id != action.approval.approver_id
                )
            ):
                raise ValueError("Original model provenance differs")
            raw = evidence.model_dump_json(by_alias=True).encode() if wire is None else wire
            if (
                len(raw) > 2_000_000
                or artifact is None
                or (
                    artifact.company_id,
                    artifact.artifact_id,
                    artifact.revision,
                    artifact.sha256,
                    artifact.allowed_principals,
                )
                != (
                    request.company_id,
                    uuid5(request.action_id, str(request.request_id)),
                    "model-result-envelope-v1",
                    hashlib.sha256(raw).hexdigest(),
                    (request.actor_id, evidence.owner_id),
                )
            ):
                raise ValueError("Protected model envelope differs")
            if (
                model is None
                or hold is None
                or (
                    quote_cost(model.price, request.bounds, now=evidence.source_event_at).amount_usd
                    != hold.amount_usd
                )
            ):
                blockers.append("reservation_mismatch")
            if evidence.result.billing == "known" and evidence.result.usage is not None:
                reported = reconcile_cost(
                    model.price if model else None,
                    evidence.result.usage,
                    now=evidence.source_event_at,
                ).amount_usd
            else:
                blockers.append("provider_billing_unknown")
        except ValueError:
            evidence = None
            blockers.append("evidence_mismatch")
    if artifact is None:
        blockers.append("artifact_missing")
    if receipt is None:
        blockers.append("receipt_missing")
    elif (
        intent is None
        or (
            receipt.company_id,
            receipt.action_id,
            receipt.task_id,
            receipt.trace_id,
            receipt.proposal_hash,
            receipt.receipt_id,
            receipt.outcome,
        )
        != (
            request.company_id,
            request.action_id,
            request.task_id,
            request.trace_id,
            action.proposal_hash,
            uuid5(request.action_id, "model-receipt-v1"),
            intent.state,
        )
        or artifact is None
        or receipt.artifacts != (artifact,)
        or evidence is None
        or receipt.recorded_at != evidence.checked_at
    ):
        blockers.append("receipt_mismatch")
    if (
        intent is None
        or intent.state not in {"succeeded", "failed"}
        or hold is None
        or hold.state != "reconciled"
        or reported is None
        or hold.actual_usd != reported
    ):
        blockers.append("billing_unconfirmed")
    if (
        intent is not None
        and intent.state == "succeeded"
        and evidence is not None
        and (
            evidence.result.status != "response"
            or evidence.result.usage is None
            or evidence.result.usage.input_tokens > request.bounds.input_tokens
            or evidence.result.usage.output_tokens > request.bounds.max_output_tokens
        )
    ):
        blockers.append("native_success_mismatch")
    unique = tuple(dict.fromkeys(blockers))
    return CycleModelFact(
        company_id=request.company_id,
        root_task_id=registered.root_task_id,
        task_id=request.task_id,
        trace_id=request.trace_id,
        actor_id=request.actor_id,
        run_id=work.registration.run_id,
        action_id=request.action_id,
        request_id=request.request_id,
        attempt_id=request.attempt_id,
        proposal_sha256=action.proposal_hash,
        request_sha256=request_hash(request),
        recipe_sha256=canonical_sha256(recipe),
        registry_sha256=canonical_sha256(registry),
        model_sha256=canonical_sha256(model) if model else None,
        artifact_sha256=artifact.sha256 if artifact else None,
        artifact_reference_sha256=canonical_sha256(artifact) if artifact else None,
        receipt_id=receipt.receipt_id if receipt else None,
        intent_fence=intent.intent_fence if intent else None,
        intent_at=intent.created_at if intent else None,
        billing_at=evidence.source_event_at if evidence else None,
        day=hold.day if hold else None,
        native_state=intent.state if intent else None,
        provider_state=evidence.result.status if evidence else None,
        hold_state=hold.state if hold else None,
        reserved_usd=hold.amount_usd if hold else None,
        ledger_actual_usd=hold.actual_usd if hold else None,
        reported_usd=reported,
        billing="unconfirmed" if unique else "known",
        blockers=unique,
    )


def total_cycle_model_facts(facts: tuple[CycleModelFact, ...]) -> CycleModelTotals:
    """Unique leaf actions only; caller still owes complete-family/authorized-read proof."""
    if not 0 < len(facts) <= 1000 or any(type(row) is not CycleModelFact for row in facts):
        raise ValueError("Model charge facts need one bounded typed collection")
    facts = tuple(CycleModelFact.model_validate_json(row.model_dump_json()) for row in facts)
    unique: dict[UUID, CycleModelFact] = {}
    for fact in facts:
        if (fact.company_id, fact.root_task_id) != (facts[0].company_id, facts[0].root_task_id):
            raise ValueError("Model charge collection crosses company/root")
        if fact.action_id in unique and unique[fact.action_id] != fact:
            raise ValueError("Conflicting duplicate model charge")
        unique[fact.action_id] = fact
    rows = tuple(unique.values())
    if len({row.request_id for row in rows}) != len(rows) or len(
        {row.attempt_id for row in rows}
    ) != len(rows):
        raise ValueError("Different model actions alias request/attempt identity")
    unresolved = tuple(sorted(row.action_id for row in rows if row.billing != "known"))
    spent = sum(
        (row.ledger_actual_usd or Decimal(0) for row in rows if row.hold_state == "reconciled"),
        Decimal(0),
    )
    held = (
        None
        if any(
            row.hold_state not in {"held", "unknown", "reconciled"} or row.reserved_usd is None
            for row in rows
        )
        else sum(
            (
                row.reserved_usd or Decimal(0)
                for row in rows
                if row.hold_state in {"held", "unknown"}
            ),
            Decimal(0),
        )
    )
    return CycleModelTotals(
        company_id=facts[0].company_id,
        root_task_id=facts[0].root_task_id,
        action_count=len(rows),
        known_spent_usd=spent,
        held_usd=held,
        actual_total_usd=None if unresolved else spent,
        unconfirmed_action_ids=unresolved,
    )

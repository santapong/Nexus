"""Pure supplied native charge joins; no SQL, model invocation or report acceptance.

Cohesion exception: one shared actual-type fixture and its splice/failure/day
controls exceed400 lines to keep each complete known charge visible and readable.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast
from uuid import UUID, uuid5

import pytest

from nexus.company.contracts.actions import ActionProposal, ApprovalDecision
from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.contracts.results import ActionReceipt
from nexus.company.contracts.work import WorkItem
from nexus.company.directory_models import RegisteredWork
from nexus.company.management.cycle_model_facts import (
    CycleModelFact,
    join_cycle_model_fact,
    total_cycle_model_facts,
)
from nexus.core.llm.company_adapter_contracts import CompanyModelRequest, request_hash
from nexus.core.llm.company_pricing import quote_cost, reconcile_cost
from nexus.core.llm.company_registry import ModelRegistry
from nexus.execution.runtime_contracts import (
    AttemptQuota,
    EffectRecord,
    ExecutionRegistration,
    ExecutionSnapshot,
)
from nexus.execution.runtime_models import ExecutionAttempt
from nexus.harness.canonical import action_hash
from nexus.harness.journal_budget import billing_day
from nexus.harness.journal_contracts import ActionRecord
from nexus.harness.journal_models import CostHold
from nexus.harness.lifecycle import ActionState
from nexus.harness.limits import LoopCounters
from nexus.harness.model_authorizer_contracts import ModelInputRecipe, model_action_parameters
from nexus.harness.model_evidence import FileModelEvidenceStore, ModelEvidence
from nexus.tests.unit.test_company_model_evidence import envelope
from nexus.tests.unit.test_company_provider_conformance import catalog


@dataclass
class Case:
    registered: RegisteredWork
    work: ExecutionSnapshot
    action: ActionRecord
    request: CompanyModelRequest
    recipe: ModelInputRecipe
    registry: ModelRegistry
    attempt: ExecutionAttempt | None
    intent: EffectRecord | None
    hold: CostHold | None
    artifact: ArtifactRef | None
    evidence: ModelEvidence | None

    def join(self) -> CycleModelFact:
        return join_cycle_model_fact(
            self.registered,
            self.work,
            self.action,
            self.request,
            self.recipe,
            self.registry,
            attempt=self.attempt,
            intent=self.intent,
            hold=self.hold,
            artifact=self.artifact,
            evidence=self.evidence,
        )


def case() -> Case:
    saved = envelope()
    assert saved.result.usage is not None
    call = saved.request.model_copy(update={"attempt_id": saved.request.action_id})
    digest = request_hash(call)
    saved = saved.model_copy(
        update={
            "request": call,
            "request_hash": digest,
            "input_estimate": saved.input_estimate.model_copy(update={"request_hash": digest}),
        }
    )
    now = saved.source_event_at
    native_at = now - timedelta(microseconds=1)
    reservation = quote_cost(saved.model.price, call.bounds, now=now).amount_usd
    assert saved.result.usage is not None
    actual = reconcile_cost(saved.model.price, saved.result.usage, now=now).amount_usd
    proposal = ActionProposal(
        company_id=call.company_id,
        action_id=call.action_id,
        task_id=call.task_id,
        trace_id=call.trace_id,
        actor_id=call.actor_id,
        revision=1,
        tool="model.request.v1",
        tool_version="v1",
        resource="model:" + call.registry_id,
        parameters=model_action_parameters(call, saved.recipe),
        policy_version="policy-1",
        price_version=call.price_version,
        estimated_cost_usd=reservation,
    )
    proposal_hash = action_hash(proposal)
    saved = saved.model_copy(update={"action_hash": proposal_hash})
    artifact = ArtifactRef(
        company_id=call.company_id,
        artifact_id=uuid5(call.action_id, str(call.request_id)),
        reference=f"/private/{call.company_id}/{call.action_id}/{call.request_id}.json",
        revision="model-result-envelope-v1",
        sha256=hashlib.sha256(saved.model_dump_json(by_alias=True).encode()).hexdigest(),
        allowed_principals=(call.actor_id, saved.owner_id),
    )
    registration = ExecutionRegistration(
        work=WorkItem(
            company_id=call.company_id,
            task_id=call.task_id,
            trace_id=call.trace_id,
            goal_id=UUID(int=40),
            department="engineering",
            title="Propose Nexus code",
            acceptance=("historical-coding-candidate",),
        ),
        run_id=UUID(int=50),
        workflow_name="company.coding.v1",
        workflow_version="v1",
        model_profile=saved.recipe.profile,
        model_registry_version=call.registry_revision,
        quota=AttemptQuota(model_requests=1, tool_attempts=0, rework_rounds=0, plan_revisions=0),
    )
    zero = LoopCounters(model_requests=0, tool_attempts=0, rework_rounds=0, plan_revisions=0)
    work = ExecutionSnapshot(
        company_id=call.company_id,
        registration=registration,
        workspace_id=UUID(int=60),
        actor_id=call.actor_id,
        parent_task_id=UUID(int=90),
        state="verifying",
        counters=zero.model_copy(update={"model_requests": 1}),
        delegated=zero,
        fence=7,
        worker_id=None,
        lease_principal_id=None,
        expires_at=None,
        segment_number=4,
        segment_id=UUID(int=70),
        waiting_action_id=None,
    )
    action = ActionRecord(
        company_id=call.company_id,
        proposal=proposal,
        proposal_hash=proposal_hash,
        approval=ApprovalDecision(
            company_id=call.company_id,
            decision_id=UUID(int=80),
            action_id=call.action_id,
            action_revision=1,
            action_hash=proposal_hash,
            approver_id=saved.owner_id,
            decision="approved",
            issued_at=native_at - timedelta(hours=1),
            expires_at=native_at + timedelta(hours=1),
        ),
        state=ActionState.AUTHORIZED,
        consumed_at=native_at - timedelta(microseconds=1),
    )
    receipt = ActionReceipt(
        company_id=call.company_id,
        receipt_id=uuid5(call.action_id, "model-receipt-v1"),
        action_id=call.action_id,
        task_id=call.task_id,
        trace_id=call.trace_id,
        proposal_hash=proposal_hash,
        outcome="succeeded",
        recorded_at=saved.checked_at,
        artifacts=(artifact,),
    )
    return Case(
        RegisteredWork(
            company_id=call.company_id,
            task_id=call.task_id,
            trace_id=call.trace_id,
            actor_id=call.actor_id,
            workspace_id=work.workspace_id,
            parent_task_id=work.parent_task_id,
            root_task_id=UUID(int=90),
            allocation_usd=Decimal(1),
            delegated_usd=Decimal(0),
            active=False,
        ),
        work,
        action,
        call,
        saved.recipe,
        catalog("openai"),
        ExecutionAttempt(
            company_id=call.company_id,
            task_id=call.task_id,
            trace_id=call.trace_id,
            attempt_id=call.attempt_id,
            kind="model_requests",
            fence=3,
            reserved_at=native_at,
        ),
        EffectRecord(
            company_id=call.company_id,
            action_id=call.action_id,
            task_id=call.task_id,
            trace_id=call.trace_id,
            run_id=registration.run_id,
            proposal_hash=proposal_hash,
            intent_fence=3,
            attempt_kind="model_requests",
            state="succeeded",
            created_at=native_at,
            receipt=receipt,
            verification=None,
        ),
        CostHold(
            company_id=call.company_id,
            task_id=call.task_id,
            action_id=call.action_id,
            day=billing_day(native_at),
            amount_usd=reservation,
            actual_usd=actual,
            state="reconciled",
        ),
        artifact,
        saved,
    )


def refresh_artifact(value: Case) -> None:
    assert value.evidence and value.artifact and value.intent and value.intent.receipt
    value.artifact = value.artifact.model_copy(
        update={
            "sha256": hashlib.sha256(
                value.evidence.model_dump_json(by_alias=True).encode()
            ).hexdigest()
        }
    )
    value.intent = value.intent.model_copy(
        update={"receipt": value.intent.receipt.model_copy(update={"artifacts": (value.artifact,)})}
    )


@pytest.mark.parametrize("outcome", ("ordinary", "provider-failed", "stopped", "invalid-content"))
def test_known_native_charge_survives_failure_stop_and_domain_content(outcome: str) -> None:
    value = case()
    assert value.intent and value.evidence and value.intent.receipt
    if outcome in {"provider-failed", "stopped"}:
        value.intent = value.intent.model_copy(
            update={
                "state": "failed",
                "receipt": value.intent.receipt.model_copy(update={"outcome": "failed"}),
            }
        )
    if outcome == "provider-failed":
        value.evidence = value.evidence.model_copy(
            update={
                "result": value.evidence.result.model_copy(
                    update={"status": "failed", "error_code": "malformed"}
                )
            }
        )
    if outcome == "invalid-content":
        value.evidence = value.evidence.model_copy(
            update={
                "result": value.evidence.result.model_copy(
                    update={"structured_json": '{"not":"a code candidate"}'}
                )
            }
        )
    refresh_artifact(value)
    fact = value.join()
    assert value.hold and fact.billing == "known" and not fact.blockers
    assert fact.ledger_actual_usd == fact.reported_usd == value.hold.actual_usd
    assert fact.ledger_actual_usd and fact.ledger_actual_usd > 0
    assert fact.intent_fence == 3 and fact.run_id == value.work.registration.run_id
    assert (
        "/private" not in fact.model_dump_json() and "actual-result" not in fact.model_dump_json()
    )
    assert total_cycle_model_facts((fact,)).actual_total_usd == value.hold.actual_usd


@pytest.mark.parametrize(
    "missing", ("artifact", "evidence", "intent", "attempt", "receipt", "hold")
)
def test_missing_proof_is_unconfirmed_and_never_erases_native_ledger_actual(missing: str) -> None:
    value = case()
    original = value.hold.actual_usd if value.hold else None
    if missing == "receipt":
        assert value.intent
        value.intent = value.intent.model_copy(update={"receipt": None})
    else:
        setattr(value, missing, None)
    fact = value.join()
    assert fact.billing == "unconfirmed" and fact.blockers
    assert fact.ledger_actual_usd == (None if missing == "hold" else original)
    totals = total_cycle_model_facts((fact,))
    assert totals.actual_total_usd is None and totals.unconfirmed_action_ids == (
        value.request.action_id,
    )
    assert totals.known_spent_usd == (Decimal(0) if missing == "hold" else original)
    assert (totals.held_usd is None) == (missing == "hold")


@pytest.mark.parametrize(
    "splice",
    ("artifact-hash", "artifact-id", "acl", "model", "recipe", "receipt", "day", "fence", "amount"),
)
def test_provenance_mismatch_retains_known_ledger_cost_but_denies_confirmation(splice: str) -> None:
    value = case()
    assert (
        value.artifact and value.evidence and value.intent and value.hold and value.intent.receipt
    )
    if splice in {"artifact-hash", "artifact-id", "acl"}:
        update = (
            {"sha256": "f" * 64}
            if splice == "artifact-hash"
            else (
                {"artifact_id": UUID(int=999)}
                if splice == "artifact-id"
                else {"allowed_principals": ()}
            )
        )
        value.artifact = value.artifact.model_copy(update=update)
    elif splice == "model":
        value.evidence = value.evidence.model_copy(
            update={"model": value.evidence.model.model_copy(update={"model_id": "crossed-model"})}
        )
    elif splice == "recipe":
        value.evidence = value.evidence.model_copy(
            update={"recipe": value.recipe.model_copy(update={"minimum_score": Decimal("0.1")})}
        )
    elif splice == "receipt":
        value.intent = value.intent.model_copy(
            update={"receipt": value.intent.receipt.model_copy(update={"proposal_hash": "f" * 64})}
        )
    elif splice == "day":
        value.hold.day += timedelta(days=1)
    elif splice == "fence":
        assert value.attempt
        value.attempt.fence += 1
    else:
        value.hold.amount_usd += Decimal("0.1")
    fact = value.join()
    assert fact.billing == "unconfirmed" and fact.ledger_actual_usd == value.hold.actual_usd
    assert total_cycle_model_facts((fact,)).known_spent_usd == value.hold.actual_usd


def test_unknown_output_stays_held_and_saved_response_is_not_native_confirmation() -> None:
    value = case()
    assert value.intent and value.hold and value.evidence
    value.intent = value.intent.model_copy(update={"state": "outcome_unknown", "receipt": None})
    value.hold.state, value.hold.actual_usd = "unknown", None
    value.evidence = value.evidence.model_copy(
        update={
            "result": value.evidence.result.model_copy(
                update={"status": "failed", "billing": "unknown", "usage": None}
            )
        }
    )
    fact = value.join()
    assert fact.billing == "unconfirmed" and fact.ledger_actual_usd is None
    totals = total_cycle_model_facts((fact,))
    assert totals.held_usd == value.hold.amount_usd and totals.actual_total_usd is None


def test_wrong_native_owner_or_parent_is_denied_without_mutating_supplied_charge() -> None:
    value = case()
    assert value.hold
    actual = value.hold.actual_usd
    value.hold.company_id = UUID(int=900)
    with pytest.raises(ValueError):
        value.join()
    assert value.hold.actual_usd == actual
    value = case()
    value.registered.root_task_id = value.request.task_id
    with pytest.raises(ValueError):
        value.join()


def test_exact_replay_deduplicates_and_conflicting_identity_cannot_be_first_wins() -> None:
    value = case()
    fact = value.join()
    value.registered.delegated_usd = Decimal("0.5")
    assert value.join() == fact  # Delegated allocations are not extra spend.
    totals = total_cycle_model_facts((fact, fact))
    assert totals.action_count == 1 and totals.known_spent_usd == fact.ledger_actual_usd
    crossed = fact.model_copy(update={"ledger_actual_usd": Decimal("0.5")})
    with pytest.raises(ValueError):
        total_cycle_model_facts((fact, crossed))
    with pytest.raises(ValueError):
        total_cycle_model_facts((fact, fact.model_copy(update={"action_id": UUID(int=999)})))


async def test_actual_protected_model_envelope_roundtrip_remains_separate_from_brain(
    tmp_path: Path,
) -> None:
    value = case()
    assert value.evidence and value.intent and value.intent.receipt
    store = FileModelEvidenceStore(tmp_path)
    value.artifact = await store.save(value.evidence)
    value.evidence = await store.load(value.artifact)
    value.intent = value.intent.model_copy(
        update={"receipt": value.intent.receipt.model_copy(update={"artifacts": (value.artifact,)})}
    )
    assert value.join().billing == "known" and not store.pending_owners()
    from nexus.company.brain.sources import ArtifactRevisionRef

    wrong = ArtifactRevisionRef(
        company_id=value.request.company_id,
        artifact_id=value.artifact.artifact_id,
        artifact_revision_id=UUID(int=900),
        revision="model-result-envelope-v1",
        sha256=value.artifact.sha256,
        byte_length=100,
    )
    with pytest.raises(ValueError):
        join_cycle_model_fact(
            value.registered,
            value.work,
            value.action,
            value.request,
            value.recipe,
            value.registry,
            attempt=value.attempt,
            intent=value.intent,
            hold=value.hold,
            artifact=cast(ArtifactRef, wrong),
            evidence=value.evidence,
        )


def test_foreign_nested_registration_company_cannot_be_a_root_cost_fact() -> None:
    value = case()
    changed = value.work.registration.work.model_copy(update={"company_id": UUID(int=909)})
    value.work = value.work.model_copy(
        update={"registration": value.work.registration.model_copy(update={"work": changed})}
    )
    with pytest.raises(ValueError):
        value.join()


def test_forged_confirmation_cannot_erase_unconfirmed_provenance_or_change_money() -> None:
    value = case()
    fact = value.join()
    for changed in (
        fact.model_copy(update={"blockers": ("evidence_missing",)}),
        fact.model_copy(update={"ledger_actual_usd": Decimal("0.5")}),
    ):
        with pytest.raises(ValueError):
            total_cycle_model_facts((changed,))


def test_final_billing_clock_can_cross_bangkok_midnight_without_moving_issued_hold() -> None:
    value = case()
    assert value.evidence and value.intent and value.intent.receipt and value.attempt and value.hold
    clock = value.evidence.source_event_at.replace(hour=17, minute=0, second=0, microsecond=2)
    native = clock - timedelta(microseconds=4)
    price = value.evidence.model.price
    assert price and value.action.approval
    price = price.model_copy(
        update={
            "as_of": clock.date(),
            "valid_from": clock - timedelta(hours=1),
            "valid_until": clock + timedelta(hours=1),
        }
    )
    model = value.evidence.model.model_copy(update={"price": price})
    value.registry = value.registry.model_copy(update={"models": (model,)})
    value.evidence = value.evidence.model_copy(
        update={
            "model": model,
            "source_event_at": clock,
            "checked_at": clock + timedelta(microseconds=100),
        }
    )
    value.intent = value.intent.model_copy(
        update={
            "created_at": native,
            "receipt": value.intent.receipt.model_copy(
                update={"recorded_at": value.evidence.checked_at}
            ),
        }
    )
    value.attempt.reserved_at = native
    value.action = value.action.model_copy(
        update={
            "consumed_at": native - timedelta(microseconds=1),
            "approval": value.action.approval.model_copy(
                update={
                    "issued_at": native - timedelta(hours=1),
                    "expires_at": clock + timedelta(hours=1),
                }
            ),
        }
    )
    value.hold.day = billing_day(native)
    refresh_artifact(value)
    fact = value.join()
    assert billing_day(clock) != value.hold.day and fact.billing == "known"
    assert fact.day == billing_day(native) and fact.billing_at == clock

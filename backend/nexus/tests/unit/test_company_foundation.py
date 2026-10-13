"""Frozen contract and policy acceptance for the first company-system slice."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from nexus.company.contracts.actions import ActionProposal, ApprovalDecision, ResourceRevision
from nexus.company.contracts.company import CompanyMandate
from nexus.company.contracts.work import WorkItem, WorkPlan
from nexus.harness.approvals import ApprovalContext, require_exact_approval
from nexus.harness.canonical import action_hash, canonical_action
from nexus.harness.lifecycle import ActionState, require_transition
from nexus.harness.limits import LoopCounters, LoopLimits, consume_attempt

COMPANY = UUID(int=1)
OWNER = UUID(int=2)
ACTOR = UUID(int=3)
TASK = UUID(int=4)
TRACE = UUID(int=5)
NOW = datetime(2026, 10, 13, 10, tzinfo=UTC)


def proposal() -> ActionProposal:
    """Return a fixed internal proposal whose source is version-bound."""
    return ActionProposal(
        company_id=COMPANY,
        action_id=UUID(int=6),
        task_id=TASK,
        trace_id=TRACE,
        actor_id=ACTOR,
        revision=1,
        tool="workspace.patch",
        tool_version="1",
        resource="stockflow:committed-snapshot",
        parameters={"path": "readiness.md", "text": "draft"},
        preconditions=(
            ResourceRevision(resource="stockflow:committed-snapshot", revision="abc123"),
        ),
        policy_version="policy-1",
        price_version="prices-1",
        estimated_cost_usd=Decimal("0.50"),
    )


def decision(action: ActionProposal) -> ApprovalDecision:
    """Bind a single owner approval to the exact proposal."""
    return ApprovalDecision(
        company_id=COMPANY,
        decision_id=UUID(int=7),
        action_id=action.action_id,
        action_revision=action.revision,
        action_hash=action_hash(action),
        approver_id=OWNER,
        decision="approved",
        issued_at=NOW,
        expires_at=NOW + timedelta(hours=24),
    )


def approval_context() -> ApprovalContext:
    """Return authoritative state supplied by a future trusted runtime adapter."""
    return ApprovalContext(
        company_id=COMPANY,
        owner_id=OWNER,
        actor_id=ACTOR,
        now=NOW,
        policy_version="policy-1",
        price_version="prices-1",
        paused=False,
        resources=(ResourceRevision(resource="stockflow:committed-snapshot", revision="abc123"),),
    )


def test_exact_current_owner_approval_is_accepted() -> None:
    action = proposal()
    require_exact_approval(action, decision(action), approval_context())


@pytest.mark.parametrize(
    "change",
    [
        {"paused": True},
        {"owner_id": UUID(int=90)},
        {"actor_id": UUID(int=91)},
        {"company_id": UUID(int=92)},
        {"policy_version": "policy-2"},
        {"price_version": "prices-2"},
        {"now": NOW + timedelta(hours=24)},
        {"now": NOW - timedelta(seconds=1)},
        {"resources": ()},
        {
            "resources": (
                ResourceRevision(resource="stockflow:committed-snapshot", revision="changed"),
            )
        },
    ],
)
def test_stale_or_unauthorized_approval_cannot_authorize(change: dict[str, object]) -> None:
    action = proposal()
    context = ApprovalContext.model_validate(approval_context().model_dump() | change)
    with pytest.raises(ValueError):
        require_exact_approval(action, decision(action), context)


@pytest.mark.parametrize(
    "change",
    [
        {"revision": 2},
        {"resource": "another-repo"},
        {"tool": "git.push"},
        {"estimated_cost_usd": "0.51"},
        {"parameters": {"path": "private.md", "text": "draft"}},
    ],
)
def test_changed_payload_requires_a_new_approval(change: dict[str, object]) -> None:
    action = proposal()
    approved = decision(action)
    altered = ActionProposal.model_validate(action.model_dump() | change)
    with pytest.raises(ValueError):
        require_exact_approval(altered, approved, approval_context())


def test_nested_mutation_cannot_reuse_approval_despite_frozen_model() -> None:
    action = proposal()
    approved = decision(action)
    action.parameters["text"] = "changed"
    with pytest.raises(ValueError):
        require_exact_approval(action, approved, approval_context())


def test_hash_is_stable_across_json_key_order_and_wire_roundtrip() -> None:
    action = proposal()
    same = ActionProposal.model_validate(
        action.model_dump()
        | {
            "parameters": {"text": "draft", "path": "readiness.md"},
        }
    )
    assert action_hash(action) == action_hash(same)
    assert canonical_action(action) == canonical_action(
        ActionProposal.model_validate_json(
            action.model_dump_json(),
        )
    )


@pytest.mark.parametrize(
    "value", [Decimal("-0.01"), Decimal("NaN"), Decimal("Infinity"), Decimal("0.0000001")]
)
def test_invalid_money_is_rejected(value: Decimal) -> None:
    with pytest.raises(ValidationError):
        ActionProposal.model_validate(proposal().model_dump() | {"estimated_cost_usd": value})


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_nonfinite_action_json_is_rejected(value: float) -> None:
    with pytest.raises(ValidationError):
        ActionProposal.model_validate(proposal().model_dump() | {"parameters": {"value": value}})


def test_unknown_fields_and_naive_timestamps_are_rejected() -> None:
    with pytest.raises(ValidationError):
        ActionProposal.model_validate(proposal().model_dump() | {"bypass_policy": True})
    with pytest.raises(ValidationError):
        ApprovalDecision.model_validate(
            decision(proposal()).model_dump()
            | {
                "issued_at": datetime(2026, 10, 13),
            }
        )


def test_initial_mandate_matches_owner_budget_and_scope() -> None:
    mandate = CompanyMandate(company_id=COMPANY, owner_id=OWNER, version="1", purpose="DravenIQ")
    assert mandate.daily_cap_usd == Decimal("5.00")
    assert mandate.work_cap_usd == Decimal("1.00")
    assert mandate.oversight == "supervised"
    assert not mandate.self_improvement_enabled


def work(task_id: UUID, dependencies: tuple[UUID, ...] = ()) -> WorkItem:
    """Create a fixed acceptance-bearing plan node."""
    return WorkItem(
        company_id=COMPANY,
        task_id=task_id,
        trace_id=TRACE,
        goal_id=UUID(int=10),
        department="builder",
        title="Readiness task",
        acceptance=("Readiness evidence exists",),
        depends_on=dependencies,
    )


def test_dependency_plan_accepts_valid_dag() -> None:
    plan = WorkPlan(
        company_id=COMPANY,
        plan_id=UUID(int=11),
        goal_id=UUID(int=10),
        revision=1,
        items=(work(UUID(int=12)), work(UUID(int=13), (UUID(int=12),))),
    )
    assert len(plan.items) == 2


@pytest.mark.parametrize("case", ["cycle", "unknown", "duplicate", "company", "goal"])
def test_invalid_plan_cannot_be_scheduled(case: str) -> None:
    first, second = work(UUID(int=12)), work(UUID(int=13), (UUID(int=12),))
    if case == "cycle":
        first = work(UUID(int=12), (UUID(int=13),))
    elif case == "unknown":
        second = work(UUID(int=13), (UUID(int=99),))
    elif case == "duplicate":
        second = first
    elif case == "company":
        second = WorkItem.model_validate(second.model_dump() | {"company_id": UUID(int=99)})
    else:
        second = WorkItem.model_validate(second.model_dump() | {"goal_id": UUID(int=99)})
    with pytest.raises(ValidationError):
        WorkPlan(
            company_id=COMPANY,
            plan_id=UUID(int=11),
            goal_id=UUID(int=10),
            revision=1,
            items=(first, second),
        )


@pytest.mark.parametrize("verdict", [None, "reject", "inconclusive"])
def test_uncertain_verification_never_means_completion(verdict: str | None) -> None:
    with pytest.raises(ValueError):
        require_transition(ActionState.VERIFYING, ActionState.COMPLETED, verdict=verdict)


def test_only_passing_verification_allows_completion() -> None:
    require_transition(ActionState.VERIFYING, ActionState.COMPLETED, verdict="pass")
    with pytest.raises(ValueError):
        require_transition(ActionState.OUTCOME_UNKNOWN, ActionState.EXECUTING)


@pytest.mark.parametrize(
    "kind,maximum",
    [
        ("model_requests", 12),
        ("tool_attempts", 20),
        ("rework_rounds", 2),
        ("plan_revisions", 2),
    ],
)
def test_limits_survive_serialization_and_count_failed_attempts(kind: str, maximum: int) -> None:
    counters = LoopCounters()
    limits = LoopLimits()
    for _ in range(maximum):
        counters = consume_attempt(counters, limits, kind)
    resumed = LoopCounters.model_validate_json(counters.model_dump_json())
    with pytest.raises(ValueError):
        consume_attempt(resumed, limits, kind)
    assert getattr(resumed, kind) == maximum


def test_invalid_attempt_kind_cannot_silently_bypass_limits() -> None:
    with pytest.raises(ValueError):
        consume_attempt(LoopCounters(), LoopLimits(), "free_retry")

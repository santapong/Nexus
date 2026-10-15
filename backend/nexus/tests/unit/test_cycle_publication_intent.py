"""Actual begin control flow; current authority/session delivery remains explicitly mocked."""

from uuid import UUID

import pytest

from nexus.company.management.plan_registration import registration
from nexus.execution.intent_checks import BeforeIntentCheck, CompositeBeforeIntentCheck
from nexus.execution.runtime_contracts import ExecutionDeniedError
from nexus.execution.runtime_support import KINDS, registration_digest
from nexus.harness.canonical import action_hash
from nexus.tests.unit.selected_intent_boundary_fixture import (
    IntentBoundary,
    NoOpIntentCheck,
    intent_boundary,
)


def cycle_boundary(index: int = 4) -> IntentBoundary:
    """Reuse real begin/lease fixture with one exact catalog P/PV/C/CV slot."""
    case = intent_boundary()
    admission = case.catalog.cycle_admission
    assert admission is not None
    slot = admission.slots[index]
    bound = slot.child.binding
    saved = registration(bound, slot.work, slot.child.quota)
    values = {
        name: getattr(bound, name)
        for name in ("company_id", "task_id", "trace_id", "actor_id", "workspace_id", "run_id")
    }
    case.lease = case.lease.model_copy(update=values)
    case.identity = case.identity.model_copy(
        update={"principal_id": bound.actor_id, "workspace_id": bound.workspace_id}
    )
    for name, value in values.items():
        setattr(case.work, name, value)
    for name in ("workflow_name", "workflow_version", "model_profile", "model_registry_version"):
        setattr(case.work, name, getattr(bound, name))
    case.work.registration_json = saved.model_dump_json()
    case.work.registration_hash = registration_digest(saved)
    case.work.lease_principal_id = bound.actor_id
    for kind in KINDS:
        setattr(case.work, kind + "_limit", getattr(slot.child.quota, kind))
    case.proposal = case.proposal.model_copy(
        update={
            **{
                key: value for key, value in values.items() if key not in {"workspace_id", "run_id"}
            },
            "tool": slot.tool.tool,
            "tool_version": slot.tool.tool_version,
            "resource": slot.tool.resource,
        }
    )
    case.action.task_id, case.action.trace_id = bound.task_id, bound.trace_id
    case.action.proposal_json = case.proposal.model_dump_json()
    case.action.proposal_hash = action_hash(case.proposal)
    case.hold.task_id = bound.task_id
    return case


@pytest.mark.parametrize("index", [4, 5, 6, 7])
@pytest.mark.parametrize("which", ["missing", "noop", "composite"])
async def test_real_begin_requires_exact_cycle_guard_before_any_reservation(
    monkeypatch: pytest.MonkeyPatch, index: int, which: str
) -> None:
    case = cycle_boundary(index)
    store, noop = case.install(monkeypatch), NoOpIntentCheck()
    check: BeforeIntentCheck | None = None if which == "missing" else noop
    if which == "composite":
        check = CompositeBeforeIntentCheck((noop,))
    with pytest.raises(
        ExecutionDeniedError,
        match=r"^Fresh cycle deliverable intent requires its exact native checks$",
    ):
        await store.begin(case.lease, case.identity, case.proposal.action_id, before_intent=check)
    case.untouched()
    case.management.assert_not_awaited()
    assert noop.calls == 0


@pytest.mark.parametrize("index", [4, 5, 6, 7])
async def test_known_original_fence_returns_before_cycle_hook_or_reservation(
    monkeypatch: pytest.MonkeyPatch, index: int
) -> None:
    case = cycle_boundary(index)
    original = case.known()
    store, noop = case.install(monkeypatch), NoOpIntentCheck()
    result = await store.begin(
        case.lease, case.identity, case.proposal.action_id, before_intent=noop
    )
    assert not result.permit_external_call and result.record.state == "outcome_unknown"
    assert result.record.intent_fence == original.intent_fence == 1 < case.work.fence
    assert result.record.receipt is None and result.record.verification is None
    case.untouched(issued=True)
    case.authority.assert_not_awaited()
    case.management.assert_not_awaited()
    assert noop.calls == 0


@pytest.mark.parametrize("field", ["fence", "worker_id", "segment_id", "expired"])
async def test_stale_cycle_lease_denies_before_new_guard_or_mutation(
    monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    case = cycle_boundary()
    lease = case.lease
    if field == "expired":
        case.work.lease_until = case.now
    else:
        lease = lease.model_copy(update={field: 99 if field == "fence" else UUID(int=999)})
    store, noop = case.install(monkeypatch), NoOpIntentCheck()
    with pytest.raises(ExecutionDeniedError, match="lease"):
        await store.begin(lease, case.identity, case.proposal.action_id, before_intent=noop)
    case.untouched()
    case.authority.assert_not_awaited()
    assert noop.calls == 0


@pytest.mark.parametrize("index", [4, 5, 6, 7])
def test_real_management_kind_guard_denies_without_changing_any_reserved_slice(index: int) -> None:
    from nexus.company.management.plan_support import validate_plan_action
    from nexus.tests.unit.cycle_catalog_fixture import cycle_catalog
    from nexus.tests.unit.test_company_cycle_catalog_integration import declared_charter

    case = cycle_boundary(index)
    admission = case.catalog.cycle_admission
    assert admission is not None
    # Real pure managed-budget boundary; no native-E/material qualification is supplied here.
    with pytest.raises(ValueError, match="tool-attempt"):
        validate_plan_action(
            case.catalog,
            admission.slots[index].child,
            declared_charter(cycle_catalog()),
            case.proposal,
            "model_requests",
            case.now,
        )
    case.untouched()

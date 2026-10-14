"""Pure read-boundary probes; mocked ORM rows do not qualify PostgreSQL registration."""

from copy import deepcopy
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from nexus.company.management.plan_models import ManagementPlanHead
from nexus.company.management.plan_registration import registration
from nexus.execution.cycle_partition_checks import require_cycle_native_partition
from nexus.execution.runtime_contracts import ExecutionDeniedError
from nexus.execution.runtime_support import registration_digest, snapshot
from nexus.tests.unit.cycle_admission_fixture import Cycle
from nexus.tests.unit.cycle_partition_fixture import Partition, partition


async def check(item: Partition) -> None:
    await require_cycle_native_partition(
        item.session,
        item.control,
        item.work,
        item.identity,
        admission=item.cycle.admission,
        registry=item.cycle.registry,
    )


def retained(item: Partition) -> list[dict[str, object]]:
    return [
        deepcopy({key: value for key, value in row.__dict__.items() if not key.startswith("_sa_")})
        for row in (
            *item.executions,
            *item.directories,
            item.control,
            item.procedure,
            *item.events,
            *item.decisions,
        )
    ]


@pytest.mark.parametrize("leaf", ["author", "verifier", "sender"])
async def test_actual_shaped_full_partition_preserves_reserved_slices_and_child_usage(
    monkeypatch: pytest.MonkeyPatch,
    leaf: str,
) -> None:
    from nexus.execution import cycle_partition_checks as module

    item = partition(monkeypatch)
    index = {"author": 3, "verifier": 4, "sender": 11}[leaf]
    item.work = item.executions[index]
    item.identity = item.identity.model_copy(update={"principal_id": item.work.actor_id})
    monkeypatch.setattr(
        module, "require_runtime_scope", AsyncMock(return_value=item.directories[index])
    )
    before = retained(item)
    await check(item)
    await check(item)
    assert retained(item) == before
    assert item.executions[1].model_requests_used == 1
    assert item.executions[0].model_requests_used == 0
    assert item.executions[0].model_requests_delegated == 3
    item.session.begin.assert_not_called()
    item.session.flush.assert_not_called()
    item.session.commit.assert_not_called()


@pytest.mark.parametrize("detached", ["control", "work"])
async def test_supplied_detached_rows_cannot_replace_actual_locked_rows(
    monkeypatch: pytest.MonkeyPatch,
    detached: str,
) -> None:
    item = partition(monkeypatch)
    before = retained(item)
    with pytest.raises(ValueError):
        await require_cycle_native_partition(
            item.session,
            deepcopy(item.control) if detached == "control" else item.control,
            deepcopy(item.work) if detached == "work" else item.work,
            item.identity,
            admission=item.cycle.admission,
            registry=item.cycle.registry,
        )
    assert retained(item) == before


async def test_actual_runtime_scope_failure_cannot_be_replaced_by_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.execution import cycle_partition_checks as module

    item = partition(monkeypatch)
    monkeypatch.setattr(
        module,
        "require_runtime_scope",
        AsyncMock(side_effect=ExecutionDeniedError("current scope unavailable")),
    )
    before = retained(item)
    with pytest.raises(ExecutionDeniedError, match="current scope unavailable"):
        await check(item)
    assert retained(item) == before


async def test_equal_usd_display_scale_preserves_original_registration_bytes_and_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = partition(monkeypatch)
    slots = list(item.cycle.admission.slots)
    original = slots[0]
    slots[0] = original.model_copy(
        update={
            "child": original.child.model_copy(update={"allocation_usd": Decimal(".080000")}),
            "work": original.work.model_copy(update={"budget_usd": Decimal(".080000")}),
        }
    )
    admission = item.cycle.admission.model_copy(update={"slots": tuple(slots)})
    item.cycle = Cycle(admission, item.cycle.registry, item.cycle.strategy, item.cycle.full)
    actual = item.executions[1]
    expected = registration(slots[0].child.binding, slots[0].work, slots[0].child.quota)
    assert snapshot(actual).registration == expected
    assert registration_digest(expected) != actual.registration_hash
    original_json, original_hash = actual.registration_json, actual.registration_hash
    before = retained(item)
    await check(item)
    assert retained(item) == before
    assert (actual.registration_json, actual.registration_hash) == (original_json, original_hash)


@pytest.mark.parametrize(
    "kind",
    ["no_transaction", "paused", "missing_binding", "revoked", "strategy_only", "foreign_actor"],
)
async def test_missing_current_authority_never_becomes_partition_success(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    item = partition(monkeypatch)
    if kind == "no_transaction":
        item.session.in_transaction.return_value = False
    elif kind == "paused":
        item.control.paused = True
    elif kind == "missing_binding":
        item.bindings.clear()
    elif kind == "revoked":
        head = item.stored[
            (ManagementPlanHead, (item.control.company_id, item.cycle.admission.plan_id))
        ]
        head.state = "revoked"  # type: ignore[attr-defined]
    elif kind == "strategy_only":
        binding = item.bindings[item.work.task_id]
        item.bindings[item.work.task_id] = binding.model_copy(
            update={"plan": binding.plan.model_copy(update={"revision": 1})}
        )
    else:
        item.identity = item.identity.model_copy(update={"principal_id": UUID(int=999)})
    before = retained(item)
    with pytest.raises(ValueError):
        await check(item)
    assert retained(item) == before


@pytest.mark.parametrize(
    "kind", ["hidden_inactive", "extra_execution", "intermediate", "foreign_root", "overflow"]
)
async def test_all_descendants_are_counted_before_matching_good_rows(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    item = partition(monkeypatch)
    if kind == "hidden_inactive":
        extra = deepcopy(item.directories[-1])
        extra.task_id = UUID(int=999)
        extra.active = False
        item.directories.append(extra)
    elif kind == "extra_execution":
        extra_execution = deepcopy(item.executions[-1])
        extra_execution.task_id = UUID(int=999)
        item.executions.append(extra_execution)
    elif kind == "intermediate":
        item.directories[3].parent_task_id = item.directories[1].task_id
    elif kind == "foreign_root":
        item.directories[3].root_task_id = UUID(int=999)
    else:
        item.directories.extend([item.directories[-1]] * 1001)
    before = retained(item)
    with pytest.raises(ValueError):
        await check(item)
    assert retained(item) == before


@pytest.mark.parametrize(
    "kind",
    [
        "native_limit",
        "native_used",
        "native_delegated",
        "root_model_use",
        "root_tool_use",
        "root_revision_use",
        "model_partition",
        "tool_partition",
        "usd_partition",
        "child_usd",
        "child_delegation",
        "sql_limit",
        "root_lease",
        "hash",
        "run",
    ],
)
async def test_permanent_native_and_sibling_limits_cannot_borrow_or_refill(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    item = partition(monkeypatch)
    root = item.executions[0]
    if kind.startswith("native_"):
        setattr(item.work, "model_requests_" + kind.removeprefix("native_"), 1)
    elif kind == "root_model_use":
        root.model_requests_used = 1
    elif kind == "root_tool_use":
        root.tool_attempts_used = 1
    elif kind == "root_revision_use":
        root.plan_revisions_used = 0
    elif kind == "model_partition":
        root.model_requests_delegated = 2
    elif kind == "tool_partition":
        root.tool_attempts_delegated = 10
    elif kind == "usd_partition":
        item.directories[0].delegated_usd = Decimal(".95")
    elif kind == "child_usd":
        item.directories[1].allocation_usd = Decimal(".50")
    elif kind == "child_delegation":
        item.directories[1].delegated_usd = Decimal(".01")
    elif kind == "sql_limit":
        item.executions[1].model_requests_limit = 2
    elif kind == "root_lease":
        root.worker_id = UUID(int=999)
    elif kind == "hash":
        item.executions[1].registration_hash = "f" * 64
    else:
        item.executions[1].run_id = UUID(int=999)
    before = retained(item)
    with pytest.raises(ValueError):
        await check(item)
    assert retained(item) == before


@pytest.mark.parametrize(
    "kind", ["missing", "extra", "wrong_root", "wrong_previous", "wrong_owner", "wrong_decision"]
)
async def test_actual_administrative_revision_evidence_is_required(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    item = partition(monkeypatch)
    if kind == "missing":
        item.events.clear()
    elif kind == "extra":
        item.events.append(deepcopy(item.events[0]))
    else:
        field = {
            "wrong_root": "parent_run_id",
            "wrong_previous": "previous_plan_revision_id",
            "wrong_owner": "owner_id",
            "wrong_decision": "owner_decision_id",
        }[kind]
        setattr(item.events[0], field, UUID(int=999))
    before = retained(item)
    with pytest.raises(ValueError):
        await check(item)
    assert retained(item) == before

"""Mocked SQL partition boundaries, not actual Strategy READ or PostgreSQL qualification."""

from copy import deepcopy
from decimal import Decimal

import pytest

from nexus.company.management.strategy_stage_partition import (
    require_strategy_stage_partition_locked,
)
from nexus.tests.unit.strategy_stage_partition_fixture import Stage, stage_case


async def check(item: Stage) -> None:
    await require_strategy_stage_partition_locked(
        item.session,
        item.control,
        item.identity,
        admission=item.admission,
        registry=item.registry,
        proof=item.proof,
    )


def retained(item: Stage) -> list[dict[str, object]]:
    return [
        deepcopy({k: v for k, v in row.__dict__.items() if not k.startswith("_sa_")})
        for row in item.all_rows()
    ]


async def test_current_stage_one_preserves_original_family_and_permanent_slices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = await stage_case(monkeypatch)
    before = retained(item)
    await check(item)
    await check(item)
    assert retained(item) == before
    assert item.executions[0].model_requests_delegated == 1
    assert item.executions[0].tool_attempts_delegated == 2
    assert item.executions[0].plan_revisions_used == 0
    for method in ("add", "add_all", "flush", "commit", "begin"):
        getattr(item.session, method).assert_not_called()
    assert item.binding_queries >= 4  # The real current_binding lookup runs for BOTH children.


@pytest.mark.parametrize(
    "change",
    [
        "hidden_inactive",
        "intermediate",
        "foreign_child",
        "inactive_child",
        "quota",
        "stored_hash",
        "usd",
        "delegated_usd",
        "delegated_tools",
        "root_model_used",
        "root_fence",
        "revision_used",
        "revision_event",
        "revoked",
        "decision_hash",
        "foreign_owner",
        "membership",
        "privileged",
        "wrong_producing_plan",
        "no_transaction",
    ],
)
async def test_changed_actual_stage_scope_denies_without_writes_or_refill(
    monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    item = await stage_case(monkeypatch)
    item.change(change)
    before = retained(item)
    with pytest.raises(ValueError):
        await check(item)
    assert retained(item) == before


async def test_value_equal_usd_keeps_original_stored_registration_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = await stage_case(monkeypatch)
    slots = list(item.admission.slots)
    original = slots[0]
    slots[0] = original.model_copy(
        update={
            "child": original.child.model_copy(update={"allocation_usd": Decimal(".080000")}),
            "work": original.work.model_copy(update={"budget_usd": Decimal(".080000")}),
        }
    )
    item.admission = item.admission.model_copy(update={"slots": tuple(slots)})
    before = retained(item)
    await check(item)
    assert retained(item) == before


async def test_original_proof_credential_deadline_survives_later_partition_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = await stage_case(monkeypatch)
    item.expire_at_family = True
    before = retained(item)
    with pytest.raises(ValueError):
        await check(item)
    assert retained(item) == before
    assert item.clock == item.proof.initial.sources.credential.expires_at

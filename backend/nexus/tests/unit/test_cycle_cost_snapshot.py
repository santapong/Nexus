"""Whole registered-family projection from supplied rows; no actual SQL or runtime proof."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from nexus.company.management.cycle_cost_contracts import FamilyCostCapture, NativeCostHold
from nexus.company.management.cycle_cost_snapshot import project_family_costs
from nexus.company.management.nexus_coding_admission import NexusCodingAdmission
from nexus.tests.unit.test_nexus_coding_admission import admission


def test_unregistered_ten_roles_are_partial_not_zero_confirmed_company_work() -> None:
    profile = admission()
    capture = FamilyCostCapture(
        observed_at=datetime.now(UTC),
        owner_id=profile.procedure.binding.actor_id,
        control_policy="old-policy-is-historical",
        control_prices="new-current-price-does-not-relabel-history",
        control_paused=True,
        profile_bound=True,
        works=(),
        selections=(),
        orphan_holds=(),
        blockers=(),
    )
    result = project_family_costs(profile, capture, {})
    assert result.basis == "registered_family_lifetime" and not result.complete_membership
    assert len(result.missing_task_ids) == 11 and result.totals.actual_total_usd is None
    assert result.totals.known_spent_usd == 0 and not result.company_completed


def test_orphan_reconciled_native_money_is_visible_even_when_proof_is_missing() -> None:
    profile = admission()
    hold = NativeCostHold(
        company_id=profile.company_id,
        action_id=UUID(int=909),
        task_id=profile.slots[0].work.task_id,
        day=datetime.now(UTC).date(),
        amount_usd=Decimal(".3"),
        actual_usd=Decimal(".2"),
        state="reconciled",
    )
    capture = FamilyCostCapture(
        observed_at=datetime.now(UTC),
        owner_id=profile.procedure.binding.actor_id,
        control_policy="policy",
        control_prices="p",
        control_paused=False,
        profile_bound=False,
        works=(),
        selections=(),
        orphan_holds=(hold,),
        blockers=("native_action_missing",),
    )
    result = project_family_costs(profile, capture, {})
    assert result.totals.known_spent_usd == Decimal(".2") and result.totals.actual_total_usd is None
    assert result.charges[0].confirmation == "unconfirmed"


async def test_source_revoke_after_model_read_does_not_promote_private_fact_in_final_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import AsyncMock

    from nexus.company.brain.scope_support import BrainDeniedError
    from nexus.company.management import cycle_cost_snapshot as snapshot_module
    from nexus.company.management import cycle_model_reader as source_module
    from nexus.company.management.cycle_cost_snapshot import CycleCostSnapshotReader
    from nexus.company.management.planning_native_facts import clock_us
    from nexus.tests.unit.test_cycle_model_reader import supplied_case

    value = await supplied_case(tmp_path, monkeypatch)
    observed = FamilyCostCapture(
        observed_at=datetime.now(UTC),
        owner_id=value.owner.identity.principal_id,
        control_policy="p",
        control_prices="q",
        control_paused=False,
        profile_bound=True,
        works=(value.selected.directory,),
        selections=(value.selected,),
        orphan_holds=(),
        blockers=(),
    )
    reader = CycleCostSnapshotReader(value.reader.factory, value.reader.catalog, value.reader)
    calls = 0

    async def captured(*args: object, **kwargs: object) -> FamilyCostCapture:
        nonlocal calls
        calls += 1
        if calls == 2:
            monkeypatch.setattr(
                source_module,
                "require_resources",
                AsyncMock(side_effect=BrainDeniedError("revoked after protected read")),
            )
        return observed

    monkeypatch.setattr(reader, "_capture_locked", captured)
    monkeypatch.setattr(snapshot_module, "management_owner_transaction", value.transaction)
    result = await reader.read(value.scope, value.owner, end_us=clock_us() + 30_000_000)
    assert result.value.totals.known_spent_usd == value.selected.hold.actual_usd
    assert result.value.charges[0].model_fact is None


def complete_capture() -> tuple[NexusCodingAdmission, FamilyCostCapture]:
    from nexus.company.contracts.work import WorkItem
    from nexus.company.management.cycle_cost_contracts import DirectoryCostWork
    from nexus.company.management.plan_registration import registration
    from nexus.execution.runtime_contracts import ExecutionSnapshot
    from nexus.harness.limits import LoopCounters

    profile = admission()
    root = profile.procedure
    item = WorkItem(
        company_id=profile.company_id,
        task_id=root.binding.task_id,
        trace_id=root.binding.trace_id,
        goal_id=profile.goal.goal_id,
        department="management",
        title="Non-executing goal procedure allocation",
        acceptance=("management.non-executing-allocation.v1",),
        budget_usd=root.allocation_usd,
    )
    bindings = [(root.binding, item, root.quota, root.allocation_usd, None)] + [
        (
            slot.child.binding,
            slot.work,
            slot.child.quota,
            slot.child.allocation_usd,
            root.binding.task_id,
        )
        for slot in profile.slots
    ]
    zero = LoopCounters(model_requests=0, tool_attempts=0, rework_rounds=0, plan_revisions=0)
    rows = []
    for bound, work, quota, amount, parent in bindings:
        native = ExecutionSnapshot(
            company_id=profile.company_id,
            registration=registration(bound, work, quota),
            workspace_id=bound.workspace_id,
            actor_id=bound.actor_id,
            parent_task_id=parent,
            state="eligible",
            counters=zero,
            delegated=zero,
            fence=0,
            worker_id=None,
            lease_principal_id=None,
            expires_at=None,
            segment_number=0,
            segment_id=None,
            waiting_action_id=None,
        )
        rows.append(
            DirectoryCostWork(
                company_id=profile.company_id,
                task_id=bound.task_id,
                trace_id=bound.trace_id,
                actor_id=bound.actor_id,
                workspace_id=bound.workspace_id,
                parent_task_id=parent,
                root_task_id=root.binding.task_id,
                allocation_usd=amount,
                delegated_usd=Decimal(0),
                active=False,
                work=native,
            )
        )
    return profile, FamilyCostCapture(
        observed_at=datetime.now(UTC),
        owner_id=root.binding.actor_id,
        control_policy="p",
        control_prices="old-price-no-eligibility-refresh",
        control_paused=True,
        profile_bound=True,
        works=tuple(rows),
        selections=(),
        orphan_holds=(),
        blockers=(),
    )


def test_actual_complete_family_metadata_can_have_zero_calls_without_company_completion() -> None:
    profile, capture = complete_capture()
    value = project_family_costs(profile, capture, {})
    assert value.complete_membership and not value.company_completed
    assert len(value.unissued_task_ids) == 11 and value.totals.known_spent_usd == 0


def test_root_native_registration_drift_cannot_claim_complete_family() -> None:
    profile, capture = complete_capture()
    root = capture.works[0]
    assert root.work
    drift = root.model_copy(update={"allocation_usd": Decimal(".01")})
    value = project_family_costs(
        profile, capture.model_copy(update={"works": (drift, *capture.works[1:])}), {}
    )
    assert (
        not value.complete_membership
        and profile.procedure.binding.task_id in value.mismatched_task_ids
    )


def test_native_hold_day_mismatch_retains_money_but_cannot_confirm_tool_charge() -> None:
    from datetime import timedelta

    from nexus.company.management.cycle_cost_contracts import (
        DirectoryCostWork,
        NativeCostAttempt,
        NativeCostSelection,
    )
    from nexus.company.management.cycle_cost_snapshot import _charge
    from nexus.harness.canonical import action_hash
    from nexus.tests.unit.test_cycle_model_facts import case as native_case

    value = native_case()
    assert value.hold and value.intent and value.attempt
    proposal = value.action.proposal.model_copy(update={"tool": "read.file.v1"})
    digest = action_hash(proposal)
    assert value.intent.receipt
    intent = value.intent.model_copy(
        update={
            "attempt_kind": "tool_attempts",
            "proposal_hash": digest,
            "receipt": value.intent.receipt.model_copy(update={"proposal_hash": digest}),
        }
    )
    selected = NativeCostSelection(
        directory=DirectoryCostWork(
            **{
                key: getattr(value.registered, key)
                for key in DirectoryCostWork.model_fields
                if key not in {"schema_version", "work"}
            },
            work=value.work,
        ),
        action=value.action.model_copy(update={"proposal": proposal, "proposal_hash": digest}),
        intent=intent,
        hold=NativeCostHold(
            **{
                key: getattr(value.hold, key)
                for key in NativeCostHold.model_fields
                if key != "schema_version"
            }
        ),
        attempt=NativeCostAttempt(
            **{
                key: getattr(value.attempt, key)
                for key in NativeCostAttempt.model_fields
                if key != "schema_version"
            }
        ).model_copy(update={"kind": "tool_attempts"}),
    )
    assert _charge(selected, None).confirmation == "known"
    assert selected.hold
    selected = selected.model_copy(
        update={
            "hold": selected.hold.model_copy(update={"day": selected.hold.day + timedelta(days=1)})
        }
    )
    result = _charge(selected, None)
    assert result.ledger_actual_usd == value.hold.actual_usd
    assert result.confirmation == "unconfirmed" and "native_day_mismatch" in result.blockers

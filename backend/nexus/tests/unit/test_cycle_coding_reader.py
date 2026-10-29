"""Actual protected C header/envelope costs; native/current-source SQL is supplied."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal, cast
from unittest.mock import AsyncMock

import pytest

from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.management.cycle_coding_sources import CodingCostSources
from nexus.company.management.cycle_cost_contracts import FamilyCostCapture
from nexus.company.management.cycle_cost_snapshot import CycleCostSnapshotReader
from nexus.company.management.cycle_model_reader import CycleModelReader
from nexus.company.management.planning_native_facts import clock_us
from nexus.harness.model_evidence import ModelEvidence
from nexus.tests.unit.cycle_coding_fixture import coding_case


async def test_history_metadata_accepts_admitted_title_without_altering_native_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nexus.company.management.coding_prepared_history import validate_history_locked

    f = await coding_case(tmp_path, monkeypatch)
    native = f.selected.directory.work
    assert native is not None
    actual = native.registration.work.model_copy(update={"title": "Model proposed coder"})
    registered = native.registration.model_copy(update={"work": actual})
    selected = f.selected.model_copy(
        update={
            "directory": f.selected.directory.model_copy(
                update={"work": native.model_copy(update={"registration": registered})}
            )
        }
    )
    f.state.selected = selected
    async with f.transaction() as (session, control, _):
        observed, _, _ = await validate_history_locked(
            f.store,
            session,
            control,
            f.scope,
            f.owner,
            f.header.action_id,
            end_us=clock_us() + 10_000_000,
        )
    assert observed.directory.work is not None
    assert observed.directory.work.registration == registered
    assert observed.directory.work.registration.work.title == "Model proposed coder"
    assert not f.store.pending_owners()


@pytest.mark.parametrize("family", [False, True])
@pytest.mark.parametrize(
    "fault", [None, "native_title", "budget", "acceptance", "unapproved", "wrong_owner"]
)
async def test_historical_profile_joins_exact_native_work_to_approved_r2(
    family: bool, fault: str | None
) -> None:
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from uuid import UUID

    from nexus.company.management.canonical import canonical_sha256
    from nexus.company.management.cycle_model_reader import stored_coding_profile
    from nexus.company.management.plan_models import ManagementPlanRevision
    from nexus.tests.unit.test_coding_intent import prepared_case
    from nexus.tests.unit.test_nexus_coding_admission import planning_origin

    _, catalog, _, _ = prepared_case()
    admission = catalog.nexus_coding_admission
    assert admission is not None
    payload = admission.payload("execution", origin=planning_origin(admission))
    actual = payload.plan.items[1].model_copy(update={"title": "Model proposed coder"})
    payload = payload.model_copy(
        update={
            "plan": payload.plan.model_copy(
                update={"items": (payload.plan.items[0], actual, *payload.plan.items[2:])}
            )
        }
    )
    row = ManagementPlanRevision(
        company_id=admission.company_id,
        plan_id=admission.plan_id,
        plan_revision_id=UUID(int=7001),
        revision=2,
        goal_id=admission.goal.goal_id,
        goal_revision_id=admission.goal.revision_id,
        mandate_revision_id=admission.mandate.revision_id,
        sha256=canonical_sha256(payload),
        snapshot_json=payload.model_dump_json(),
        proposed_by=admission.procedure.binding.actor_id,
        recorded_at=datetime.now(UTC),
    )
    if fault == "native_title":
        actual = actual.model_copy(update={"title": "Other native title"})
    elif fault == "budget":
        actual = actual.model_copy(update={"budget_usd": Decimal(".2")})
    elif fault == "acceptance":
        actual = actual.model_copy(update={"acceptance": ("changed",)})
    requested = (payload.plan.items[0], actual, *payload.plan.items[2:]) if family else (actual,)
    approval = SimpleNamespace(
        owner_id=UUID(int=999) if fault == "wrong_owner" else admission.procedure.binding.actor_id
    )
    session = AsyncMock()
    session.scalars.side_effect = [
        MagicMock(all=lambda: (row,)),
        MagicMock(all=lambda: () if fault == "unapproved" else (approval,)),
    ]
    assert await stored_coding_profile(session, admission, works=tuple(requested)) is (
        fault is None
    )
    session.get.assert_not_awaited()  # No current head, Goal, lease or fresh execution lookup.


def reader(f: object) -> CycleModelReader:
    from types import SimpleNamespace

    assert isinstance(f, SimpleNamespace)
    return CycleModelReader(
        f.services.factory,
        f.services.management.catalog,
        f.services.evidence,
        coding=CodingCostSources(f.services),
    )


@pytest.mark.parametrize("status", ["response", "failed"])
async def test_real_header_and_model_file_confirm_original_native_money_without_fresh_c(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: Literal["response", "failed"],
) -> None:
    f = await coding_case(tmp_path, monkeypatch, status=status)
    model = reader(f)
    forbidden = AsyncMock(
        side_effect=AssertionError("financial read requested fresh C/SDK authority")
    )
    monkeypatch.setattr(type(f.services.identities), "current", forbidden)
    monkeypatch.setattr(type(f.services.resolver), "resolve", forbidden)
    # Execution admission is stopped; current-owner audit remains possible.
    f.services.request_stop()
    actual = cast(ProtectedBlobStore, f.services.prepared_blobs).read

    async def header_only(ref: object) -> bytes:
        assert ref == f.reference.header, "financial read disclosed the private input body"
        return await actual(f.reference.header)

    monkeypatch.setattr(f.services.prepared_blobs, "read", header_only)
    found = await model.read(
        f.scope, f.owner, f.selected.action.proposal.action_id, end_us=clock_us() + 20_000_000
    )
    assert found.fact is not None, found.blockers
    assert found.fact.billing == "known", found.fact.blockers
    assert found.fact.ledger_actual_usd == f.selected.hold.actual_usd
    assert found.fact.native_state == f.selected.intent.state
    assert found.proof is not None and found.proof.coding is not None
    assert "private generated result" not in found.fact.model_dump_json()
    assert str(tmp_path) not in found.fact.model_dump_json()
    assert not model.pending_owners()
    forbidden.assert_not_awaited()


async def test_unconfigured_c_stays_unconfirmed_and_does_not_open_private_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = await coding_case(tmp_path, monkeypatch)
    model = CycleModelReader(f.services.factory, f.services.management.catalog, f.services.evidence)
    private = AsyncMock(side_effect=AssertionError("unconfigured C read private record"))
    monkeypatch.setattr(f.services.evidence, "load", private)
    found = await model.read(
        f.scope, f.owner, f.selected.action.proposal.action_id, end_us=clock_us() + 10_000_000
    )
    assert found.fact is None and found.blockers == ("source_proof_unavailable",)
    private.assert_not_awaited()


async def test_source_denial_happens_before_header_or_model_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = await coding_case(tmp_path, monkeypatch)
    model = reader(f)
    private = AsyncMock(side_effect=AssertionError("source denial read private record"))
    monkeypatch.setattr(f.services.evidence, "load", private)
    monkeypatch.setattr(f.services.prepared_blobs, "read", private)
    f.state.revoked = True
    found = await model.read(
        f.scope, f.owner, f.selected.action.proposal.action_id, end_us=clock_us() + 10_000_000
    )
    assert found.fact is None
    private.assert_not_awaited()


async def test_final_family_cc_source_revocation_drops_private_fact_and_keeps_native_spend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.company.management import cycle_cost_snapshot as module

    f = await coding_case(tmp_path, monkeypatch)
    model = reader(f)
    snapshot = CycleCostSnapshotReader(model.factory, model.catalog, model)
    observed = FamilyCostCapture(
        observed_at=datetime.now(UTC),
        owner_id=f.owner.identity.principal_id,
        control_policy="p",
        control_prices="historical-price",
        control_paused=True,
        profile_bound=True,
        works=(f.selected.directory,),
        selections=(f.selected,),
        orphan_holds=(),
        blockers=(),
    )
    calls = 0

    async def capture(*args: object, **kwargs: object) -> FamilyCostCapture:
        nonlocal calls
        calls += 1
        if calls == 2:
            f.state.revoked = True
        return observed

    monkeypatch.setattr(snapshot, "_capture_locked", capture)
    monkeypatch.setattr(module, "management_owner_transaction", f.transaction)
    result = await snapshot.read(f.scope, f.owner, end_us=clock_us() + 20_000_000)
    assert result.value.totals.known_spent_usd == f.selected.hold.actual_usd
    assert result.value.charges[0].confirmation == "unconfirmed"
    assert result.value.charges[0].model_fact is None


async def test_copied_internal_source_proof_is_not_an_original_owned_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = await coding_case(tmp_path, monkeypatch)
    model = reader(f)
    found = await model.read(
        f.scope, f.owner, f.selected.action.proposal.action_id, end_us=clock_us() + 20_000_000
    )
    assert found.proof is not None and found.proof.coding is not None and model.coding is not None
    copied = replace(found.proof.coding)
    with pytest.raises(ValueError):
        model.coding.require_proof(copied, f.scope, f.owner, clock_us() + 10_000_000)


async def test_actual_blocked_model_read_remains_owned_after_caller_cancellation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = await coding_case(tmp_path, monkeypatch)
    model = reader(f)
    entered, finish = asyncio.Event(), asyncio.Event()
    original = f.services.evidence.load

    async def blocked(ref: ArtifactRef) -> ModelEvidence:
        entered.set()
        await finish.wait()
        return cast(ModelEvidence, await original(ref))

    monkeypatch.setattr(f.services.evidence, "load", blocked)
    task = asyncio.create_task(
        model.read(
            f.scope, f.owner, f.selected.action.proposal.action_id, end_us=clock_us() + 10_000_000
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert model.pending_owners()
    finally:
        finish.set()
        await asyncio.gather(*model.pending_owners(), return_exceptions=True)
    assert not model.pending_owners()


async def test_source_signature_changes_after_private_read_cannot_confirm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = await coding_case(tmp_path, monkeypatch)
    model = reader(f)
    original = f.services.evidence.load

    async def changed(ref: ArtifactRef) -> ModelEvidence:
        saved = await original(ref)
        f.state.signature = "e" * 64
        return cast(ModelEvidence, saved)

    monkeypatch.setattr(f.services.evidence, "load", changed)
    found = await model.read(
        f.scope, f.owner, f.selected.action.proposal.action_id, end_us=clock_us() + 10_000_000
    )
    assert found.fact is None and found.blockers == ("source_read_changed",)


async def test_crossed_native_receipt_is_denied_before_model_output_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from uuid import UUID

    f = await coding_case(tmp_path, monkeypatch)
    model = reader(f)
    receipt = f.selected.intent.receipt.model_copy(update={"receipt_id": UUID(int=9909)})
    intent = f.selected.intent.model_copy(update={"receipt": receipt})
    f.state.selected = f.selected.model_copy(update={"intent": intent})
    private = AsyncMock(side_effect=AssertionError("crossed receipt reached private model bytes"))
    monkeypatch.setattr(f.services.evidence, "load", private)
    found = await model.read(
        f.scope,
        f.owner,
        f.selected.action.proposal.action_id,
        end_us=clock_us() + 10_000_000,
    )
    assert found.fact is None
    private.assert_not_awaited()


async def test_original_source_deadline_bounds_actual_pending_model_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = await coding_case(tmp_path, monkeypatch)
    model = reader(f)
    entered, finish = asyncio.Event(), asyncio.Event()
    original = f.services.evidence.load

    async def blocked(ref: ArtifactRef) -> ModelEvidence:
        entered.set()
        await finish.wait()
        return cast(ModelEvidence, await original(ref))

    monkeypatch.setattr(f.services.evidence, "load", blocked)
    f.state.deadlines = (datetime.now(UTC) + timedelta(seconds=1),)
    try:
        with pytest.raises(TimeoutError):
            await model.read(
                f.scope,
                f.owner,
                f.selected.action.proposal.action_id,
                end_us=clock_us() + 10_000_000,
            )
        assert entered.is_set() and model.pending_owners()
    finally:
        finish.set()
        await asyncio.gather(*model.pending_owners(), return_exceptions=True)
    assert not model.pending_owners()


async def test_denied_old_store_cannot_block_a_new_legitimate_owner_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = await coding_case(tmp_path, monkeypatch)
    model = reader(f)
    f.state.revoked = True
    first = await model.read(
        f.scope,
        f.owner,
        f.selected.action.proposal.action_id,
        end_us=clock_us() + 10_000_000,
    )
    assert first.fact is None
    f.state.revoked = False  # Supplied current authority changes; no grant write occurs.
    second = await model.read(
        f.scope,
        f.owner,
        f.selected.action.proposal.action_id,
        end_us=clock_us() + 10_000_000,
    )
    assert second.fact is not None and second.fact.billing == "known"
    assert not model.pending_owners()

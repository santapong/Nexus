"""Direct real history gates preserve immutable refs and current READ/final dates."""

from datetime import datetime
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.scope_support import BrainConflictError, BrainDeniedError
from nexus.tests.historical_reference_probe_support import (
    direct_history_context,
    direct_qualifier,
    direct_reference,
    finite_historical_source_grant,
    forbid_blob_read,
    nominate_historical_final_clock,
    old_reference_case,
)
from nexus.tests.notification_worker_digest_loss_support import revoke_actual_source_read
from nexus.tests.notification_worker_tick_fixture import worker_tick_factory
from nexus.tests.notification_worker_tick_matrix_support import tick_ledger

__all__ = ["worker_tick_factory"]


async def test_current_default_rejects_old_reference_while_explicit_history_accepts(
    worker_tick_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = await old_reference_case(worker_tick_factory, tmp_path)
    forbid_blob_read(monkeypatch, case)
    before = await tick_ledger(worker_tick_factory)
    async with direct_history_context(case) as (session, actual, brain, witness):
        with pytest.raises(BrainConflictError):
            await direct_reference(case, session, actual, brain, witness, historical=False)
        assert await direct_reference(case, session, actual, brain, witness, historical=True)
        required, deadlines = await direct_qualifier(case, session, actual, brain, witness)
        assert required and deadlines
    assert await tick_ledger(worker_tick_factory) == before
    before.require_no_effects()


async def test_direct_history_and_obsolete_qualifier_deny_actual_source_read_revoke(
    worker_tick_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    case = await old_reference_case(worker_tick_factory, tmp_path)
    await revoke_actual_source_read(case)
    before = await tick_ledger(worker_tick_factory)
    async with direct_history_context(case) as (session, actual, brain, witness):
        with pytest.raises(BrainDeniedError):
            await direct_reference(case, session, actual, brain, witness, historical=True)
        with pytest.raises(BrainDeniedError):
            await direct_qualifier(case, session, actual, brain, witness)
    assert await tick_ledger(worker_tick_factory) == before
    before.require_no_effects()


@pytest.mark.parametrize("kind", ["sha", "length", "company", "id"])
async def test_exact_historical_reference_tamper_denies_with_original_positive_control(
    worker_tick_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    kind: str,
) -> None:
    case = await old_reference_case(worker_tick_factory, tmp_path)
    reference = case.baseline_references[0]
    change = (
        {"sha256": "f" * 64}
        if kind == "sha"
        else {"byte_length": reference.byte_length + 1}
        if kind == "length"
        else {"company_id": UUID(int=999)}
        if kind == "company"
        else {"artifact_revision_id": UUID(int=999)}
    )
    modified = reference.model_copy(update=change)
    before = await tick_ledger(worker_tick_factory)
    async with direct_history_context(case) as (session, actual, brain, witness):
        assert await direct_reference(case, session, actual, brain, witness, historical=True)
        error = BrainConflictError if kind in {"sha", "length"} else BrainDeniedError
        with pytest.raises(error):
            await direct_reference(
                case, session, actual, brain, witness, historical=True, reference=modified
            )
    assert await tick_ledger(worker_tick_factory) == before
    before.require_no_effects()


async def test_actual_historical_source_grant_expiry_at_last_method_clock_denies(
    worker_tick_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = await old_reference_case(worker_tick_factory, tmp_path)
    expires = await finite_historical_source_grant(case)
    before = await tick_ledger(worker_tick_factory)
    seen: list[tuple[datetime, datetime, int]] = []
    nominate_historical_final_clock(monkeypatch, case, expires, seen)
    async with direct_history_context(case) as (session, actual, brain, witness):
        with pytest.raises(BrainConflictError):
            await direct_reference(case, session, actual, brain, witness, historical=True)
    assert len(seen) == 1 and seen[0][0] < expires <= seen[0][1] and seen[0][2] == 3
    assert await tick_ledger(worker_tick_factory) == before
    before.require_no_effects()

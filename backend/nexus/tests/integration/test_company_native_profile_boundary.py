"""Final pending append crosses clocks but must never commit expired or partial preparation."""

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.harness.journal_models import JournalAction
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_management_acceptance import saved_m1
from nexus.tests.native_profile_support import configured_profile
from nexus.tests.native_profile_support import profile_factory as profile_factory


async def test_natural_profile_health_expiry_after_actual_pending_flush_rolls_back(
    profile_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = await configured_profile(profile_factory, tmp_path)
    profile = await case.preparation.resolve_profile(
        control(), identity(OWNER), case.report_id, case.commitment_id, case.evidence_ids
    )
    expiry = datetime.now(UTC) + timedelta(seconds=8)
    catalog = case.preparation.catalog
    models = tuple(
        row.model_copy(update={"health": row.health.model_copy(update={"expires_at": expiry})})
        for row in catalog.models.models
    )
    case.preparation.catalog = catalog.model_copy(
        update={"models": catalog.models.model_copy(update={"models": models})}
    )
    original = AsyncSession.flush
    reached = False

    async def delayed_flush(session: AsyncSession, objects: Sequence[object] | None = None) -> None:
        nonlocal reached
        pending = any(isinstance(row, JournalAction) for row in session.new)
        await original(session, objects=objects)
        if pending:
            reached = True
            await asyncio.sleep(max(0, (expiry - datetime.now(UTC)).total_seconds()) + 0.1)

    monkeypatch.setattr(AsyncSession, "flush", delayed_flush)
    before = await saved_m1(profile_factory)
    with pytest.raises(ValueError, match="evidence"):
        await case.preparation.prepare_author(profile.reference)
    assert reached and await saved_m1(profile_factory) == before
    async with profile_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.scalar(select(func.count()).select_from(JournalAction)) == 0


async def test_interruption_after_actual_pending_insert_leaves_no_partial_action(
    profile_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = await configured_profile(profile_factory, tmp_path)
    profile = await case.preparation.resolve_profile(
        control(), identity(OWNER), case.report_id, case.commitment_id, case.evidence_ids
    )
    original = AsyncSession.flush
    reached = False

    async def interrupted_flush(
        session: AsyncSession, objects: Sequence[object] | None = None
    ) -> None:
        nonlocal reached
        pending = any(isinstance(row, JournalAction) for row in session.new)
        await original(session, objects=objects)
        if pending:
            reached = True
            raise RuntimeError("Interrupted after native pending insert")

    monkeypatch.setattr(AsyncSession, "flush", interrupted_flush)
    before = await saved_m1(profile_factory)
    with pytest.raises(RuntimeError, match="Interrupted"):
        await case.preparation.prepare_author(profile.reference)
    assert reached and await saved_m1(profile_factory) == before
    async with profile_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.scalar(select(func.count()).select_from(JournalAction)) == 0

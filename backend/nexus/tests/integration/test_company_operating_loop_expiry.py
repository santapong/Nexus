"""Natural deadlines crossing actual native hold flush roll back consumption and cost."""

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.management.native_loop_store import NativeReportOperatingLoop
from nexus.harness.canonical import action_hash
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_models import CostHold, DailyBudget, JournalAction
from nexus.tests.generated_artifact_fixture import ledger
from nexus.tests.integration.test_company_brain_ingestion import RESOURCE, owner_scope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_management_acceptance import saved_m1
from nexus.tests.operating_loop_support import configured_loop, decide_existing
from nexus.tests.operating_loop_support import loop_factory as loop_factory


@pytest.mark.parametrize("deadline", ["approval", "source", "profile"])
async def test_real_hold_flush_crossing_current_deadline_leaves_no_consumption_or_cost(
    loop_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    deadline: str,
) -> None:
    loop, case = await configured_loop(loop_factory, tmp_path)
    author = case.payload.children[0].binding
    expiry = datetime.now(UTC) + timedelta(seconds=12)
    if deadline == "source":
        # Pin the legitimate expiring grant before proposal compilation so its
        # generation is part of the actual native input hash being approved.
        await ResourceAccessStore(loop_factory).change(
            owner_scope(),
            identity(OWNER),
            ResourceAccessChange(
                company_id=COMPANY,
                resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
                principal_id=author.actor_id,
                active=True,
                expires_at=expiry,
                expected_generation=2,
            ),
        )
        # The saved report intentionally pins resource generations. The fixture
        # explicitly saves a fresh owner snapshot before registering this occurrence;
        # the loop itself never generates a replacement report/configuration.
        original_profile = await case.preparation.resolve_profile(
            control(), identity(OWNER), case.report_id, case.commitment_id, case.evidence_ids
        )
        observed = datetime.now(UTC)
        saved = await case.native.producer.reports.save_snapshot(
            control(),
            identity(OWNER),
            original_profile.selection.plan.plan_revision_id,
            author.task_id,
            (),
            period_start=observed - timedelta(days=1),
            period_end=observed,
        )
        profile = await case.preparation.resolve_profile(
            control(), identity(OWNER), saved.report_id, case.commitment_id, case.evidence_ids
        )
        loop = NativeReportOperatingLoop(
            loop.registration.model_copy(update={"profile": profile.reference}),
            case.preparation,
            case.native,
        )
    pending = await loop.tick(control(), identity(OWNER))
    assert pending.pending is not None
    if deadline != "source":
        expiry = datetime.now(UTC) + timedelta(seconds=10)
    if deadline == "approval":
        # Actual immutable public owner decision, dated within its allowed24h window;
        # no approval-row expiry rewrite or frozen clock is used.
        await CompanyJournal(loop_factory).approve_registered(
            ledger(author).model_copy(update={"principal_id": OWNER}),
            pending.pending.proposal.action_id,
            action_hash(pending.pending.proposal),
            expiry - timedelta(hours=24),
            identity=identity(OWNER),
        )
    else:
        await decide_existing(loop_factory, pending.pending)
        if deadline == "profile":
            catalog = case.native.publisher.catalog
            models = tuple(
                row.model_copy(
                    update={"health": row.health.model_copy(update={"expires_at": expiry})}
                )
                for row in catalog.models.models
            )
            case.native.publisher.catalog = catalog.model_copy(
                update={"models": catalog.models.model_copy(update={"models": models})}
            )
    original = AsyncSession.flush
    reached = False

    async def late_hold(session: AsyncSession, objects: Sequence[object] | None = None) -> None:
        nonlocal reached
        inserting = any(isinstance(row, CostHold) for row in session.new)
        await original(session, objects=objects)
        if inserting:
            reached = True
            await asyncio.sleep(max(0, (expiry - datetime.now(UTC)).total_seconds()) + 0.1)

    monkeypatch.setattr(AsyncSession, "flush", late_hold)
    before = await saved_m1(loop_factory)
    denied = await loop.tick(control(), identity(OWNER))
    assert reached and denied.state == "blocked" and denied.scheduled is None
    assert await saved_m1(loop_factory) == before
    async with loop_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.scalar(select(func.count()).select_from(CostHold)) == 0
        row = await session.get(JournalAction, pending.pending.proposal.action_id)
        assert row and row.consumed_at is None and row.state == "awaiting_approval"
        assert not await session.scalar(select(func.count()).select_from(DailyBudget))

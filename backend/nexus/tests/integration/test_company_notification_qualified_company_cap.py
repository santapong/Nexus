"""Actual native company/day cap preserves subject/date and known unissued holds in draft JSON."""

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.native_fact_contracts import CapSelector
from nexus.company.brain.native_fact_emitter import NativeFactEmitter
from nexus.tests.integration.test_company_brain_ingestion import owner_scope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_native_fact_company_cap import _hold_one
from nexus.tests.native_fact_fixture import facts_factory as facts_factory
from nexus.tests.qualified_notification_fixture import configured_qualified


async def test_actual_five_native_holds_publish_company_day_budget_subject(
    facts_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    store, _, _ = await configured_qualified(facts_factory, tmp_path)
    for _ in range(5):
        await _hold_one(facts_factory)
    event = await NativeFactEmitter(facts_factory, store.loader.reader).emit(
        owner_scope(), identity(OWNER), CapSelector(company_id=COMPANY)
    )
    assert event is not None
    draft = await store.publish_event(control(), identity(OWNER), event.event_id)
    assert draft.signal.subject_id == COMPANY and draft.signal.budget_day == event.budget_day
    assert "Billing: known" in draft.payload.text and "Held USD: 5.000000" in draft.payload.text
    assert await store.get_current(control(), identity(OWNER), draft.draft_id) == draft

"""Actual native new-kind facts to immutable qualified owner drafts with zero M1 effects."""

from pathlib import Path
from typing import Literal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.native_fact_contracts import DecisionSelector, DigestSelector
from nexus.company.brain.native_fact_emitter import NativeFactEmitter
from nexus.tests.integration.test_company_brain_ingestion import owner_scope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_management_acceptance import saved_m1
from nexus.tests.native_fact_fixture import facts_factory as facts_factory
from nexus.tests.qualified_notification_fixture import configured_qualified


async def test_actual_pending_decision_publishes_and_coalesces_owner_draft_without_effect(
    facts_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    store, case, _ = await configured_qualified(facts_factory, tmp_path)
    profile = await case.preparation.resolve_profile(
        control(), identity(OWNER), case.report_id, case.commitment_id, case.evidence_ids
    )
    pending = await case.preparation.prepare_author(profile.reference)
    event = await NativeFactEmitter(facts_factory, store.loader.reader).emit(
        owner_scope(),
        identity(OWNER),
        DecisionSelector(company_id=COMPANY, action_id=pending.action.proposal.action_id),
    )
    assert event is not None
    before = await saved_m1(facts_factory)
    result = await store.publish_event_result(control(), identity(OWNER), event.event_id)
    assert result.state == "published" and result.draft is not None
    draft = result.draft
    assert draft.kind == "routine" and draft.signal.kind == "decision_required"
    assert draft.signal.subject_id == pending.action.proposal.action_id
    assert "decision" in draft.payload.subject.lower() and "unknown" in draft.payload.text
    repeat = await store.publish_event_result(control(), identity(OWNER), event.event_id)
    assert repeat.state == "coalesced" and repeat.draft == draft
    assert await store.get_current(control(), identity(OWNER), draft.draft_id) == draft
    assert await saved_m1(facts_factory) == before
    store.policy = store.policy.model_copy(update={"template_version": "changed-owner-plain.v2"})
    with pytest.raises(ValueError, match="policy"):
        await store.get_current(control(), identity(OWNER), draft.draft_id)


@pytest.mark.parametrize("kind", ["daily", "weekly"])
async def test_actual_report_digest_uses_original_projection_and_registered_bucket(
    facts_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    kind: Literal["daily", "weekly"],
) -> None:
    store, _, _ = await configured_qualified(facts_factory, tmp_path, digest_kind=kind)
    event = await NativeFactEmitter(facts_factory, store.loader.reader).emit(
        owner_scope(),
        identity(OWNER),
        DigestSelector(company_id=COMPANY, schedule=f"qualified-{kind}-v1"),
    )
    if event is None:
        pytest.skip("Actual clock is before the registered09:00 digest bucket")
    before = await saved_m1(facts_factory)
    result = await store.publish_event_result(control(), identity(OWNER), event.event_id)
    assert result.draft is not None and result.draft.kind == kind
    draft = result.draft
    assert (draft.due_bucket, draft.scheduled_for) == (event.due_bucket, event.scheduled_for)
    assert draft.signal.digest is not None and draft.signal.digest.report_id == event.report_id
    assert (
        kind in draft.payload.subject.lower() and "goal completed" not in draft.payload.text.lower()
    )
    assert await store.get_current(control(), identity(OWNER), draft.draft_id) == draft
    assert await saved_m1(facts_factory) == before

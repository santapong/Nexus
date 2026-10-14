"""Natural current deadlines crossing the real outbox append roll back native publication."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Unpack
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.brain.access_models import BrainResource
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.event_models import BrainEvent
from nexus.company.brain.event_store import append_event
from nexus.company.brain.events import EventKind, OutboxEvent
from nexus.company.brain.native_fact_contracts import (
    DecisionSelector,
    DigestSelector,
    RegisteredDigestPolicy,
)
from nexus.company.brain.native_fact_digest import digest_window
from nexus.company.brain.native_fact_emitter import NativeFactEmitter
from nexus.company.brain.native_fact_reader import NativeFactReader
from nexus.company.brain.native_fact_services import NativeFactServices
from nexus.company.brain.native_fact_wake import WakePins
from nexus.company.brain.scope_support import brain_transaction
from nexus.company.notifications.contracts import NotificationPolicy
from nexus.tests.integration.test_company_brain_ingestion import RESOURCE, owner_scope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_management_acceptance import saved_m1
from nexus.tests.native_fact_fixture import configured_facts
from nexus.tests.native_fact_fixture import facts_factory as facts_factory


@pytest.mark.parametrize("deadline", ["owner_grant", "actor_grant", "profile", "digest_policy"])
async def test_natural_expiry_after_actual_event_insert_rolls_back_without_work_cost_change(
    facts_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    deadline: str,
) -> None:
    services, case = await configured_facts(facts_factory, tmp_path)
    profile = await case.preparation.resolve_profile(
        control(), identity(OWNER), case.report_id, case.commitment_id, case.evidence_ids
    )
    pending = await case.preparation.prepare_author(profile.reference)
    selector = DecisionSelector(company_id=COMPANY, action_id=pending.action.proposal.action_id)
    expiry = datetime.now(UTC) + timedelta(seconds=4)
    if deadline in {"owner_grant", "actor_grant"}:
        async with brain_transaction(facts_factory, owner_scope(), identity(OWNER), owner=True) as (
            session,
            _,
            _,
        ):
            row = await session.get(BrainResource, (COMPANY, RESOURCE))
            assert row is not None
            generation = row.acl_generation
        await ResourceAccessStore(facts_factory).change(
            owner_scope(),
            identity(OWNER),
            ResourceAccessChange(
                company_id=COMPANY,
                resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
                principal_id=OWNER
                if deadline == "owner_grant"
                else case.payload.children[0].binding.actor_id,
                active=True,
                expires_at=expiry,
                expected_generation=generation,
            ),
        )
    elif deadline == "profile":
        services = _short_profile(services, expiry)
    else:
        if digest_window("weekly", datetime.now(UTC)) is None:
            pytest.skip("Real Monday clock is before the registered09:00 weekly bucket")
        registration = RegisteredDigestPolicy(
            company_id=COMPANY,
            schedule="timed-digest-v1",
            kind="weekly",
            report_id=case.report_id,
            resource=services.resource,
            policy=NotificationPolicy(enabled=True, weekly_digest=True),
            registered_at=datetime.now(UTC) - timedelta(minutes=1),
            expires_at=expiry,
        )
        services = replace(services, digests=(registration,))
    emitter = NativeFactEmitter(facts_factory, NativeFactReader(services))
    actual_selector = (
        DigestSelector(company_id=COMPANY, schedule="timed-digest-v1")
        if deadline == "digest_policy"
        else selector
    )
    from nexus.company.brain import native_fact_emitter

    original = append_event
    reached = False

    async def expired_append(
        session: AsyncSession,
        scope: BrainReadScope,
        *,
        kind: EventKind,
        resource_id: UUID,
        deduplication_key: str,
        now: datetime,
        **pins: Unpack[WakePins],
    ) -> OutboxEvent:
        nonlocal reached
        event = await original(
            session,
            scope,
            kind=kind,
            resource_id=resource_id,
            deduplication_key=deduplication_key,
            now=now,
            **pins,
        )
        assert datetime.now(UTC) < expiry
        reached = True
        await asyncio.sleep((expiry - datetime.now(UTC)).total_seconds() + 0.03)
        return event

    monkeypatch.setattr(native_fact_emitter, "append_event", expired_append)
    before = await saved_m1(facts_factory)
    with pytest.raises(ValueError):
        await emitter.emit(owner_scope(), identity(OWNER), actual_selector)
    assert reached and await saved_m1(facts_factory) == before
    async with facts_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert not await session.scalar(
            select(func.count())
            .select_from(BrainEvent)
            .where(BrainEvent.kind.in_(("decision_required", "digest_due")))
        )


def _short_profile(services: NativeFactServices, expiry: datetime) -> NativeFactServices:
    catalog = services.catalog
    models = tuple(
        row.model_copy(update={"health": row.health.model_copy(update={"expires_at": expiry})})
        for row in catalog.models.models
    )
    current = catalog.model_copy(
        update={"models": catalog.models.model_copy(update={"models": models})}
    )
    return replace(
        services, catalog=current, scheduler=replace(services.scheduler, catalog=current)
    )

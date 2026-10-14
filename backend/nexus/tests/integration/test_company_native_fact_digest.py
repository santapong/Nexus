"""Registered native report digests use exact policy/09:00 buckets and original observed facts."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.native_fact_contracts import (
    DigestSelector,
    DigestState,
    RegisteredDigestPolicy,
)
from nexus.company.brain.native_fact_digest import digest_window
from nexus.company.brain.native_fact_emitter import NativeFactEmitter
from nexus.company.brain.native_fact_reader import NativeFactReader
from nexus.company.brain.scope_support import brain_transaction
from nexus.company.notifications.contracts import NotificationPolicy
from nexus.execution.runtime_support import db_now
from nexus.tests.integration.test_company_brain_ingestion import owner_scope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_management_acceptance import saved_m1
from nexus.tests.native_fact_fixture import configured_facts
from nexus.tests.native_fact_fixture import facts_factory as facts_factory


@pytest.mark.parametrize("kind", ["daily", "weekly"])
async def test_registered_owner_report_digest_coalesces_exact_bucket_and_policy(
    facts_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    kind: Literal["daily", "weekly"],
) -> None:
    services, case = await configured_facts(facts_factory, tmp_path)
    now = datetime.now(UTC)
    registration = RegisteredDigestPolicy(
        company_id=COMPANY,
        schedule=f"actual-{kind}-v1",
        kind=kind,
        report_id=case.report_id,
        policy=NotificationPolicy(
            enabled=True, daily_digest=kind == "daily", weekly_digest=kind == "weekly"
        ),
        resource=services.resource,
        registered_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
    )
    reader = NativeFactReader(replace(services, digests=(registration,)))
    emitter = NativeFactEmitter(facts_factory, reader)
    selector = DigestSelector(company_id=COMPANY, schedule=registration.schedule)
    before = await saved_m1(facts_factory)
    async with brain_transaction(facts_factory, owner_scope(), identity(OWNER), owner=True) as (
        session,
        cc,
        _,
    ):
        window = digest_window(kind, await db_now(session))
    event = await emitter.emit(owner_scope(), identity(OWNER), selector)
    if window is None:
        assert event is None  # Real clock before09; pure alternate-clock window tests are separate.
        return
    assert event is not None and (event.due_bucket, event.scheduled_for) == window
    assert await emitter.emit(owner_scope(), identity(OWNER), selector) == event
    async with brain_transaction(facts_factory, owner_scope(), identity(OWNER), owner=True) as (
        session,
        cc,
        _,
    ):
        fact = await reader.load_event_locked(session, cc, owner_scope(), identity(OWNER), event)
        assert fact is not None and isinstance(fact.state, DigestState)
        assert fact.source_recorded_at == fact.state.saved.observed_at
        assert (
            fact.source_event.precision == "instant"
            and fact.source_event.value == fact.state.saved.observed_at.isoformat()
        )
        assert (
            fact.artifacts
            and fact.required_resource_ids == fact.state.saved.data.required_resource_ids
        )
    # A policy-version change produces a different explicit registered occurrence.
    revised = registration.model_copy(
        update={"policy": registration.policy.model_copy(update={"version": "owner-notify.v2"})}
    )
    newer = await NativeFactEmitter(
        facts_factory, NativeFactReader(replace(services, digests=(revised,)))
    ).emit(owner_scope(), identity(OWNER), selector)
    assert newer is not None and newer.event_id != event.event_id
    assert await saved_m1(facts_factory) == before


@pytest.mark.parametrize("case_name", ["unregistered", "expired", "disabled"])
async def test_digest_missing_expired_or_disabled_policy_never_invents_occurrence(
    facts_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    case_name: str,
) -> None:
    services, case = await configured_facts(facts_factory, tmp_path)
    now = datetime.now(UTC)
    registration = RegisteredDigestPolicy(
        company_id=COMPANY,
        schedule="explicit-daily-v1",
        kind="daily",
        report_id=case.report_id,
        policy=NotificationPolicy(enabled=case_name != "disabled", daily_digest=True),
        resource=services.resource,
        registered_at=now - timedelta(hours=1),
        expires_at=now - timedelta(seconds=1)
        if case_name == "expired"
        else now + timedelta(hours=1),
    )
    emitter = NativeFactEmitter(
        facts_factory,
        NativeFactReader(
            replace(services, digests=() if case_name == "unregistered" else (registration,))
        ),
    )
    selector = DigestSelector(company_id=COMPANY, schedule=registration.schedule)
    if case_name == "disabled":
        assert await emitter.emit(owner_scope(), identity(OWNER), selector) is None
    else:
        with pytest.raises(ValueError, match="schedule"):
            await emitter.emit(owner_scope(), identity(OWNER), selector)

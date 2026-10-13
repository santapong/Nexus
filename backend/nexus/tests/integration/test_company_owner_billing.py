"""Known receipts retain byte identity while independent billing evidence resolves holds."""

from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.company.directory_contracts import MembershipChange
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.execution.billing_contracts import BillingLookupRequest, BillingObservation
from nexus.execution.billing_models import BillingEvidence
from nexus.execution.owner_reconcile_store import OwnerReconciliationStore
from nexus.execution.runtime_contracts import ExecutionDeniedError
from nexus.execution.runtime_models import EffectIntent
from nexus.harness.journal_models import CompanyControl, CostHold, DailyBudget, WorkBudget
from nexus.settings import settings
from nexus.tests.integration.company_billing_fixture import (
    known_unknown_bill,
)
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER, TASK, control
from nexus.tests.integration.test_company_execution_store import identity, migrate, scope
from nexus.tests.integration.test_company_owner_reconciliation import FixtureResolver, expire


@pytest.fixture
async def billing_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_owner_billing"
    admin = create_async_engine(url)
    app = create_async_engine(url.set(username="nexus_company_app"))
    migrated = False
    try:
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "upgrade")
        migrated = True
        yield async_sessionmaker(app, expire_on_commit=False)
    finally:
        await app.dispose()
        if migrated:
            async with admin.begin() as connection:
                await connection.run_sync(migrate, "downgrade")
        await admin.dispose()


@pytest.mark.parametrize("outcome", ["succeeded", "failed"])
@pytest.mark.parametrize("amount", ["0.000000", "0.075000"])
async def test_known_receipt_and_business_state_unchanged_while_bill_moves_once(
    billing_factory: async_sessionmaker[AsyncSession], tmp_path: Path, outcome: str, amount: str
) -> None:
    execution, proposal, resolver = await known_unknown_bill(
        billing_factory, tmp_path, amount, outcome=outcome
    )
    await PersistentCompanyDirectory(billing_factory).set_membership(
        MembershipChange(
            company_id=COMPANY, principal_id=ACTOR, role="member", membership_active=False
        ),
        control(),
    )
    await expire()
    before = await execution.get(scope(principal=OWNER), identity(OWNER))
    owner = OwnerReconciliationStore(billing_factory, FixtureResolver(), billing_resolver=resolver)
    original = await receipt_bytes(billing_factory, proposal.action_id)
    lease = await owner.claim_billing(
        control(), identity(OWNER), TASK, UUID(int=601), proposal.action_id
    )
    assert await receipt_bytes(billing_factory, proposal.action_id) == original
    result = await owner.resolve_billing(lease, identity(OWNER))
    assert result is not None and result.actual_usd == Decimal(amount)
    assert await receipt_bytes(billing_factory, proposal.action_id) == original
    assert await owner.resolve_billing(lease, identity(OWNER)) == result
    released = await owner.release_billing(lease, identity(OWNER))
    assert released.state == before.state and released.counters == before.counters
    async with billing_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        held = await session.get(CostHold, proposal.action_id)
        budget = await session.get(WorkBudget, (COMPANY, TASK))
        assert (
            held is not None and held.state == "reconciled" and held.actual_usd == Decimal(amount)
        )
        assert budget is not None and budget.held_usd == 0 and budget.spent_usd == Decimal(amount)
        daily = await session.get(DailyBudget, (COMPANY, held.day))
        assert daily is not None and daily.held_usd == 0 and daily.spent_usd == Decimal(amount)
        assert await session.scalar(select(func.count()).select_from(BillingEvidence)) == 1


async def receipt_bytes(factory: async_sessionmaker[AsyncSession], action_id: UUID) -> str:
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        effect = await session.get(EffectIntent, (COMPANY, action_id))
        assert effect is not None and effect.receipt_json is not None
        return effect.receipt_json


async def test_missing_billing_resolver_cannot_release_known_unknown_hold(
    billing_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    _, proposal, _ = await known_unknown_bill(billing_factory, tmp_path, "0.000000")
    await expire()
    with pytest.raises(ExecutionDeniedError):
        await OwnerReconciliationStore(billing_factory, FixtureResolver()).claim_billing(
            control(), identity(OWNER), TASK, UUID(int=601), proposal.action_id
        )


async def assert_unresolved(
    factory: async_sessionmaker[AsyncSession], action_id: UUID, original: str
) -> None:
    assert await receipt_bytes(factory, action_id) == original
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        held = await session.get(CostHold, action_id)
        assert held is not None and held.state == "unknown" and held.actual_usd is None
        assert await session.scalar(select(func.count()).select_from(BillingEvidence)) == 0


@pytest.mark.parametrize("corruption", ["missing", "changed_bytes", "current_acl", "current_hash"])
async def test_unverified_or_revoked_proof_retains_unknown_bill_and_receipt(
    billing_factory: async_sessionmaker[AsyncSession], tmp_path: Path, corruption: str
) -> None:
    _, proposal, resolver = await known_unknown_bill(billing_factory, tmp_path, "0.000000")
    await expire()
    owner = OwnerReconciliationStore(billing_factory, FixtureResolver(), billing_resolver=resolver)
    owned = await owner.claim_billing(
        control(), identity(OWNER), TASK, UUID(int=601), proposal.action_id
    )
    original = await receipt_bytes(billing_factory, proposal.action_id)
    if corruption == "missing":
        resolver.path.unlink()
    elif corruption == "changed_bytes":
        resolver.path.write_bytes(b"synthetic damaged source")
    elif corruption == "current_acl":
        resolver.allowed_principals = ()
    else:
        resolver.current_proof_hash = "f" * 64
    assert await owner.resolve_billing(owned, identity(OWNER)) is None
    await assert_unresolved(billing_factory, proposal.action_id, original)


async def test_historical_invoice_survives_pause_new_prices_and_immutable_evidence_guard(
    billing_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    execution, proposal, resolver = await known_unknown_bill(billing_factory, tmp_path, "0.075000")
    async with billing_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        await session.execute(
            update(CompanyControl).values(paused=True, price_version="later-price")
        )
    await expire()
    owner = OwnerReconciliationStore(billing_factory, FixtureResolver(), billing_resolver=resolver)
    owned = await owner.claim_billing(
        control(), identity(OWNER), TASK, UUID(int=601), proposal.action_id
    )
    first = await owner.resolve_billing(owned, identity(OWNER))
    assert first is not None and first.observation.price_version == proposal.price_version
    assert (await execution.get(scope(principal=OWNER), identity(OWNER))).state == "verifying"
    with pytest.raises(DBAPIError):
        async with billing_factory() as session, session.begin():
            await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
            await session.execute(update(BillingEvidence).values(actual_usd=Decimal("0.09")))
    async with billing_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(UUID(int=900)), True)))
        assert await session.scalar(select(func.count()).select_from(BillingEvidence)) == 0


@pytest.mark.parametrize("changed", ["acl", "hash"])
async def test_source_access_or_hash_revocation_after_read_denies_commit(
    billing_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    changed: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, proposal, resolver = await known_unknown_bill(billing_factory, tmp_path, "0.075000")
    await expire()
    original_resolve = resolver.resolve

    async def revoke_source(request: BillingLookupRequest) -> BillingObservation | None:
        result = await original_resolve(request)
        if changed == "acl":
            resolver.allowed_principals = ()
        else:
            resolver.current_proof_hash = "f" * 64
        return result

    monkeypatch.setattr(resolver, "resolve", revoke_source)
    owner = OwnerReconciliationStore(billing_factory, FixtureResolver(), billing_resolver=resolver)
    owned = await owner.claim_billing(
        control(), identity(OWNER), TASK, UUID(int=601), proposal.action_id
    )
    original = await receipt_bytes(billing_factory, proposal.action_id)
    with pytest.raises(ExecutionDeniedError):
        await owner.resolve_billing(owned, identity(OWNER))
    await assert_unresolved(billing_factory, proposal.action_id, original)


@pytest.mark.parametrize("changed", ["actual_usd", "price_version", "receipt_hash"])
async def test_explicit_conflicting_recheck_cannot_change_amount_or_provenance(
    billing_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    changed: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, proposal, resolver = await known_unknown_bill(billing_factory, tmp_path, "0.075000")
    await expire()
    owner = OwnerReconciliationStore(billing_factory, FixtureResolver(), billing_resolver=resolver)
    owned = await owner.claim_billing(
        control(), identity(OWNER), TASK, UUID(int=601), proposal.action_id
    )
    first = await owner.resolve_billing(owned, identity(OWNER))
    assert first is not None
    original_resolve = resolver.resolve

    async def conflicting(request: BillingLookupRequest) -> BillingObservation:
        result = await original_resolve(request)
        assert result is not None
        update = {
            "actual_usd": Decimal("0.09"),
            "price_version": "changed",
            "receipt_hash": "f" * 64,
        }
        return type(result).model_validate(result.model_dump() | {changed: update[changed]})

    monkeypatch.setattr(resolver, "resolve", conflicting)
    with pytest.raises(ExecutionDeniedError):
        await owner.resolve_billing(owned, identity(OWNER))
    async with billing_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        row = await session.get(BillingEvidence, (COMPANY, proposal.action_id))
        hold = await session.get(CostHold, proposal.action_id)
        assert row is not None and row.observation_hash == first.observation_hash
        assert hold is not None and hold.actual_usd == Decimal("0.075000")


async def test_billing_denies_live_takeover_wrong_identity_and_stale_fence(
    billing_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    _, proposal, resolver = await known_unknown_bill(billing_factory, tmp_path, "0.075000")
    owner = OwnerReconciliationStore(billing_factory, FixtureResolver(), billing_resolver=resolver)
    with pytest.raises(ExecutionDeniedError):
        await owner.claim_billing(
            control(), identity(OWNER), TASK, UUID(int=601), proposal.action_id
        )
    await expire()
    old = await owner.claim_billing(
        control(), identity(OWNER), TASK, UUID(int=601), proposal.action_id
    )
    with pytest.raises(ExecutionDeniedError):
        await owner.resolve_billing(old, identity())
    await expire()
    new = await owner.claim_billing(
        control(), identity(OWNER), TASK, UUID(int=602), proposal.action_id
    )
    assert new.execution.fence > old.execution.fence
    with pytest.raises(ExecutionDeniedError):
        await owner.resolve_billing(old, identity(OWNER))
    renewed = await owner.renew_billing(new, identity(OWNER))
    assert renewed.execution.fence == new.execution.fence


async def test_owner_revocation_during_unlocked_billing_lookup_denies_commit(
    billing_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, proposal, resolver = await known_unknown_bill(billing_factory, tmp_path, "0.075000")
    await expire()
    original_resolve = resolver.resolve

    async def revoke_owner(request: BillingLookupRequest) -> BillingObservation | None:
        result = await original_resolve(request)
        await PersistentCompanyDirectory(billing_factory).set_membership(
            MembershipChange(
                company_id=COMPANY, principal_id=OWNER, role="owner", membership_active=False
            ),
            control(),
        )
        return result

    monkeypatch.setattr(resolver, "resolve", revoke_owner)
    owner = OwnerReconciliationStore(billing_factory, FixtureResolver(), billing_resolver=resolver)
    owned = await owner.claim_billing(
        control(), identity(OWNER), TASK, UUID(int=601), proposal.action_id
    )
    original = await receipt_bytes(billing_factory, proposal.action_id)
    with pytest.raises(ExecutionDeniedError):
        await owner.resolve_billing(owned, identity(OWNER))
    await assert_unresolved(billing_factory, proposal.action_id, original)

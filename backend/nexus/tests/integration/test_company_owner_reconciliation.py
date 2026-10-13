"""Separate current-owner reconciliation never recreates actor authority or allowance."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.directory_contracts import MembershipChange
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.execution.effect_store import EffectStore
from nexus.execution.owner_reconcile_contracts import (
    ReconciliationObservation,
    ReconciliationRequest,
)
from nexus.execution.owner_reconcile_store import OwnerReconciliationStore
from nexus.execution.runtime_contracts import ExecutionDeniedError, ExecutionLease
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt, ExecutionWork
from nexus.execution.runtime_store import ExecutionStore
from nexus.harness.journal_models import CompanyControl, CostHold, JournalAction
from nexus.settings import settings
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER, TASK, control
from nexus.tests.integration.test_company_execution_store import (
    WORKER,
    action,
    identity,
    migrate,
    ready,
    receipt,
    scope,
)


@pytest.fixture
async def owner_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_owner_reconcile"
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


async def expire() -> None:
    admin = create_async_engine(settings.company_test_database_url)
    try:
        async with admin.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE company_execution_work "
                    "SET lease_until=clock_timestamp()-interval '1 second'"
                )
            )
    finally:
        await admin.dispose()


class FixtureResolver:
    """Trusted offline composition fixture; no HTTP/user proof or provider call exists."""

    def __init__(self, *, verified: bool = True) -> None:
        self.verified = verified

    async def resolve(self, request: ReconciliationRequest) -> ReconciliationObservation | None:
        if not self.verified:
            return None
        proof = ArtifactRef(
            company_id=COMPANY,
            artifact_id=UUID(int=501),
            reference="offline-source:verified-lookup",
            sha256="a" * 64,
            revision="fixture-v1",
            allowed_principals=(OWNER,),
        )
        return ReconciliationObservation(
            company_id=COMPANY,
            receipt=receipt(request.proposal),
            actual_usd=Decimal("0.00"),
            proof=proof,
        )


async def issued(
    factory: async_sessionmaker[AsyncSession],
) -> tuple[ExecutionStore, EffectStore, ActionProposal, ExecutionLease]:
    execution, effects = await ready(factory)
    proposal = await action(factory)
    lease = await execution.claim(scope(), identity(), WORKER)
    await effects.begin(lease, identity(), proposal.action_id)
    return execution, effects, proposal, lease


async def test_owner_resolves_issued_evidence_after_actor_revocation_without_new_allowance(
    owner_factory: async_sessionmaker[AsyncSession],
) -> None:
    execution, effects, proposal, actor_lease = await issued(owner_factory)
    directory = PersistentCompanyDirectory(owner_factory)
    await directory.set_membership(
        MembershipChange(
            company_id=COMPANY, principal_id=ACTOR, role="member", membership_active=False
        ),
        control(),
    )
    await expire()
    owner = OwnerReconciliationStore(owner_factory, FixtureResolver())
    owned = await owner.claim(control(), identity(OWNER), TASK, UUID(int=502))
    assert owned.execution.actor_id == ACTOR and owned.control_scope.principal_id == OWNER
    assert owned.execution.fence > actor_lease.fence
    result = await owner.resolve(owned, identity(OWNER), proposal.action_id)
    assert result is not None and result.state == "succeeded"
    assert result.receipt is not None and len(result.receipt.artifacts) >= 2
    current = await execution.get(scope(principal=OWNER), identity(OWNER))
    assert current.counters.tool_attempts == 1 and current.state == "verifying"
    assert current.lease_principal_id == OWNER
    async with owner_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        held = await session.get(CostHold, proposal.action_id)
        assert held is not None and held.state == "reconciled" and held.actual_usd == 0
    await directory.set_membership(
        MembershipChange(
            company_id=COMPANY, principal_id=ACTOR, role="member", membership_active=True
        ),
        control(),
    )
    with pytest.raises(ExecutionDeniedError):
        await effects.record_receipt(owned.execution, identity(), receipt(proposal))
    with pytest.raises(ExecutionDeniedError):
        await execution.reserve_attempt(
            owned.execution, identity(), "model_requests", UUID(int=505)
        )
    with pytest.raises(ExecutionDeniedError):
        await execution.claim(
            scope(),
            identity(),
            owned.execution.worker_id,
            reconcile_only=True,
            segment_id=owned.execution.segment_id,
        )


async def test_live_actor_lease_denies_owner_takeover(
    owner_factory: async_sessionmaker[AsyncSession],
) -> None:
    await issued(owner_factory)
    with pytest.raises(ExecutionDeniedError):
        await OwnerReconciliationStore(owner_factory, FixtureResolver()).claim(
            control(), identity(OWNER), TASK, UUID(int=502)
        )


async def test_unverified_lookup_preserves_unknown_outcome_and_held_cost(
    owner_factory: async_sessionmaker[AsyncSession],
) -> None:
    execution, _, proposal, _ = await issued(owner_factory)
    await expire()
    owner = OwnerReconciliationStore(owner_factory, FixtureResolver(verified=False))
    owned = await owner.claim(control(), identity(OWNER), TASK, UUID(int=502))
    assert await owner.resolve(owned, identity(OWNER), proposal.action_id) is None
    current = await execution.get(scope(principal=OWNER), identity(OWNER))
    assert current.state == "outcome_unknown" and current.counters.tool_attempts == 1
    async with owner_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        held = await session.get(CostHold, proposal.action_id)
        assert held is not None and held.state == "unknown" and held.amount_usd > 0


async def test_owner_revocation_during_unlocked_lookup_denies_commit(
    owner_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, _, proposal, _ = await issued(owner_factory)
    await expire()

    class RevokingResolver(FixtureResolver):
        async def resolve(self, request: ReconciliationRequest) -> ReconciliationObservation | None:
            await PersistentCompanyDirectory(owner_factory).set_membership(
                MembershipChange(
                    company_id=COMPANY, principal_id=OWNER, role="owner", membership_active=False
                ),
                control(),
            )
            return await super().resolve(request)

    owner = OwnerReconciliationStore(owner_factory, RevokingResolver())
    owned = await owner.claim(control(), identity(OWNER), TASK, UUID(int=502))
    with pytest.raises(ExecutionDeniedError):
        await owner.resolve(owned, identity(OWNER), proposal.action_id)


async def test_blocked_release_is_persistent_without_intent_or_new_authority(
    owner_factory: async_sessionmaker[AsyncSession],
) -> None:
    execution, _ = await ready(owner_factory)
    lease = await execution.claim(scope(), identity(), WORKER)
    blocked = await execution.release(lease, identity(), blocked=True)
    assert blocked.state == "blocked" and blocked.worker_id is None
    with pytest.raises(ExecutionDeniedError):
        await execution.claim(scope(), identity(), WORKER)
    with pytest.raises(ExecutionDeniedError):
        await OwnerReconciliationStore(owner_factory, FixtureResolver()).claim(
            control(), identity(OWNER), TASK, UUID(int=502)
        )


async def test_before_intent_denial_rolls_back_attempt_intent_and_hold_changes(
    owner_factory: async_sessionmaker[AsyncSession],
) -> None:
    execution, effects = await ready(owner_factory)
    proposal = await action(owner_factory)
    lease = await execution.claim(scope(), identity(), WORKER)
    before = await execution.get(scope(), identity())

    class DenyingDatabaseCheck:
        called = False

        async def validate(
            self,
            session: AsyncSession,
            control: CompanyControl,
            work: ExecutionWork,
            action: JournalAction,
            now: datetime,
        ) -> None:
            self.called = True
            assert control.company_id == work.company_id == action.company_id == COMPANY
            assert now.utcoffset() is not None and work.lease_principal_id == ACTOR
            assert await session.get(CostHold, action.id) is not None
            raise ExecutionDeniedError("Fresh database model gate denied")

    check = DenyingDatabaseCheck()
    with pytest.raises(ExecutionDeniedError):
        await effects.begin(lease, identity(), proposal.action_id, before_intent=check)
    assert check.called and await execution.get(scope(), identity()) == before
    async with owner_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.scalar(select(func.count()).select_from(EffectIntent)) == 0
        assert await session.scalar(select(func.count()).select_from(ExecutionAttempt)) == 0
        held = await session.get(CostHold, proposal.action_id)
        assert held is not None and held.state == "held" and held.actual_usd is None
        assert held.amount_usd == proposal.estimated_cost_usd
    first = await effects.begin(lease, identity(), proposal.action_id)
    check.called = False
    cached = await effects.begin(lease, identity(), proposal.action_id, before_intent=check)
    assert first.permit_external_call and not cached.permit_external_call and not check.called


async def test_unknown_intent_takes_precedence_over_blocked_release(
    owner_factory: async_sessionmaker[AsyncSession],
) -> None:
    execution, _, proposal, lease = await issued(owner_factory)
    unknown = await execution.release(lease, identity(), blocked=True)
    assert unknown.state == "outcome_unknown" and unknown.lease_principal_id is None
    assert unknown.counters.tool_attempts == 1
    async with owner_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        effect = await session.get(EffectIntent, (COMPANY, proposal.action_id))
        held = await session.get(CostHold, proposal.action_id)
        assert effect is not None and effect.receipt_json is None
        assert held is not None and held.state == "unknown" and held.amount_usd > 0


@pytest.mark.parametrize("invalid", ["receipt_hash", "proof_access"])
async def test_unbound_or_inaccessible_observation_cannot_resolve_or_refund(
    owner_factory: async_sessionmaker[AsyncSession], invalid: str
) -> None:
    execution, _, proposal, _ = await issued(owner_factory)
    await expire()

    class InvalidResolver(FixtureResolver):
        async def resolve(self, request: ReconciliationRequest) -> ReconciliationObservation:
            observed = await super().resolve(request)
            assert observed is not None
            value = observed.model_dump()
            if invalid == "receipt_hash":
                value["receipt"]["proposal_hash"] = "f" * 64
            else:
                value["proof"]["allowed_principals"] = (ACTOR,)
            return ReconciliationObservation.model_validate(value)

    owner = OwnerReconciliationStore(owner_factory, InvalidResolver())
    owned = await owner.claim(control(), identity(OWNER), TASK, UUID(int=502))
    with pytest.raises(ExecutionDeniedError):
        await owner.resolve(owned, identity(OWNER), proposal.action_id)
    current = await execution.get(scope(principal=OWNER), identity(OWNER))
    assert current.state == "outcome_unknown" and current.counters.tool_attempts == 1
    async with owner_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        effect = await session.get(EffectIntent, (COMPANY, proposal.action_id))
        held = await session.get(CostHold, proposal.action_id)
        assert effect is not None and effect.receipt_json is None
        assert held is not None and held.state == "unknown" and held.actual_usd is None


async def test_only_current_owner_fence_can_renew_release_or_resolve(
    owner_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, effects, proposal, _ = await issued(owner_factory)
    await expire()
    owner = OwnerReconciliationStore(owner_factory, FixtureResolver())
    with pytest.raises(ExecutionDeniedError):
        await owner.claim(control(ACTOR), identity(), TASK, UUID(int=502))
    old = await owner.claim(control(), identity(OWNER), TASK, UUID(int=502))
    renewed = await owner.renew(old, identity(OWNER))
    assert renewed.execution.fence == old.execution.fence
    with pytest.raises(ExecutionDeniedError):
        await effects.begin(renewed.execution, identity(OWNER), proposal.action_id)
    await expire()
    new = await owner.claim(control(), identity(OWNER), TASK, UUID(int=503))
    assert new.execution.fence > old.execution.fence
    for method in (owner.renew, owner.release):
        with pytest.raises(ExecutionDeniedError):
            await method(old, identity(OWNER))
    with pytest.raises(ExecutionDeniedError):
        await owner.resolve(old, identity(OWNER), proposal.action_id)
    result = await owner.resolve(new, identity(OWNER), proposal.action_id)
    assert result is not None and result.state == "succeeded"
    released = await owner.release(new, identity(OWNER))
    assert released.state == "verifying" and released.lease_principal_id is None


async def test_bounded_timeout_cancels_lookup_and_retains_unknown_receipt_and_billing(
    owner_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, _, proposal, _ = await issued(owner_factory)
    await expire()

    class SlowResolver(FixtureResolver):
        cancelled = False

        async def resolve(self, request: ReconciliationRequest) -> ReconciliationObservation | None:
            try:
                await asyncio.sleep(5)
                return await super().resolve(request)
            finally:
                self.cancelled = True

    resolver = SlowResolver()
    owner = OwnerReconciliationStore(owner_factory, resolver, timeout_seconds=1)
    owned = await owner.claim(control(), identity(OWNER), TASK, UUID(int=502))
    assert await owner.resolve(owned, identity(OWNER), proposal.action_id) is None
    assert resolver.cancelled
    async with owner_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        effect = await session.get(EffectIntent, (COMPANY, proposal.action_id))
        held = await session.get(CostHold, proposal.action_id)
        assert (
            effect is not None and effect.state == "outcome_unknown" and effect.receipt_json is None
        )
        assert held is not None and held.state == "unknown" and held.actual_usd is None


async def test_known_receipt_reuse_needs_no_new_lookup_and_cannot_become_business_completion(
    owner_factory: async_sessionmaker[AsyncSession],
) -> None:
    execution, _, proposal, _ = await issued(owner_factory)
    await expire()

    class CountingResolver(FixtureResolver):
        calls = 0

        async def resolve(self, request: ReconciliationRequest) -> ReconciliationObservation | None:
            self.calls += 1
            return await super().resolve(request)

    resolver = CountingResolver()
    owner = OwnerReconciliationStore(owner_factory, resolver)
    owned = await owner.claim(control(), identity(OWNER), TASK, UUID(int=502))
    first = await owner.resolve(owned, identity(OWNER), proposal.action_id)
    assert await owner.resolve(owned, identity(OWNER), proposal.action_id) == first
    assert resolver.calls == 1 and first is not None and first.verification is None
    current = await execution.get(scope(principal=OWNER), identity(OWNER))
    assert current.state == "verifying" and current.counters.tool_attempts == 1

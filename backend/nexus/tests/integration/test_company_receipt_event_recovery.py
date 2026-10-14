"""Issued outcomes remain recordable after admission/source revoke without new permits."""

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.brain.access_models import BrainResource
from nexus.company.brain.event_models import BrainEvent
from nexus.company.control_store import CompanyControls
from nexus.company.management.transactions import management_owner_transaction
from nexus.company.notifications.receipt_event_publisher import NativeReceiptEventPublisher
from nexus.execution.runtime_support import lease_scope, runtime_transaction
from nexus.tests.generated_artifact_fixture import generated_scenario
from nexus.tests.integration.test_company_brain_ingestion import RESOURCE, owner_scope
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.receipt_atomic_support import failed_receipt, managed_effects
from nexus.tests.receipt_event_support import receipt_factory as receipt_factory


@pytest.mark.parametrize("condition", ["source_revoked", "paused"])
async def test_already_issued_failed_receipt_preserves_outcome_under_revoke_or_pause(
    receipt_factory: async_sessionmaker[AsyncSession], tmp_path: Path, condition: str
) -> None:
    # Keep the51-line issued/revoke/record/replay sequence together; splitting the
    # admission change from terminal recording could hide an accidental new permit.
    item = await generated_scenario(receipt_factory, tmp_path, production=True)
    lease = item.lease
    before = await item.execution.get(lease_scope(lease), identity(ACTOR))
    if condition == "source_revoked":
        async with management_owner_transaction(receipt_factory, control(), identity(OWNER)) as (
            session,
            _,
            _,
        ):
            resource = await session.get(BrainResource, (COMPANY, RESOURCE))
            assert resource is not None
            generation = resource.acl_generation
        await ResourceAccessStore(receipt_factory).change(
            owner_scope(),
            identity(OWNER),
            ResourceAccessChange(
                company_id=COMPANY,
                resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
                principal_id=ACTOR,
                active=False,
                expected_generation=generation,
            ),
        )
    else:
        await CompanyControls(receipt_factory).set_paused_registered(
            control(), identity(OWNER), True
        )
    effects = managed_effects(
        receipt_factory, item, NativeReceiptEventPublisher(item.plans.catalog)
    )
    receipt = failed_receipt(item)
    first = await effects.record_receipt(lease, identity(ACTOR), receipt, actual_usd=None)
    assert first.state == "failed" and first.receipt == receipt
    assert await effects.record_receipt(lease, identity(ACTOR), receipt, actual_usd=None) == first
    async with runtime_transaction(
        receipt_factory, lease_scope(lease), identity(ACTOR), allow_paused=True, allow_inactive=True
    ) as (session, _, _):
        assert (
            await session.scalar(
                select(func.count())
                .select_from(BrainEvent)
                .where(BrainEvent.kind == "receipt_recorded")
            )
            == 1
        )
    assert (
        await item.execution.get(lease_scope(lease), identity(ACTOR))
    ).counters == before.counters


@pytest.mark.parametrize("outcome", ["succeeded", "outcome_unknown"])
async def test_nonfailed_receipt_does_not_create_a_failed_action_wake(
    receipt_factory: async_sessionmaker[AsyncSession], tmp_path: Path, outcome: str
) -> None:
    item = await generated_scenario(receipt_factory, tmp_path, production=True)
    receipt = failed_receipt(item).model_copy(update={"outcome": outcome})
    effects = managed_effects(
        receipt_factory, item, NativeReceiptEventPublisher(item.plans.catalog)
    )
    record = await effects.record_receipt(item.lease, identity(ACTOR), receipt, actual_usd=None)
    assert record.state == outcome
    async with runtime_transaction(receipt_factory, lease_scope(item.lease), identity(ACTOR)) as (
        session,
        _,
        _,
    ):
        assert (
            await session.scalar(
                select(func.count())
                .select_from(BrainEvent)
                .where(BrainEvent.kind == "receipt_recorded")
            )
            == 0
        )

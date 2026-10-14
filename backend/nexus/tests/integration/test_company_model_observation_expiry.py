"""Actual committed native sender intent cannot use expired replacement eligibility."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.base import BrainReadScope
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.model_observations import ModelEligibilityObservation
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.company.notifications.managed_admission import ManagedNotificationAdmission
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.execution.runtime_support import lease_scope, runtime_transaction
from nexus.harness.journal_models import CompanyControl
from nexus.settings import settings
from nexus.tests.integration.test_company_directory import OWNER, migrate
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.notification_managed_execution import (
    approved_sender,
    configure_catalog,
    mock_dispatch,
)
from nexus.tests.notification_managed_fixture import configured_sender


@pytest.fixture
async def observation_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Normal015 restricted app, explicitly exclusive disposable observation database."""
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_notification_review"
    admin = create_async_engine(url)
    app = create_async_engine(url.set(username="nexus_company_app"))
    async with admin.begin() as connection:
        await connection.run_sync(migrate, "upgrade")
    try:
        yield async_sessionmaker(app, expire_on_commit=False)
    finally:
        await app.dispose()
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "downgrade")
        await admin.dispose()


async def test_current_observation_expiry_after_intent_keeps_unknown_without_post(
    observation_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Keep this >50-line real intent/expiry scenario together for boundary review.
    case = await configured_sender(observation_factory, tmp_path)
    original = case.plans.catalog
    now = datetime.now(UTC)
    observations = tuple(
        ModelEligibilityObservation(
            company_id=original.company_id,
            observation_id=uuid4(),
            registry_revision=original.models.revision,
            registry_id=model.registry_id,
            registration_sha256=canonical_sha256(model),
            receipt_sha256="7" * 64,
            health=model.health.model_copy(
                update={"checked_at": now, "expires_at": now + timedelta(seconds=8)}
            ),
            evaluations=model.evaluations,
        )
        for model in original.models.models
    )
    catalog = PlanAdmissionCatalog.model_validate(
        original.model_dump() | {"model_observations": observations}
    )
    assert catalog.models == original.models
    case = configure_catalog(observation_factory, case, catalog)
    prepared, lease = await approved_sender(observation_factory, case)
    original_admit = case.effects.preparation.admit
    seen = False

    async def admit(
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        actor: VerifiedIdentity,
        work: ExecutionWork,
        draft_id: UUID,
        action: ActionProposal,
    ) -> ManagedNotificationAdmission:
        nonlocal seen
        result = await original_admit(session, control, scope, actor, work, draft_id, action)
        # Original registry remains healthy; current observation crosses its deadline.
        row = await session.get(
            EffectIntent, (lease.company_id, prepared.action.proposal.action_id)
        )
        if row is not None and row.state == "intent":
            seen = True
            for _ in range(8):
                await session.execute(select(func.pg_sleep(1.1)))
        return result

    monkeypatch.setattr(case.effects.preparation, "admit", admit)
    calls: list[str] = []
    service = mock_dispatch(observation_factory, case, calls)
    with pytest.raises(ValueError):
        await service.dispatch(
            lease, identity(OWNER), case.selection.draft_id, prepared.action.proposal.action_id
        )
    assert seen and calls == []
    async with runtime_transaction(observation_factory, lease_scope(lease), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        intent = await session.get(
            EffectIntent, (lease.company_id, prepared.action.proposal.action_id)
        )
        assert intent is not None and intent.state == "intent" and intent.receipt_json is None

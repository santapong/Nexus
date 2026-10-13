"""Acceptance/proof/event rollback and immutable invalidation preserve all M1 facts."""

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.management import acceptance_store
from nexus.company.management.acceptance_models import (
    ManagementAcceptanceInvalidation,
    ManagementAcceptanceProof,
    ManagementWorkAcceptance,
)
from nexus.tests.integration.management_acceptance_fixture import (
    acceptance_factory as acceptance_factory,
)
from nexus.tests.integration.management_acceptance_fixture import (
    configured_acceptance,
    issue_accepted_report_fixture,
)
from nexus.tests.integration.management_acceptance_report_fixture import bindings
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_management_acceptance import saved_m1
from nexus.tests.integration.test_company_management_acceptance_denials import no_acceptance


async def test_event_failure_rolls_back_acceptance_and_proof(
    acceptance_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = await configured_acceptance(acceptance_factory, tmp_path)
    verifier = bindings(scenario.payload)[2]
    before = await saved_m1(acceptance_factory)

    async def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("Controlled outbox rollback probe")

    monkeypatch.setattr(acceptance_store, "append_event", fail)
    with pytest.raises(RuntimeError, match="Controlled outbox"):
        await scenario.store.publish_verified_result(
            scenario.verifier_lease,
            identity(verifier.actor_id),
            action_id=scenario.action_id,
            protected_result=scenario.protected_result,
        )
    await no_acceptance(acceptance_factory)
    async with acceptance_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert (
            await session.scalar(select(func.count()).select_from(ManagementAcceptanceProof)) == 0
        )
    assert await saved_m1(acceptance_factory) == before


async def test_invalidation_is_separate_exact_history_without_proof_or_receipt_rewrite(
    acceptance_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    scenario, record = await issue_accepted_report_fixture(acceptance_factory, tmp_path)
    before = await saved_m1(acceptance_factory)
    result = await scenario.store.invalidate(
        control(), identity(OWNER), record.acceptance_id, "source_changed"
    )
    assert (
        await scenario.store.invalidate(
            control(), identity(OWNER), record.acceptance_id, "source_changed"
        )
        == result
    )
    assert await saved_m1(acceptance_factory) == before
    async with acceptance_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        row = await session.get(ManagementWorkAcceptance, (COMPANY, record.acceptance_id))
        assert row is not None and row.result_json == record.model_dump_json()
        assert (
            await session.scalar(select(func.count()).select_from(ManagementAcceptanceProof)) == 1
        )
        assert (
            await session.scalar(select(func.count()).select_from(ManagementAcceptanceInvalidation))
            == 1
        )
    with pytest.raises(ValueError):
        await scenario.store.invalidate(
            control(record.target.verifier.actor_id),
            identity(record.target.verifier.actor_id),
            record.acceptance_id,
            "invalid_check",
        )


async def test_acceptance_rows_are_append_only_and_company_scoped(
    acceptance_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    _, record = await issue_accepted_report_fixture(acceptance_factory, tmp_path)
    with pytest.raises(DBAPIError):
        async with acceptance_factory() as session, session.begin():
            await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
            await session.execute(update(ManagementWorkAcceptance).values(verdict="reject"))
    async with acceptance_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(uuid4()), True)))
        assert await session.get(ManagementWorkAcceptance, (COMPANY, record.acceptance_id)) is None

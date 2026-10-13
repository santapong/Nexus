"""Independent exact replay must retain final lease/grant validity after awaited lookup."""

from collections.abc import Awaitable, Callable
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.management.acceptance_models import ManagementWorkAcceptance
from nexus.tests.integration.management_acceptance_fixture import (
    acceptance_factory as acceptance_factory,
)
from nexus.tests.integration.management_acceptance_fixture import issue_accepted_report_fixture
from nexus.tests.integration.test_company_brain_ingestion import RESOURCE, owner_scope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER
from nexus.tests.integration.test_company_execution_store import identity


async def test_exact_replay_rechecks_input_grant_after_awaited_existing_record_lookup(
    acceptance_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario, record = await issue_accepted_report_fixture(acceptance_factory, tmp_path)
    verifier = scenario.payload.children[1].binding
    async with acceptance_factory() as session:
        now = await session.scalar(select(func.clock_timestamp()))
    assert now is not None
    generation = next(
        row.generation for row in scenario.inputs.source.contributors if row.resource_id == RESOURCE
    )
    await ResourceAccessStore(acceptance_factory).change(
        owner_scope(),
        identity(OWNER),
        ResourceAccessChange(
            company_id=COMPANY,
            resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
            principal_id=verifier.actor_id,
            active=True,
            expected_generation=generation,
            expires_at=now + timedelta(seconds=8),
        ),
    )
    original_get = cast(
        Callable[..., Awaitable[Any]], AsyncSession.get
    )  # SQLAlchemy overloaded lookup retains the exact result.

    async def delayed_get(
        self: AsyncSession, entity: object, ident: object, **kwargs: Any
    ) -> object:
        # SQLAlchemy has an overloaded untyped call surface; native API result is unchanged.
        result = await original_get(self, entity, ident, **kwargs)
        if entity is ManagementWorkAcceptance and result is not None:
            await self.execute(select(func.pg_sleep(8.3)))
        return result

    monkeypatch.setattr(AsyncSession, "get", delayed_get)
    with pytest.raises(ValueError):
        await scenario.store.publish_verified_result(
            scenario.verifier_lease,
            identity(verifier.actor_id),
            action_id=scenario.action_id,
            protected_result=scenario.protected_result,
        )
    # Replay did not mint another outcome; the original immutable accepted history remains.
    async with acceptance_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.scalar(select(func.count()).select_from(ManagementWorkAcceptance)) == 1
        saved = await original_get(
            session, ManagementWorkAcceptance, (COMPANY, record.acceptance_id)
        )
        assert saved is not None and saved.result_json == record.model_dump_json()

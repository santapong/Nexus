"""Current-owner races and actual issued unknown facts survive permanent stop and resume."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from litestar.testing import AsyncTestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import PrincipalAccess, VerifiedIdentity
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.contracts.results import ActionReceipt
from nexus.company.directory_contracts import MembershipChange
from nexus.company.management.cancellation_models import WorkCancellation
from nexus.execution.effect_store import EffectStore
from nexus.execution.runtime_store import ExecutionStore
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CostHold
from nexus.tests.generated_artifact_fixture import ledger
from nexus.tests.integration.test_company_api import headers
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_management_acceptance import saved_m1
from nexus.tests.integration.test_company_management_control_api import BASE, intent
from nexus.tests.management_control_api_support import configured_control_api
from nexus.tests.management_control_api_support import control_api_factory as control_api_factory
from nexus.tests.management_plan_support import authorized_action, registered_freshness


async def test_issued_unknown_receipt_cost_and_lifetime_counter_survive_http_stop_and_resume(
    control_api_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    scenario = await configured_control_api(control_api_factory, tmp_path)
    target = scenario.payload.children[0].binding
    artifacts = BoundedArtifactReader(
        control_api_factory, ProtectedBlobStore(tmp_path, storage_symbol="fixture.blobs.v1")
    )
    freshness = registered_freshness(control_api_factory)
    execution = ExecutionStore(
        control_api_factory,
        management_catalog=scenario.plans.catalog,
        management_artifacts=artifacts,
        management_freshness=freshness,
    )
    effects = EffectStore(
        control_api_factory,
        management_catalog=scenario.plans.catalog,
        management_artifacts=artifacts,
        management_freshness=freshness,
    )
    lease = await execution.claim(ledger(target), identity(target.actor_id), uuid4())
    action = await authorized_action(control_api_factory, target)
    await effects.begin(lease, identity(target.actor_id), action.action_id)
    receipt = ActionReceipt(
        company_id=COMPANY,
        receipt_id=uuid4(),
        action_id=action.action_id,
        task_id=target.task_id,
        trace_id=target.trace_id,
        proposal_hash=action_hash(action),
        outcome="outcome_unknown",
        recorded_at=datetime.now(UTC),
    )
    await effects.record_receipt(lease, identity(target.actor_id), receipt, actual_usd=None)
    before = await saved_m1(control_api_factory)
    async with AsyncTestClient(scenario.app) as client:
        paused = await client.post(
            f"/api/v2/companies/{COMPANY}/pause", headers=headers(OWNER), json={"paused": True}
        )
        assert paused.status_code == 200
        stopped = await client.post(
            BASE + f"/work/{target.task_id}/cancel",
            headers=headers(OWNER),
            json=intent(target).model_dump(mode="json"),
        )
        assert stopped.status_code == 200, stopped.text
        resumed = await client.post(
            f"/api/v2/companies/{COMPANY}/pause", headers=headers(OWNER), json={"paused": False}
        )
        assert resumed.status_code == 200
    assert await saved_m1(control_api_factory) == before
    current = await execution.get(ledger(target), identity(target.actor_id))
    assert current.counters.tool_attempts == 1 and current.state == "outcome_unknown"
    async with control_api_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        hold = await session.get(CostHold, action.action_id)
        assert hold is not None and hold.state == "unknown" and hold.actual_usd is None
        assert hold.amount_usd == Decimal("0.03")


async def test_owner_revoked_after_actual_gateway_lookup_cannot_append_stop(
    control_api_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = await configured_control_api(control_api_factory, tmp_path)
    original = scenario.directory.lookup_principal

    async def revoke_after_lookup(
        signed: VerifiedIdentity, *, task_id: UUID, trace_id: UUID
    ) -> PrincipalAccess | None:
        result = await original(signed, task_id=task_id, trace_id=trace_id)
        await scenario.directory.set_membership(
            MembershipChange(
                company_id=COMPANY, principal_id=OWNER, role="owner", membership_active=False
            ),
            control(),
        )
        return result

    monkeypatch.setattr(scenario.directory, "lookup_principal", revoke_after_lookup)
    target = scenario.payload.children[0].binding
    before = await saved_m1(control_api_factory)
    async with AsyncTestClient(scenario.app) as client:
        response = await client.post(
            BASE + f"/work/{target.task_id}/cancel",
            headers=headers(OWNER),
            json=intent(target).model_dump(mode="json"),
        )
        assert response.status_code == 403, response.text
    assert await saved_m1(control_api_factory) == before
    async with control_api_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.scalar(select(func.count()).select_from(WorkCancellation)) == 0

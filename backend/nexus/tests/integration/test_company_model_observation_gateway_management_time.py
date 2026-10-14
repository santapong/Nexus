"""Exact own/sibling plan grant expiry after actual final closure read blocks the SDK."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx2
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.brain.access_models import BrainResource
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.harness import model_managed_deadlines
from nexus.harness.journal_models import CostHold
from nexus.harness.model_managed_inputs import ManagedModelInputs
from nexus.tests.integration.test_company_brain_ingestion import RESOURCE, owner_scope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.management_plan_support import VERIFIER
from nexus.tests.model_observation_gateway_fixture import (
    observed_gateway,
)
from nexus.tests.model_observation_gateway_fixture import (
    observed_gateway_factory as observed_gateway_factory,
)
from nexus.tests.unit.test_company_provider_conformance import response


@pytest.mark.parametrize("principal", ["own", "sibling"])
async def test_management_only_exact_grant_deadline_at_last_closure_await_denies_paid_call(
    observed_gateway_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    principal: str,
) -> None:
    wires: list[httpx2.Request] = []

    def handle(wire: httpx2.Request) -> httpx2.Response:
        wires.append(wire)
        return httpx2.Response(200, json=response("openai"))

    case = await observed_gateway(observed_gateway_factory, tmp_path, httpx2.MockTransport(handle))
    expiry = datetime.now(UTC) + timedelta(seconds=10)
    async with observed_gateway_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        resource = await session.get(BrainResource, (COMPANY, RESOURCE))
        assert resource is not None
        generation = resource.acl_generation
    await ResourceAccessStore(observed_gateway_factory).change(
        owner_scope(),
        identity(OWNER),
        ResourceAccessChange(
            company_id=COMPANY,
            resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
            principal_id=case.lease.actor_id if principal == "own" else VERIFIER,
            active=True,
            expires_at=expiry,
            expected_generation=generation,
        ),
    )
    original = model_managed_deadlines.capture_plan_deadlines
    reached = False

    async def delayed_capture(
        session: AsyncSession,
        work: ExecutionWork,
        actual: ManagedModelInputs,
    ) -> tuple[datetime, ...]:
        nonlocal reached
        deadlines = await original(session, work, actual)
        assert expiry in deadlines and datetime.now(UTC) < expiry
        reached = True
        await asyncio.sleep((expiry - datetime.now(UTC)).total_seconds() + 0.04)
        return deadlines

    monkeypatch.setattr(model_managed_deadlines, "capture_plan_deadlines", delayed_capture)
    result = await case.client.request_once(case.call, now=datetime.now(UTC))
    assert reached and not wires and result.provider_result.billing == "unknown"
    assert result.recorded is not None and result.recorded.billing == "unknown"
    async with observed_gateway_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        work = await session.get(ExecutionWork, (COMPANY, case.call.task_id))
        intent = await session.get(EffectIntent, (COMPANY, case.call.action_id))
        hold = await session.get(CostHold, case.call.action_id)
        assert work and intent and hold
        assert work.model_requests_used == 1 and intent.state == "outcome_unknown"
        assert intent.receipt_json is None and hold.state == "unknown" and hold.actual_usd is None

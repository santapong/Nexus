"""An already-issued actual SDK response stays recordable after its observation window closes."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import httpx2
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.harness.journal_models import CostHold
from nexus.tests.model_observation_gateway_fixture import (
    observed_gateway,
)
from nexus.tests.model_observation_gateway_fixture import (
    observed_gateway_factory as observed_gateway_factory,
)
from nexus.tests.unit.test_company_provider_conformance import response


async def test_issued_known_result_evidence_receipt_and_cost_survive_observation_expiry(
    observed_gateway_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    wires: list[httpx2.Request] = []
    deadline: datetime | None = None

    async def handle(wire: httpx2.Request) -> httpx2.Response:
        assert deadline is not None and datetime.now(UTC) < deadline
        wires.append(wire)
        await asyncio.sleep((deadline - datetime.now(UTC)).total_seconds() + 0.04)
        return httpx2.Response(200, json=response("openai"))

    case = await observed_gateway(
        observed_gateway_factory, tmp_path, httpx2.MockTransport(handle), expires_seconds=15
    )
    deadline = case.observation.health.expires_at
    result = await case.client.request_once(case.call, now=datetime.now(UTC))
    assert (
        len(wires) == 1
        and result.provider_result.billing == "known"
        and result.recorded is not None
    )
    assert result.recorded.billing == "known" and result.recorded.actual_usd is not None
    evidence = await case.evidence.load(result.recorded.artifact)
    assert evidence.checked_at >= deadline and evidence.source_event_at < deadline
    assert evidence.model == case.registry.models[0] and evidence.eligibility_provenance is not None
    assert evidence.eligibility_provenance.observation == case.observation
    async with observed_gateway_factory() as session, session.begin():
        await session.execute(
            select(func.set_config("nexus.company_id", str(case.call.company_id), True))
        )
        work = await session.get(ExecutionWork, (case.call.company_id, case.call.task_id))
        intent = await session.get(EffectIntent, (case.call.company_id, case.call.action_id))
        hold = await session.get(CostHold, case.call.action_id)
        assert work and intent and hold
        assert work.model_requests_used == 1 and work.tool_attempts_used == 0
        assert intent.state == "succeeded" and intent.receipt_json is not None
        assert hold.state == "reconciled" and hold.actual_usd == result.recorded.actual_usd

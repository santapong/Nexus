"""One actual managed SDK mock request uses fresh observation without changing original work."""

from datetime import UTC, datetime
from pathlib import Path

import httpx2
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.management.canonical import canonical_sha256
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.harness.journal_models import CostHold, WorkBudget
from nexus.tests.model_observation_gateway_fixture import (
    observed_gateway,
)
from nexus.tests.model_observation_gateway_fixture import (
    observed_gateway_factory as observed_gateway_factory,
)
from nexus.tests.unit.test_company_provider_conformance import response


@pytest.mark.parametrize("outcome", ["known", "unknown"])
async def test_observed_managed_sdk_preserves_original_registration_and_native_receipt_cost(
    observed_gateway_factory: async_sessionmaker[AsyncSession], tmp_path: Path, outcome: str
) -> None:
    wires: list[httpx2.Request] = []

    def handle(wire: httpx2.Request) -> httpx2.Response:
        wires.append(wire)
        if outcome == "unknown":
            raise httpx2.ReadTimeout("fixture-only", request=wire)
        return httpx2.Response(200, json=response("openai"))

    case = await observed_gateway(observed_gateway_factory, tmp_path, httpx2.MockTransport(handle))
    original = case.registry.model_dump()
    assert case.registry.models[0].health.expires_at < datetime.now(UTC)
    async with observed_gateway_factory() as session, session.begin():
        await session.execute(
            select(func.set_config("nexus.company_id", str(case.call.company_id), True))
        )
        work = await session.get(ExecutionWork, (case.call.company_id, case.call.task_id))
        assert work is not None
        registration = work.registration_hash
    result = await case.client.request_once(case.call, now=datetime.now(UTC))
    assert len(wires) == 1 and result.recorded is not None, result
    assert result.recorded.billing == outcome
    evidence = await case.evidence.load(result.recorded.artifact)
    assert evidence.model == case.registry.models[0] and case.registry.model_dump() == original
    assert evidence.eligibility_provenance is not None
    assert evidence.eligibility_provenance.observation == case.observation
    assert evidence.eligibility_provenance.registration_sha256 == canonical_sha256(evidence.model)
    async with observed_gateway_factory() as session, session.begin():
        await session.execute(
            select(func.set_config("nexus.company_id", str(case.call.company_id), True))
        )
        work = await session.get(ExecutionWork, (case.call.company_id, case.call.task_id))
        intent = await session.get(EffectIntent, (case.call.company_id, case.call.action_id))
        hold = await session.get(CostHold, case.call.action_id)
        budget = await session.get(WorkBudget, (case.call.company_id, case.call.task_id))
        assert work and intent and hold and budget
        assert (
            work.registration_hash == registration
            and work.model_registry_version == case.registry.revision
        )
        assert work.model_requests_used == 1 and work.tool_attempts_used == 0
        if outcome == "known":
            assert intent.state == "succeeded" and intent.receipt_json is not None
            assert hold.state == "reconciled" and result.recorded.actual_usd == budget.spent_usd
        else:
            assert intent.state == "outcome_unknown" and intent.receipt_json is None
            assert (
                hold.state == "unknown"
                and budget.spent_usd == 0
                and budget.held_usd == hold.amount_usd
            )
    repeat = await case.client.request_once(case.call, now=datetime.now(UTC))
    assert repeat.provider_result.billing == "not_issued" and len(wires) == 1

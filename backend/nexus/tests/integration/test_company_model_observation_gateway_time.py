"""Natural observation expiry at actual intent flush and pre-SDK setup preserves accounting."""

import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import httpx2
import pytest
from pydantic_ai.models import Model
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.core.llm import company_adapters
from nexus.core.llm.company_adapter_contracts import ServerEndpoint
from nexus.core.llm.company_adapter_sdk import sdk_model
from nexus.core.llm.company_registry import ModelRegistration
from nexus.core.llm.company_wire_usage import WireObserver
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.harness.journal_models import CostHold, WorkBudget
from nexus.tests.model_observation_gateway_fixture import (
    observed_gateway,
)
from nexus.tests.model_observation_gateway_fixture import (
    observed_gateway_factory as observed_gateway_factory,
)
from nexus.tests.unit.test_company_provider_conformance import response


@pytest.mark.parametrize("phase", ["intent_flush", "sdk_setup"])
async def test_natural_observation_expiry_never_issues_sdk_and_preserves_consumed_or_unissued_state(
    observed_gateway_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    wires: list[httpx2.Request] = []

    def handle(wire: httpx2.Request) -> httpx2.Response:
        wires.append(wire)
        return httpx2.Response(200, json=response("openai"))

    case = await observed_gateway(
        observed_gateway_factory, tmp_path, httpx2.MockTransport(handle), expires_seconds=15
    )
    expiry = case.observation.health.expires_at
    reached = False
    original_flush, original_sdk = AsyncSession.flush, sdk_model

    async def wait_for_expiry() -> None:
        nonlocal reached
        assert datetime.now(UTC) < expiry
        reached = True
        await asyncio.sleep((expiry - datetime.now(UTC)).total_seconds() + 0.04)

    async def delayed_flush(session: AsyncSession, objects: Sequence[object] | None = None) -> None:
        target = any(
            isinstance(row, EffectIntent) and row.action_id == case.call.action_id
            for row in session.new
        )
        await original_flush(session, objects=objects)
        if target and phase == "intent_flush":
            await wait_for_expiry()

    @asynccontextmanager
    async def delayed_sdk(
        model: ModelRegistration,
        endpoint: ServerEndpoint,
        observer: WireObserver,
    ) -> AsyncIterator[Model]:
        async with original_sdk(model, endpoint, observer) as sdk:
            if phase == "sdk_setup":
                await wait_for_expiry()
            yield sdk

    monkeypatch.setattr(AsyncSession, "flush", delayed_flush)
    monkeypatch.setattr(company_adapters, "sdk_model", delayed_sdk)
    result = await case.client.request_once(case.call, now=datetime.now(UTC))
    assert reached and not wires
    if phase == "intent_flush":
        assert result.provider_result.billing == "not_issued" and result.recorded is None
    else:
        assert result.provider_result.billing == "unknown" and result.recorded is not None
        evidence = await case.evidence.load(result.recorded.artifact)
        assert evidence.checked_at >= expiry and evidence.eligibility_provenance is not None
        assert evidence.model == case.registry.models[0]
    async with observed_gateway_factory() as session, session.begin():
        await session.execute(
            select(func.set_config("nexus.company_id", str(case.call.company_id), True))
        )
        work = await session.get(ExecutionWork, (case.call.company_id, case.call.task_id))
        intent = await session.get(EffectIntent, (case.call.company_id, case.call.action_id))
        hold = await session.get(CostHold, case.call.action_id)
        budget = await session.get(WorkBudget, (case.call.company_id, case.call.task_id))
        assert (
            work
            and hold
            and budget
            and budget.spent_usd == 0
            and budget.held_usd == hold.amount_usd
        )
        if phase == "intent_flush":
            assert work.model_requests_used == 0 and intent is None and hold.state == "held"
        else:
            assert work.model_requests_used == 1 and intent is not None
            assert (
                intent.state == "outcome_unknown"
                and intent.receipt_json is None
                and hold.state == "unknown"
            )

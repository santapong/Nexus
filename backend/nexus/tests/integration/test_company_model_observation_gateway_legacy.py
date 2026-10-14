"""Default empty observation wiring keeps original actual SDK/client evidence behavior."""

from datetime import UTC, datetime
from pathlib import Path

import httpx2
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.tests.integration.company_model_client_fixture import client, rows
from nexus.tests.model_observation_gateway_fixture import (
    observed_gateway_factory as observed_gateway_factory,
)
from nexus.tests.unit.test_company_provider_conformance import response


async def test_empty_observation_current_original_model_sdk_and_evidence_remain_compatible(
    observed_gateway_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    wires: list[httpx2.Request] = []

    def handle(wire: httpx2.Request) -> httpx2.Response:
        wires.append(wire)
        return httpx2.Response(200, json=response("openai"))

    model_client, call, _ = await client(
        observed_gateway_factory, tmp_path, httpx2.MockTransport(handle), cleanup_seconds=5
    )
    result = await model_client.request_once(call, now=datetime.now(UTC))
    assert len(wires) == 1 and result.recorded is not None
    assert result.recorded.billing == "known" and result.recorded.receipt_id is not None
    from nexus.harness.model_evidence import FileModelEvidenceStore

    saved = await FileModelEvidenceStore(tmp_path).load(result.recorded.artifact)
    assert (
        saved.eligibility_provenance is None and "eligibility_provenance" not in saved.model_dump()
    )
    work, intent, hold, budget = await rows(observed_gateway_factory, call)
    assert work.model_requests_used == 1 and intent is not None and intent.state == "succeeded"
    assert hold.state == "reconciled" and hold.actual_usd == budget.spent_usd

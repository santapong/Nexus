"""Repeated caller cancellation cannot abandon the bounded recording/release task."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.core.llm.company_adapter_contracts import CompanyModelRequest, CompanyModelResult
from nexus.harness.model_authorizer import PersistentModelCallAuthorizer, RecordedModelOutcome
from nexus.harness.model_client import GovernedModelCancelledError
from nexus.tests.integration.company_model_client_fixture import client, rows
from nexus.tests.integration.company_model_client_fixture import client_factory as client_factory
from nexus.tests.integration.test_company_model_client_cleanup import SlowRecorder
from nexus.tests.unit.test_company_provider_conformance import response


class CancelledRecorder(PersistentModelCallAuthorizer):
    async def record_result(
        self, request: CompanyModelRequest, result: CompanyModelResult
    ) -> RecordedModelOutcome:
        raise asyncio.CancelledError


async def test_repeated_cancellation_finishes_bounded_cleanup_and_preserves_primary_cancel(
    client_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    entered = asyncio.Event()
    SlowRecorder.entered = entered
    governed, call, _ = await client(
        client_factory,
        tmp_path,
        httpx2.MockTransport(lambda _: httpx2.Response(200, json=response("openai"))),
        gate_type=SlowRecorder,
        cleanup_seconds=0.5,
    )
    task = asyncio.create_task(governed.request_once(call, now=datetime.now(UTC)))
    await entered.wait()
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    async with asyncio.timeout(5):
        with pytest.raises(GovernedModelCancelledError) as cancelled:
            await task
    result = cancelled.value.governed
    assert result.stop_required and result.provider_result.billing == "known"
    assert result.recording_error == "recording_timeout" and result.release_status == "released"
    work, effect, hold, _ = await rows(client_factory, call)
    assert work.worker_id is None and effect and effect.state == "outcome_unknown"
    assert hold.state == "unknown" and work.model_requests_used == 1
    SlowRecorder.entered = None


async def test_cancelled_recording_does_not_assert_any_ledger_or_release_fact(
    client_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    governed, call, _ = await client(
        client_factory,
        tmp_path,
        httpx2.MockTransport(lambda _: httpx2.Response(200, json=response("openai"))),
        gate_type=CancelledRecorder,
    )
    with pytest.raises(GovernedModelCancelledError) as cancelled:
        await governed.request_once(call, now=datetime.now(UTC))
    result = cancelled.value.governed
    assert (
        result.recording_error == "cleanup_interrupted" and result.ledger_billing == "unconfirmed"
    )
    assert result.release_status == "not_attempted" and result.execution_state is None
    work, effect, hold, _ = await rows(client_factory, call)
    assert work.worker_id and effect and effect.state == "intent" and hold.state == "held"

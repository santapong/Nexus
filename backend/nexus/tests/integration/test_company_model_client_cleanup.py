"""Cancellation/error cleanup preserves primary outcome and unknown holds; offline only."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.knowledge import ArtifactRef
from nexus.core.llm.company_adapter_contracts import CompanyModelRequest, CompanyModelResult
from nexus.execution.runtime_contracts import (
    ExecutionDeniedError,
    ExecutionLease,
    ExecutionSnapshot,
)
from nexus.execution.runtime_store import ExecutionStore
from nexus.harness.model_authorizer import PersistentModelCallAuthorizer, RecordedModelOutcome
from nexus.harness.model_client import GovernedModelCancelledError
from nexus.harness.model_evidence import FileModelEvidenceStore, ModelEvidence
from nexus.tests.integration.company_model_client_fixture import client, rows
from nexus.tests.integration.company_model_client_fixture import client_factory as client_factory
from nexus.tests.unit.test_company_provider_conformance import response


class FailedEvidence(FileModelEvidenceStore):
    async def save(self, evidence: ModelEvidence) -> ArtifactRef:
        raise OSError("sensitive failure text must not escape")


class SlowRecorder(PersistentModelCallAuthorizer):
    entered: ClassVar[asyncio.Event | None] = None

    async def record_result(
        self, request: CompanyModelRequest, result: CompanyModelResult
    ) -> RecordedModelOutcome:
        if self.entered is not None:
            self.entered.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class FailedRelease(ExecutionStore):
    async def release(
        self, lease: ExecutionLease, identity: VerifiedIdentity, *, blocked: bool = False
    ) -> ExecutionSnapshot:
        raise ExecutionDeniedError("sensitive release text must not escape")


class SlowRelease(ExecutionStore):
    async def release(
        self, lease: ExecutionLease, identity: VerifiedIdentity, *, blocked: bool = False
    ) -> ExecutionSnapshot:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


@pytest.mark.parametrize("failed_release", [False, True])
async def test_cancelled_wire_records_unknown_then_releases_without_swallowing_cancel(
    client_factory: async_sessionmaker[AsyncSession], tmp_path: Path, failed_release: bool
) -> None:
    started = asyncio.Event()
    count = 0

    async def handle(_: httpx2.Request) -> httpx2.Response:
        nonlocal count
        count += 1
        started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    governed, call, _ = await client(
        client_factory,
        tmp_path,
        httpx2.MockTransport(handle),
        execution_type=FailedRelease if failed_release else ExecutionStore,
    )
    task = asyncio.create_task(governed.request_once(call, now=datetime.now(UTC)))
    await started.wait()
    task.cancel()
    with pytest.raises(GovernedModelCancelledError) as cancelled:
        await task
    result = cancelled.value.governed
    assert cancelled.value.result.status == "cancelled" and count == 1
    assert result.recorded and result.recorded.billing == "unknown"
    assert result.release_status == ("failed" if failed_release else "released")
    assert result.stop_required
    work, effect, hold, budget = await rows(client_factory, call)
    assert (work.worker_id is not None) == failed_release and work.state == "outcome_unknown"
    assert work.model_requests_used == 1 and effect and effect.state == "outcome_unknown"
    assert hold.state == "unknown" and budget.held_usd == hold.amount_usd


@pytest.mark.parametrize("failure", ["store", "record_timeout", "release", "release_timeout"])
async def test_cleanup_failure_is_bounded_sanitized_and_does_not_invent_ledger_truth(
    client_factory: async_sessionmaker[AsyncSession], tmp_path: Path, failure: str
) -> None:
    count = 0

    def handle(_: httpx2.Request) -> httpx2.Response:
        nonlocal count
        count += 1
        return httpx2.Response(200, json=response("openai"))

    governed, call, _ = await client(
        client_factory,
        tmp_path,
        httpx2.MockTransport(handle),
        evidence=FailedEvidence(tmp_path) if failure == "store" else None,
        gate_type=SlowRecorder if failure == "record_timeout" else PersistentModelCallAuthorizer,
        execution_type=FailedRelease
        if failure == "release"
        else (SlowRelease if failure == "release_timeout" else ExecutionStore),
        cleanup_seconds=0.5 if failure.endswith("timeout") else 1,
    )
    async with asyncio.timeout(5):
        result = await governed.request_once(call, now=datetime.now(UTC))
    assert count == 1 and result.provider_result.status == "response"
    assert "sensitive" not in result.model_dump_json() and result.stop_required
    work, _, hold, budget = await rows(client_factory, call)
    if failure.startswith("release"):
        assert result.recorded and result.ledger_billing == "known"
        assert (
            result.release_error
            == ("release_denied" if failure == "release" else "release_timeout")
            and work.worker_id
        )
        assert work.state == "verifying" and hold.state == "reconciled"
    else:
        assert result.recorded is None and result.ledger_billing == "unconfirmed"
        assert result.recording_error == (
            "recording_failed" if failure == "store" else "recording_timeout"
        )
        assert result.release_status == "released" and work.worker_id is None
        assert work.state == "outcome_unknown" and hold.state == "unknown"
        assert hold.actual_usd is None and budget.held_usd == hold.amount_usd


async def test_cancellation_after_wire_preserves_known_provider_result_and_bounds_cleanup(
    client_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    recording = asyncio.Event()
    SlowRecorder.entered = recording

    def handle(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=response("openai"))

    governed, call, _ = await client(
        client_factory,
        tmp_path,
        httpx2.MockTransport(handle),
        gate_type=SlowRecorder,
        cleanup_seconds=0.5,
    )
    task = asyncio.create_task(governed.request_once(call, now=datetime.now(UTC)))
    await recording.wait()
    task.cancel()
    async with asyncio.timeout(5):
        with pytest.raises(GovernedModelCancelledError) as cancelled:
            await task
    result = cancelled.value.governed
    assert result.provider_result.billing == "known" and result.ledger_billing == "unconfirmed"
    assert result.recording_error == "recording_timeout" and result.release_status == "released"
    assert (await rows(client_factory, call))[0].worker_id is None
    SlowRecorder.entered = None

"""Ordinary file threads and real SDK mocks retain resource owners, never late authority.

Native SQL delivery is mocked explicitly; no database or paid provider is used.
"""

from __future__ import annotations

import asyncio
import os
import threading
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid5

import httpx2
import pytest

from nexus.core.llm.company_adapter_contracts import (
    AuthorizedModelAttempt,
    CompanyModelRequest,
    CompanyModelResult,
    request_hash,
)
from nexus.core.llm.company_pricing import CostQuote
from nexus.execution.management_services import ManagementExecutionServices
from nexus.execution.runtime_support import lease_scope
from nexus.harness.model_authorizer import PersistentModelCallAuthorizer, RecordedModelOutcome
from nexus.harness.model_evidence import FileModelEvidenceStore, ModelEvidence
from nexus.tests.unit.test_company_model_evidence import envelope
from nexus.tests.unit.test_company_planning_consumer import composition
from nexus.tests.unit.test_company_provider_conformance import response


async def entered(event: threading.Event) -> None:
    async with asyncio.timeout(2):
        while not event.is_set():
            await asyncio.sleep(0.001)


@pytest.mark.parametrize("phase", ["save", "load", "hash"])
async def test_cancelled_file_operation_keeps_actual_thread_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    store, evidence = FileModelEvidenceStore(tmp_path), envelope()
    reference = await store.save(evidence)
    started, finish = threading.Event(), threading.Event()
    read, sync, read_bytes = store._read, os.fsync, Path.read_bytes
    task: asyncio.Task[object]

    def block() -> None:
        started.set()
        if not finish.wait(4):
            raise TimeoutError("Finite supplied filesystem stall")

    def delayed_read(path: Path) -> ModelEvidence:
        block()
        return read(path)

    def delayed_sync(fd: int) -> None:
        block()
        sync(fd)

    def delayed_hash(path: Path) -> bytes:
        block()
        return read_bytes(path)

    if phase == "save":
        monkeypatch.setattr(os, "fsync", delayed_sync)
        store = FileModelEvidenceStore(tmp_path / "fresh")
        task = cast(asyncio.Task[object], asyncio.create_task(store.save(evidence)))
    elif phase == "load":
        monkeypatch.setattr(store, "_read", delayed_read)
        task = cast(asyncio.Task[object], asyncio.create_task(store.load(reference)))
    else:
        monkeypatch.setattr(Path, "read_bytes", delayed_hash)
        task = cast(asyncio.Task[object], asyncio.create_task(store.load(reference)))
    try:
        await entered(started)
        task.cancel("Original caller denial")
        with pytest.raises(asyncio.CancelledError) as caught:
            await task
        owners = store.pending_owners()
        assert len(owners) == 1 and not owners[0].done()
        assert caught.value.__dict__["_nexus_model_pending"] == owners
        task.cancel("Repeated cancellation cannot cancel the thread owner")
        assert not owners[0].cancelled()
    finally:
        finish.set()
        if hasattr(store, "pending_owners"):
            await asyncio.gather(*store.pending_owners())
    assert store.pending_owners() == ()


async def test_actual_sdk_record_timeout_does_not_release_over_live_file_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    posts: list[str] = []

    def wire(call: httpx2.Request) -> httpx2.Response:
        posts.append(call.method)
        return httpx2.Response(200, json=response("openai"))

    consumer, prepared = composition(tmp_path, httpx2.MockTransport(wire))
    store = consumer.evidence
    started, finish = threading.Event(), threading.Event()
    native_record = AsyncMock()
    release = AsyncMock(return_value=SimpleNamespace(state="blocked"))
    original_sync = os.fsync

    def stalled_sync(fd: int) -> None:
        started.set()
        if not finish.wait(9):
            raise TimeoutError("Finite supplied filesystem stall")
        original_sync(fd)

    async def claim(
        gate: PersistentModelCallAuthorizer, call: CompanyModelRequest, quote: CostQuote
    ) -> AuthorizedModelAttempt:
        return AuthorizedModelAttempt(
            scope=lease_scope(consumer.lease),
            action_id=call.action_id,
            attempt_id=call.attempt_id,
            request_id=call.request_id,
            request_hash=request_hash(call),
            registry_id=call.registry_id,
            registry_revision=call.registry_revision,
            price_version=call.price_version,
            reserved_usd=quote.amount_usd,
        )

    async def before(
        gate: PersistentModelCallAuthorizer,
        call: CompanyModelRequest,
        quote: CostQuote,
        provenance: str | None,
    ) -> datetime:
        return datetime.now(UTC)

    async def record(
        gate: PersistentModelCallAuthorizer, call: CompanyModelRequest, result: CompanyModelResult
    ) -> RecordedModelOutcome:
        actual = envelope().model_copy(
            update={
                "request": call,
                "request_hash": request_hash(call),
                "result": result,
                "model": consumer._registry.models[0],
                "recipe": prepared.input_recipe,
                "input_estimate": consumer._estimator.estimate(
                    call, consumer._registry, prepared.input_recipe
                ),
            }
        )
        artifact = await store.save(actual)
        await store.load(artifact)
        await native_record()
        return RecordedModelOutcome(
            artifact=artifact,
            billing="known",
            actual_usd=Decimal("0.000360"),
            stop_required=False,
            receipt_id=uuid5(call.action_id, "model-receipt-v1"),
        )

    monkeypatch.setattr(PersistentModelCallAuthorizer, "claim", claim)
    monkeypatch.setattr(PersistentModelCallAuthorizer, "revalidate_before_sdk", before)
    monkeypatch.setattr(PersistentModelCallAuthorizer, "record_result", record)
    execution = consumer.management.execution_store(consumer._factory)
    monkeypatch.setattr(execution, "release", release)
    monkeypatch.setattr(ManagementExecutionServices, "execution_store", lambda *args: execution)
    monkeypatch.setattr(os, "fsync", stalled_sync)
    try:
        attempt = await consumer.request_once(prepared, now=datetime.now(UTC))
        assert started.is_set() and posts == ["POST"]
        assert attempt.governed.recording_error == "recording_timeout"
        assert release.await_count == 0
        assert attempt.governed.release_status == "failed"
        assert attempt.governed.release_error == "release_failed"
        assert attempt.candidate is None and attempt.stop_required
        owners = consumer.pending_owners()
        assert len(owners) == 1 and not owners[0].done()
        assert consumer._clients[0].pending_owners() == owners
        native_record.assert_not_awaited()
    finally:
        finish.set()
        if hasattr(store, "pending_owners"):
            await asyncio.gather(*store.pending_owners())
    await asyncio.sleep(0)
    # Retiring resources must not resume the cancelled recording chain or SDK.
    native_record.assert_not_awaited()
    release.assert_not_awaited()
    assert consumer.pending_owners() == () and posts == ["POST"]


async def test_stopped_consumer_cannot_construct_a_later_client(tmp_path: Path) -> None:
    consumer, prepared = composition(tmp_path, httpx2.MockTransport(lambda _: httpx2.Response(500)))
    consumer.request_stop()
    with pytest.raises(ValueError, match="one planning request"):
        await consumer.request_once(prepared, now=datetime.now(UTC))
    assert consumer._clients == []


async def test_timed_out_native_settlement_retains_real_call_without_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    consumer, prepared = composition(tmp_path, httpx2.MockTransport(lambda _: httpx2.Response(500)))
    client = consumer._client(prepared)
    consumer._clients.append(client)
    entered_native, finish = asyncio.Event(), asyncio.Event()
    completed: list[str] = []

    async def actual_native_call() -> RecordedModelOutcome:
        entered_native.set()
        await finish.wait()
        completed.append("actual-native-return")
        raise ValueError("Supplied native denial; no private response values")

    async def record(*args: object) -> RecordedModelOutcome:
        return await client._gate._owned(actual_native_call())

    release = AsyncMock()
    monkeypatch.setattr(client._gate, "record_result", record)
    monkeypatch.setattr(client._execution, "release", release)
    # A shorter configured cleanup is already supported; the original 5s case
    # above covers the default and this keeps the separate native-leaf case finite.
    client._cleanup_seconds = 0.02
    try:
        outcome = await client._finish(prepared.request, envelope().result)
        assert entered_native.is_set() and completed == []
        assert outcome.recording_error == "recording_timeout"
        assert outcome.recorded is None and outcome.release_status == "failed"
        owners = consumer.pending_owners()
        assert len(owners) == 1 and not owners[0].done()
        release.assert_not_awaited()
        finish.set()
        settled = await asyncio.gather(*owners, return_exceptions=True)
        assert isinstance(settled[0], ValueError)
        assert completed == ["actual-native-return"]
    finally:
        finish.set()
    release.assert_not_awaited()
    assert consumer.pending_owners() == ()


async def test_cleanup_cannot_mint_new_record_release_windows_after_original_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nexus.builder.contained_query import clock_us

    consumer, prepared = composition(tmp_path, httpx2.MockTransport(lambda _: httpx2.Response(500)))
    client = consumer._client(prepared)

    async def record(*args: object) -> RecordedModelOutcome:
        await asyncio.sleep(0.05)
        raise ValueError("Supplied native denial")

    release = AsyncMock(return_value=SimpleNamespace(state="blocked"))
    monkeypatch.setattr(client._gate, "record_result", record)
    monkeypatch.setattr(client._execution, "release", release)
    monkeypatch.setattr(client, "_end_us", clock_us() + 10_000, raising=False)
    outcome = await client._finish(prepared.request, envelope().result)
    release.assert_not_awaited()
    assert outcome.recording_error == "recording_timeout"
    assert outcome.release_status == "failed" and outcome.release_error == "release_timeout"


@pytest.mark.parametrize("fault", ["bool", "float", "expired", "sdk-later", "sdk-no-parent"])
def test_server_deadline_arguments_fail_closed_before_gateway(
    tmp_path: Path,
    fault: str,
) -> None:
    from nexus.builder.contained_query import clock_us
    from nexus.harness.model_client import GovernedModelClient

    consumer, prepared = composition(tmp_path, httpx2.MockTransport(lambda _: httpx2.Response(500)))
    old = consumer._client(prepared)
    end: object = clock_us() + 1_000_000
    sdk: int | None = None
    if fault == "bool":
        end = True
    elif fault == "float":
        end = float("nan")
    elif fault == "expired":
        end = clock_us() - 1
    elif fault == "sdk-later":
        sdk = cast(int, end) + 1
    else:
        end, sdk = None, clock_us() + 1_000_000
    with pytest.raises(ValueError):
        GovernedModelClient(
            consumer._registry,
            consumer._resolver,
            old._gate,
            old._execution,
            consumer.lease,
            consumer._identity,
            end_us=cast(int | None, end),
            sdk_end_us=sdk,
        )


def test_nexus_consumer_requires_genuine_original_actor_witness(tmp_path: Path) -> None:
    from nexus.tests.unit.nexus_cycle_fixture import case

    consumer, prepared = composition(tmp_path, httpx2.MockTransport(lambda _: httpx2.Response(500)))
    _, catalog = case()
    # Use the actual configured Nexus catalog, without claiming this foreign
    # supplied fixture is native registered planning or passing its effect gate.
    consumer._management = ManagementExecutionServices(
        catalog, consumer.management.artifacts, consumer.management.freshness
    )
    with pytest.raises(ValueError, match="authenticated actor witness"):
        consumer._client(prepared)

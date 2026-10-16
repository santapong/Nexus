"""Finite actual private files and blocked-worker ownership, without native effects."""

import asyncio
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from pydantic_ai.models import Model

from nexus.company.contracts.knowledge import ArtifactRef
from nexus.core.llm.company_adapter_contracts import ServerEndpoint
from nexus.core.llm.company_adapter_sdk import sdk_model as actual_sdk_model
from nexus.core.llm.company_registry import ModelRegistration
from nexus.core.llm.company_wire_usage import WireObserver
from nexus.harness.qualification_evidence import QualificationEvidence
from nexus.tests.unit.test_qualification_client import prepared


async def test_protected_evidence_roundtrip_mode_and_immutable_write_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = prepared(tmp_path, monkeypatch)
    result = await client.request_once()
    assert result.evidence is not None
    loaded = await client._store.load(result.evidence, end_us=client._end)
    assert loaded.recipe.target.health.status == "unknown" and not loaded.recipe.target.enabled
    path = Path(result.evidence.reference)
    assert path.stat().st_mode & 0o777 == 0o400 and path.stat().st_nlink == 1
    with pytest.raises(FileExistsError):
        await client._store.save(loaded, end_us=client._end)
    assert await client._store.load(result.evidence, end_us=client._end) == loaded
    forged = result.evidence.model_copy(update={"sha256": "f" * 64})
    with pytest.raises(ValueError):
        await client._store.load(forged, end_us=client._end)


async def test_evidence_failure_never_records_a_ledger_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, order = prepared(tmp_path, monkeypatch)

    def denied(*args: object, **kwargs: object) -> ArtifactRef:
        raise PermissionError("supplied private filesystem failure")

    monkeypatch.setattr(client._store, "_write", denied)
    result = await client.request_once()
    assert result.provider_result.billing == "known" and result.recording_error is not None
    assert result.evidence is None and result.record is None
    assert order == ["intent", "post"] and not client.pending_owners()


async def test_pending_real_file_worker_survives_caller_cancellation_with_actual_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, order = prepared(tmp_path, monkeypatch)
    entered, release = threading.Event(), threading.Event()
    original = client._store._write

    def blocked(evidence: QualificationEvidence, raw: bytes, end_us: int) -> ArtifactRef:
        entered.set()
        assert release.wait(3), "finite blocked worker explicitly released"
        return original(evidence, raw, end_us)

    monkeypatch.setattr(client._store, "_write", blocked)
    caller = asyncio.create_task(client.request_once())
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        caller.cancel()
        with pytest.raises(asyncio.CancelledError) as caught:
            await caller
        assert client.pending_owners() and all(
            not task.cancelled() for task in client.pending_owners()
        )
        partial = caught.value.__dict__["_nexus_qualification_result"]
        assert partial.provider_result.billing == "known" and partial.record is None
        assert partial.recording_error is not None
        assert order == ["intent", "post"]
    finally:
        release.set()
        await asyncio.gather(*client.pending_owners(), return_exceptions=True)
    assert not client.pending_owners()


async def test_final_clock_denies_success_without_losing_actual_returned_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.core.llm.company_adapter_contracts import CompanyModelResult
    from nexus.execution.runtime_contracts import EffectRecord
    from nexus.harness import qualification_client as module
    from nexus.harness import qualification_evidence as evidence_module
    from nexus.harness.qualification_client import QualificationRunResult

    client, _ = prepared(tmp_path, monkeypatch)
    now = [client._end - 5_000_000]
    monkeypatch.setattr(module, "clock_us", lambda: now[0])
    monkeypatch.setattr(evidence_module, "clock_us", lambda: now[0])
    original = client._record

    async def expire(intent: EffectRecord, result: CompanyModelResult) -> QualificationRunResult:
        outcome = await original(intent, result)
        now[0] = client._end
        return outcome

    monkeypatch.setattr(client, "_record", expire)
    result = await client.request_once()
    assert result.recording_error == "original_end_expired"
    assert result.evidence is not None and result.record is not None
    assert result.record.state == "succeeded"  # Actual returned prefix, never late eligibility.
    assert result.stop_required and not result.profile_quality_evaluated


async def test_repeated_cancel_keeps_actual_sdk_close_worker_owned_until_retired(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.harness import qualification_client as module

    client, order = prepared(tmp_path, monkeypatch)
    entered, release = threading.Event(), threading.Event()

    def close() -> None:
        entered.set()
        assert release.wait(3), "finite SDK close worker explicitly released"

    @asynccontextmanager
    async def delayed(
        row: ModelRegistration, endpoint: ServerEndpoint, observer: WireObserver
    ) -> AsyncIterator[Model]:
        async with actual_sdk_model(row, endpoint, observer) as model:
            yield model
        await asyncio.to_thread(close)

    monkeypatch.setattr(module, "sdk_model", delayed)
    caller = asyncio.create_task(client.request_once())
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        caller.cancel("first SDK close cancellation")
        await asyncio.sleep(0.1)
        assert not caller.done() and client.pending_owners()
        assert all(not task.cancelled() for task in client.pending_owners())
        assert order == ["intent", "post"]
        caller.cancel("second SDK close cancellation")
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError, match="first SDK close cancellation") as caught:
            await caller
        result = caught.value.__dict__["_nexus_qualification_result"]
        assert result.caller_interrupted and result.record.state == "failed"
        assert result.actual_usd is not None and result.evidence is not None
    finally:
        release.set()
        await asyncio.gather(caller, *client.pending_owners(), return_exceptions=True)
    assert not client.pending_owners()

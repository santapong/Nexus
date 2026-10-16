"""Actual SDK MockTransport and protected files; native claim/record/release IO is supplied.

Actual temporary repository archive is read by the concrete store; native/source SQL delivery
is supplied. No live vendor, real native permission or DB accounting proof follows.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Coroutine
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid5

import httpx2
import pytest
from pydantic import SecretStr

from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.management.coding_consumer import (
    CodingReadCancelledError,
    RegisteredCodingConsumer,
)
from nexus.company.management.coding_intent import PreparedCodingRequest
from nexus.company.management.coding_prepared_checks import conditions
from nexus.company.management.coding_stored_intent import StoredCodingIntent
from nexus.core.llm.company_adapter_contracts import (
    AuthorizedModelAttempt,
    CompanyModelRequest,
    CompanyModelResult,
    ServerEndpoint,
    request_hash,
)
from nexus.core.llm.company_pricing import CostQuote, reconcile_cost
from nexus.execution.runtime_store import ExecutionStore
from nexus.execution.runtime_support import lease_scope
from nexus.harness.model_authorizer import PersistentModelCallAuthorizer, RecordedModelOutcome
from nexus.harness.model_client_contracts import GovernedModelCancelledError
from nexus.harness.model_evidence import FileModelEvidenceStore, ModelEvidence
from nexus.tests.unit.test_coding_content import PATCH
from nexus.tests.unit.test_coding_prepared_store import saved_case
from nexus.tests.unit.test_company_provider_conformance import EndpointResolver, response


async def composition(
    root: Path,
    transport: httpx2.AsyncBaseTransport,
    monkeypatch: pytest.MonkeyPatch,
    *,
    duration_us: int = 20_000_000,
) -> tuple[RegisteredCodingConsumer, PreparedCodingRequest]:
    root.mkdir(mode=0o700, exist_ok=True)
    store, prepared, lease, credential, _ = await saved_case(root, monkeypatch)
    loaded = await store.load_worker(
        lease,
        credential,
        prepared.request.action_id,
        end_us=time.monotonic_ns() // 1000 + duration_us,
    )
    factory, management, contexts = store.factory, store.management, store.contexts
    catalog = management.catalog
    from nexus.harness.model_input_estimator import FullContextInputEstimator

    estimator = FullContextInputEstimator(catalog.models, prepared.input_recipe)
    row = catalog.models.models[1]
    endpoint = ServerEndpoint(
        endpoint_id=row.endpoint_id,
        provider=row.provider,
        api_family=row.api_family,
        base_url="https://offline.invalid/v1",
        api_key=SecretStr("fake-coding-test-key"),
        transport=transport,
        # This fixture tests the protocol. The actual cold SDK/close work must
        # fit even under coverage; explicit short-expiry cases are separate.
        timeout_seconds=10,
    )
    end = time.monotonic_ns() // 1000 + duration_us
    return RegisteredCodingConsumer(
        factory,
        management,
        contexts,
        FileModelEvidenceStore(root / "models"),
        EndpointResolver(endpoint),
        estimator,
        prepared.input_recipe,
        lease,
        credential,
        resources=conditions(loaded.header),
        prepared_store=store,
        stored=loaded,
        end_us=end,
        sdk_end_us=end - min(5_000_000, duration_us // 2),
    ), prepared


def install_native_delivery(
    consumer: RegisteredCodingConsumer, monkeypatch: pytest.MonkeyPatch
) -> AsyncMock:
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
        assert type(gate._additional_check) is StoredCodingIntent
        gate._additional_check.validate_time(datetime.now(UTC))
        return datetime.now(UTC)

    async def record(
        gate: PersistentModelCallAuthorizer, call: CompanyModelRequest, result: CompanyModelResult
    ) -> RecordedModelOutcome:
        registry = consumer.management.catalog.models
        model = next(row for row in registry.models if row.registry_id == call.registry_id)
        now = datetime.now(UTC)
        admission = consumer.management.catalog.nexus_coding_admission
        assert admission is not None
        envelope = ModelEvidence(
            request=call,
            request_hash=request_hash(call),
            action_hash="a" * 64,
            model=model,
            registry_revision=registry.revision,
            price_version=registry.pricebook_version,
            recipe=consumer._recipe,
            input_estimate=consumer._estimator.estimate(call, registry, consumer._recipe),
            result=result,
            source_event_at=now,
            checked_at=now,
            owner_id=admission.procedure.binding.actor_id,
        )
        artifact = await consumer.evidence.save(envelope)
        assert model.price is not None
        return RecordedModelOutcome(
            artifact=artifact,
            billing=result.billing,
            actual_usd=reconcile_cost(model.price, result.usage, now=now).amount_usd
            if result.usage
            else None,
            receipt_id=uuid5(call.action_id, "model-receipt-v1")
            if result.billing == "known"
            else None,
            stop_required=result.status != "response" or result.billing != "known",
        )

    release = AsyncMock(return_value=SimpleNamespace(state="verifying"))
    monkeypatch.setattr(PersistentModelCallAuthorizer, "claim", claim)
    monkeypatch.setattr(PersistentModelCallAuthorizer, "revalidate_before_sdk", before)
    monkeypatch.setattr(PersistentModelCallAuthorizer, "record_result", record)
    monkeypatch.setattr(ExecutionStore, "release", release)
    return release


def output(prepared: PreparedCodingRequest, semantic: str = "valid") -> str:
    return json.dumps(
        {
            "patch": PATCH if semantic != "malformed" else "not a patch",
            "explanation": "Model-authored correction of the pinned source.",
            "questions": [],
            "evidence_ids": [str(prepared.sources[0].evidence[0].evidence_id)]
            if semantic != "foreign"
            else [str(uuid5(prepared.request.action_id, "foreign"))],
        }
    )


def strings(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, dict):
        return tuple(text for child in value.values() for text in strings(child))
    if isinstance(value, list):
        return tuple(text for child in value for text in strings(child))
    return ()


@pytest.mark.parametrize(
    "semantic", ["valid", "malformed", "foreign", "missing-usage", "wrong-model"]
)
async def test_real_single_sdk_post_protected_result_and_charged_domain_denial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, semantic: str
) -> None:
    posts = []

    def wire(call: httpx2.Request) -> httpx2.Response:
        posts.append(call.method)
        emitted = strings(json.loads(call.content))
        assert prepared.request.input_text in emitted
        assert prepared.request.output_schema is not None
        assert json.loads(prepared.request.output_schema.document)["$comment"] in emitted
        # Vendor fixture is dynamic JSON; production parsing runs the actual pinned SDK.
        body = json.loads(json.dumps(response("google")))
        if semantic != "wrong-model":
            body["modelVersion"] = consumer.management.catalog.models.models[1].model_id
        body["candidates"][0]["content"]["parts"][0]["text"] = output(prepared, semantic)
        if semantic == "missing-usage":
            del body["usageMetadata"]
        return httpx2.Response(200, json=body)

    consumer, prepared = await composition(tmp_path, httpx2.MockTransport(wire), monkeypatch)
    release = install_native_delivery(consumer, monkeypatch)
    result = await consumer.request_once(prepared, now=datetime.now(UTC))
    assert posts == ["POST"]
    assert result.governed.recorded is not None, (
        result.governed.recording_error,
        result.governed.provider_result.error_code,
        result.governed.provider_result.status,
    )
    saved = await consumer.evidence.load(result.governed.recorded.artifact)
    assert saved.input_estimate == prepared.input_estimate
    if semantic == "valid":
        assert result.candidate is not None and not result.stop_required, (
            result.governed.provider_result.status,
            result.governed.provider_result.error_code,
        )
        assert (
            result.candidate.binding == prepared.binding and result.candidate.content.patch == PATCH
        )
        assert result.governed.release_status == "released"
    else:
        assert result.candidate is None and result.stop_required
        assert result.denial == (
            "model_outcome" if semantic in {"missing-usage", "wrong-model"} else "invalid_content"
        )
    if semantic in {"missing-usage", "wrong-model"}:
        assert result.governed.ledger_billing == "unknown"
        assert result.governed.recorded.actual_usd is None
    else:
        assert result.governed.ledger_billing == "known"
        assert (
            result.governed.recorded.actual_usd is not None
            and result.governed.recorded.actual_usd > 0
        )
    release.assert_awaited_once()
    with pytest.raises(ValueError, match="one coding request"):
        await consumer.request_once(prepared, now=datetime.now(UTC))
    assert posts == ["POST"]


async def test_stop_before_issue_and_expired_original_end_never_call_sdk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    posts = []

    def forbidden(req: httpx2.Request) -> httpx2.Response:
        posts.append(req.method)
        raise AssertionError("A stopped/expired coding request cannot reach the SDK")

    consumer, prepared = await composition(tmp_path, httpx2.MockTransport(forbidden), monkeypatch)
    install_native_delivery(consumer, monkeypatch)
    consumer.request_stop()
    with pytest.raises(ValueError):
        await consumer.request_once(prepared, now=datetime.now(UTC))
    assert not posts
    consumer2, prepared2 = await composition(
        tmp_path / "expired", httpx2.MockTransport(forbidden), monkeypatch
    )
    monkeypatch.setattr(
        "nexus.company.management.coding_consumer._clock", lambda: consumer2._end_us
    )
    with pytest.raises(TimeoutError):
        await consumer2.request_once(prepared2, now=datetime.now(UTC))
    assert not posts


async def test_cancellation_during_real_thread_read_retains_owner_and_never_adopts_late_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def wire(_: httpx2.Request) -> httpx2.Response:
        body = json.loads(json.dumps(response("google")))
        body["modelVersion"] = consumer.management.catalog.models.models[1].model_id
        body["candidates"][0]["content"]["parts"][0]["text"] = output(prepared)
        return httpx2.Response(200, json=body)

    consumer, prepared = await composition(tmp_path, httpx2.MockTransport(wire), monkeypatch)
    install_native_delivery(consumer, monkeypatch)
    started, finish = Event(), Event()
    actual = FileModelEvidenceStore._read
    count = 0

    def delayed(path: Path) -> ModelEvidence:
        nonlocal count
        count += 1
        if count == 1:
            started.set()
            assert finish.wait(3)
        return actual(path)

    monkeypatch.setattr(FileModelEvidenceStore, "_read", staticmethod(delayed))
    run = asyncio.create_task(consumer.request_once(prepared, now=datetime.now(UTC)))
    try:
        assert await asyncio.to_thread(started.wait, 3)
        run.cancel()
        with pytest.raises(CodingReadCancelledError) as caught:
            await run
        assert caught.value.governed.ledger_billing == "known"
        assert consumer.pending_owners() and not caught.value.evidence_read.done()
        finish.set()
        await asyncio.gather(*consumer.pending_owners())
        assert not consumer.pending_owners()
        with pytest.raises(ValueError):
            await consumer.request_once(prepared, now=datetime.now(UTC))
    finally:
        finish.set()
        await asyncio.gather(run, return_exceptions=True)


async def test_sdk_cancellation_keeps_actual_exchange_unknown_and_does_not_release_pending_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered, finish = asyncio.Event(), asyncio.Event()
    posts: list[str] = []

    async def wire(request: httpx2.Request) -> httpx2.Response:
        posts.append(request.method)
        entered.set()
        await finish.wait()
        body = json.loads(json.dumps(response("google")))
        body["modelVersion"] = consumer.management.catalog.models.models[1].model_id
        body["candidates"][0]["content"]["parts"][0]["text"] = output(prepared)
        return httpx2.Response(200, json=body)

    consumer, prepared = await composition(tmp_path, httpx2.MockTransport(wire), monkeypatch)
    release = install_native_delivery(consumer, monkeypatch)
    run = asyncio.create_task(consumer.request_once(prepared, now=datetime.now(UTC)))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        run.cancel()
        with pytest.raises(GovernedModelCancelledError) as caught:
            await run
        frozen = caught.value.governed
        assert frozen.ledger_billing in {"unknown", "unconfirmed"}
        assert frozen.stop_required and frozen.release_status != "released"
        assert consumer.pending_owners()
        release.assert_not_awaited()
        finish.set()
        await asyncio.gather(*consumer.pending_owners(), return_exceptions=True)
        assert not consumer.pending_owners()
        assert caught.value.governed is frozen and frozen.stop_required
        with pytest.raises(ValueError):
            await consumer.request_once(prepared, now=datetime.now(UTC))
        assert posts == ["POST"]
    finally:
        finish.set()
        await asyncio.gather(run, return_exceptions=True)


async def test_original_read_timeout_preserves_real_thread_owner_without_late_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def wire(_: httpx2.Request) -> httpx2.Response:
        body = json.loads(json.dumps(response("google")))
        body["modelVersion"] = consumer.management.catalog.models.models[1].model_id
        body["candidates"][0]["content"]["parts"][0]["text"] = output(prepared)
        return httpx2.Response(200, json=body)

    consumer, prepared = await composition(tmp_path, httpx2.MockTransport(wire), monkeypatch)
    install_native_delivery(consumer, monkeypatch)
    entered, finish = Event(), Event()
    actual = FileModelEvidenceStore._read
    actual_load = consumer.evidence.load
    from nexus.company.management import coding_consumer as module

    actual_clock = module._clock
    original_end = consumer._end_us

    def near_original_end(reference: ArtifactRef) -> Coroutine[None, None, ModelEvidence]:
        # Advance only this fixture's consumer clock at the real read boundary.
        # Keep its first absolute end unchanged; SDK/setup clocks are untouched.
        offset = consumer._end_us - actual_clock() - 500_000
        assert offset > 0
        monkeypatch.setattr(module, "_clock", lambda: actual_clock() + offset)
        return actual_load(reference)

    def delayed(path: Path) -> ModelEvidence:
        entered.set()
        assert finish.wait(4)
        return actual(path)

    monkeypatch.setattr(FileModelEvidenceStore, "_read", staticmethod(delayed))
    monkeypatch.setattr(consumer.evidence, "load", near_original_end)
    run = asyncio.create_task(consumer.request_once(prepared, now=datetime.now(UTC)))
    try:
        assert await asyncio.to_thread(entered.wait, 10)
        result = await run
        assert result.candidate is None and result.denial == "evidence_unavailable"
        assert consumer._end_us == original_end
        assert result.governed.ledger_billing == "known" and result.stop_required
        assert consumer.pending_owners()
        finish.set()
        await asyncio.gather(*consumer.pending_owners(), return_exceptions=True)
        assert not consumer.pending_owners() and result.candidate is None
    finally:
        finish.set()
        await asyncio.gather(run, return_exceptions=True)

"""Actual pinned SDK with supplied native leaves and fake transport; no authority qualification."""

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import UUID

import httpx2
import pytest
from pydantic import SecretStr
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models import Model
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.builder.contained_query import clock_us
from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.canonical import canonical_sha256
from nexus.core.llm.company_adapter_contracts import CompanyModelRequest, ServerEndpoint
from nexus.core.llm.company_adapter_sdk import request_model as actual_request_model
from nexus.core.llm.qualification_contracts import SdkPins, qualification_request
from nexus.execution.effect_store import EffectStore
from nexus.execution.runtime_contracts import EffectRecord, EffectStart, ExecutionLease
from nexus.harness import qualification_client as client_module
from nexus.harness import qualification_evidence as evidence_module
from nexus.harness.qualification_client import QualificationClient
from nexus.harness.qualification_evidence import FileQualificationEvidenceStore
from nexus.harness.qualification_intent import QualificationIntentCheck
from nexus.tests.unit.test_company_provider_conformance import response
from nexus.tests.unit.test_qualification_contracts import NOW, recipe, scope


def prepared(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    provider: str = "openai",
    mode: str = "normal",
) -> tuple[QualificationClient, list[str]]:
    value = recipe()
    if provider == "google":
        target = value.target.model_copy(
            update={
                "provider": "google",
                "api_family": "google_generate_content",
                "model_id": "gemini-3.5-flash-lite",
                "endpoint_id": "google.official.v1",
                "context_window": 1048576,
                "max_output_tokens": 65536,
            }
        )
        value = value.model_copy(
            update={
                "target": target,
                "financial_input_ceiling": 1048576,
                "financial_output_ceiling": 65536,
                "qualification_target_sha256s": (canonical_sha256(target),),
            }
        )
    call = qualification_request(value, scope(), action_id=UUID(int=5), request_id=UUID(int=6))
    factory = cast(async_sessionmaker[AsyncSession], object())
    effects = EffectStore(factory)
    lease = ExecutionLease(
        company_id=scope().company_id,
        task_id=scope().task_id,
        trace_id=scope().trace_id,
        actor_id=scope().principal_id,
        workspace_id=UUID(int=7),
        run_id=UUID(int=10),
        workflow_version="v1",
        segment_id=UUID(int=11),
        worker_id=UUID(int=12),
        fence=1,
        expires_at=NOW + timedelta(minutes=5),
        mode="execute",
    )
    identity = VerifiedIdentity(principal_id=lease.actor_id, workspace_id=lease.workspace_id)
    intent = EffectRecord(
        company_id=lease.company_id,
        action_id=call.action_id,
        task_id=lease.task_id,
        trace_id=lease.trace_id,
        run_id=lease.run_id,
        proposal_hash="f" * 64,
        intent_fence=1,
        attempt_kind="model_requests",
        state="intent",
        created_at=NOW,
        receipt=None,
        verification=None,
    )
    order: list[str] = []

    async def begin(*args: object, **kwargs: object) -> EffectStart:
        assert kwargs["kind"] == "model_requests"
        assert isinstance(kwargs["before_intent"], QualificationIntentCheck)
        order.append("intent")
        return EffectStart(record=intent, permit_external_call=mode != "existing")

    async def revalidate(self: QualificationIntentCheck) -> datetime:
        return NOW

    async def recorded(*args: object, **kwargs: object) -> EffectRecord:
        assert list((tmp_path / "evidence").rglob("*.json"))
        receipt = cast(ActionReceipt, args[2])
        assert (kwargs["actual_usd"] is None) == (receipt.outcome == "outcome_unknown")
        order.append("receipt")
        return intent.model_copy(update={"state": receipt.outcome, "receipt": receipt})

    def handle(wire: httpx2.Request) -> httpx2.Response:
        order.append("post")
        if mode == "cancel":
            raise asyncio.CancelledError("supplied original SDK cancellation")
        if mode == "malformed":
            return httpx2.Response(200, content=b"{invalid-json")
        body = response(provider)
        body["model" if provider == "openai" else "modelVersion"] = value.target.model_id
        if mode == "usage":
            body.pop("usage" if provider == "openai" else "usageMetadata")
        if mode == "continuation":
            candidates = body["candidates"]
            assert isinstance(candidates, list) and isinstance(candidates[0], dict)
            candidates[0].update(finishReason="CONTINUATION", continuationToken="Y29udGludWU=")
        return httpx2.Response(200, json=body)

    class Resolver:
        async def resolve(self, endpoint_id: str) -> ServerEndpoint:
            return ServerEndpoint(
                endpoint_id=endpoint_id,
                provider=provider,
                api_family="openai_responses"
                if provider == "openai"
                else "google_generate_content",
                base_url="https://api.openai.com/v1"
                if provider == "openai"
                else "https://generativelanguage.googleapis.com",
                api_key=SecretStr("fake-qualification-key"),
                transport=httpx2.MockTransport(handle),
            )

    monkeypatch.setattr(effects, "begin", begin)
    monkeypatch.setattr(effects, "record_receipt", recorded)
    monkeypatch.setattr(QualificationIntentCheck, "revalidate_before_sdk", revalidate)
    monkeypatch.setattr(QualificationIntentCheck, "observation_time", revalidate)
    client = QualificationClient(
        factory,
        effects,
        lease,
        identity,
        value,
        call,
        Resolver(),
        FileQualificationEvidenceStore(tmp_path / "evidence"),
        end_us=clock_us() + 10_000_000,
    )
    return client, order


async def test_unknown_model_probe_records_protected_evidence_before_receipt_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, order = prepared(tmp_path, monkeypatch)
    result = await client.request_once()
    assert result.recording_error is None and result.evidence is not None
    assert result.provider_result.status == "response"
    assert result.provider_result.billing == "known"
    assert order == ["intent", "post", "receipt"]
    duplicate = await client.request_once()
    assert duplicate.provider_result.billing == "not_issued"
    assert order == ["intent", "post", "receipt"] and not client.pending_owners()
    assert not client._recipe.target.enabled and client._recipe.target.evaluations == ()


@pytest.mark.parametrize("provider", ["openai", "google"])
@pytest.mark.parametrize("mode", ["malformed", "usage"])
async def test_unknown_usage_retains_unknown_native_receipt_and_never_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    mode: str,
) -> None:
    client, order = prepared(tmp_path, monkeypatch, provider=provider, mode=mode)
    result = await client.request_once()
    assert result.provider_result.status == "failed" and result.provider_result.billing == "unknown"
    assert result.record is not None and result.record.state == "outcome_unknown"
    assert result.actual_usd is None and result.evidence is not None
    assert order == ["intent", "post", "receipt"]


async def test_google_continuation_preserves_first_usage_without_second_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, order = prepared(tmp_path, monkeypatch, provider="google", mode="continuation")
    result = await client.request_once()
    assert result.provider_result.status == "failed" and result.provider_result.billing == "known"
    assert result.provider_result.text is None and result.actual_usd is not None
    assert result.record is not None and result.record.state == "failed"
    assert order == ["intent", "post", "receipt"]


async def test_duplicate_native_intent_never_calls_sdk_or_saves_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, order = prepared(tmp_path, monkeypatch, mode="existing")
    result = await client.request_once()
    assert result.provider_result.billing == "not_issued" and result.evidence is None
    assert order == ["intent"] and not (tmp_path / "evidence").exists()


async def test_actual_sdk_cancellation_preserves_first_cause_and_unknown_hold(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, order = prepared(tmp_path, monkeypatch, mode="cancel")
    with pytest.raises(asyncio.CancelledError, match="supplied original") as caught:
        await client.request_once()
    result = caught.value.__dict__["_nexus_qualification_result"]
    assert result.provider_result.status == "cancelled" and result.actual_usd is None
    assert result.record.state == "outcome_unknown" and result.evidence is not None
    assert order == ["intent", "post", "receipt"] and not client.pending_owners()


async def test_request_splice_during_resolver_await_is_denied_before_native_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, order = prepared(tmp_path, monkeypatch)
    original = client._resolver.resolve

    async def changed(endpoint_id: str) -> ServerEndpoint:
        result = await original(endpoint_id)
        client._request = client._request.model_copy(
            update={"input_text": "Unapproved different public case"}
        )
        return result

    monkeypatch.setattr(client._resolver, "resolve", changed)
    with pytest.raises(ValueError, match="composition"):
        await client.request_once()
    assert order == []


async def test_changed_sdk_source_after_intent_denies_post_and_retains_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, order = prepared(tmp_path, monkeypatch)
    pins = client._recipe.sdk_pins
    calls = 0

    async def changed() -> SdkPins:
        nonlocal calls
        calls += 1
        if calls == 1:
            return pins
        version = pins.versions[-1].model_copy(update={"version": "unapproved-v2"})
        return pins.model_copy(update={"versions": (*pins.versions[:-1], version)})

    monkeypatch.setattr(client_module, "capture_sdk_pins", changed)
    result = await client.request_once()
    assert result.provider_result.billing == "unknown" and result.provider_result.text is None
    assert result.record is not None and result.record.state == "outcome_unknown"
    assert order == ["intent", "receipt"]


async def test_late_complete_sdk_return_is_not_promoted_or_recorded_after_original_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, order = prepared(tmp_path, monkeypatch)
    now = [client._end - 5_000_000]
    monkeypatch.setattr(client_module, "clock_us", lambda: now[0])
    monkeypatch.setattr(evidence_module, "clock_us", lambda: now[0])
    original = actual_request_model

    async def late(model: Model, request: CompanyModelRequest) -> ModelResponse:
        result = await original(model, request)
        now[0] = client._end
        return result

    monkeypatch.setattr(client_module, "request_model", late)
    result = await client.request_once()
    if client.pending_owners():
        await asyncio.gather(*client.pending_owners(), return_exceptions=True)
    assert result.provider_result.status == "failed" and result.provider_result.text is None
    assert result.record is None and result.evidence is None and result.recording_error
    assert order == ["intent", "post"]

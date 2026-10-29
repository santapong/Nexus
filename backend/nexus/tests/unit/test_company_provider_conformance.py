"""Actual pinned SDK requests over offline HTTP; never paid/live vendor conformance.

Full native provider wire fixtures and the shared two-adapter failure matrix are
kept together to make protocol evidence reviewable; this exceeds the file guideline.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx2
import pytest
from pydantic import SecretStr, ValidationError

from nexus.core.llm.company_adapter_contracts import (
    AuthorizedModelAttempt,
    CompanyModelRequest,
    JsonSchemaDocument,
    ModelRequestCancelledError,
    ModelTool,
    ServerEndpoint,
    request_hash,
)
from nexus.core.llm.company_adapters import CompanyModelAdapters
from nexus.core.llm.company_pricing import CostQuote, TokenBounds
from nexus.core.llm.company_registry import ModelRegistry
from nexus.harness.journal_contracts import LedgerScope
from nexus.tests.unit.test_company_model_registry import model

NOW = datetime.now(UTC)
KEY = "offline-fixture-provider-key"
SCHEMA = JsonSchemaDocument(
    schema_json=json.dumps(
        {
            "type": "object",
            "properties": {"result": {"type": "string"}},
            "required": ["result"],
            "additionalProperties": False,
        }
    )
)
TOOL_SCHEMA = JsonSchemaDocument(
    schema_json=json.dumps(
        {
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
            "additionalProperties": False,
        }
    )
)


def request(**updates: object) -> CompanyModelRequest:
    return CompanyModelRequest.model_validate(
        {
            "company_id": UUID(int=1),
            "task_id": UUID(int=2),
            "trace_id": UUID(int=3),
            "actor_id": UUID(int=4),
            "action_id": UUID(int=5),
            "attempt_id": UUID(int=6),
            "request_id": UUID(int=7),
            "registry_id": "fixture-a",
            "registry_revision": "registry-1",
            "price_version": "prices-1",
            "data_classification": "internal",
            "bounds": TokenBounds(input_tokens=1000, max_output_tokens=64),
            "input_text": "Return a readiness result",
            "output_schema": SCHEMA,
        }
        | updates
    )


class Authorizer:
    """Offline one-time fixture; no persistent approval/reservation proof is implied."""

    def __init__(self, *, denied: bool = False, wrong: bool = False) -> None:
        self.denied, self.wrong = denied, wrong
        self.claims = 0

    async def claim(self, call: CompanyModelRequest, quote: CostQuote) -> AuthorizedModelAttempt:
        self.claims += 1
        if self.denied or self.claims > 1:
            raise ValueError("fixture claim denied or already consumed")
        return AuthorizedModelAttempt(
            scope=LedgerScope(
                company_id=call.company_id,
                principal_id=call.actor_id,
                task_id=call.task_id,
                trace_id=call.trace_id,
            ),
            action_id=call.action_id,
            attempt_id=call.attempt_id,
            request_id=call.request_id,
            request_hash="bad" if self.wrong else request_hash(call),
            registry_id=call.registry_id,
            registry_revision=call.registry_revision,
            price_version=call.price_version,
            reserved_usd=quote.amount_usd,
        )


class EndpointResolver:
    def __init__(self, endpoint: ServerEndpoint) -> None:
        self.endpoint = endpoint

    async def resolve(self, endpoint_id: str) -> ServerEndpoint:
        assert endpoint_id == self.endpoint.endpoint_id
        return self.endpoint


def catalog(provider: str) -> ModelRegistry:
    baseline = model()
    assert baseline.price is not None
    health = baseline.health.model_copy(
        update={"checked_at": NOW - timedelta(minutes=1), "expires_at": NOW + timedelta(hours=1)}
    )
    price = baseline.price.model_copy(
        update={
            "as_of": NOW.date(),
            "valid_from": NOW - timedelta(hours=1),
            "valid_until": NOW + timedelta(hours=1),
        }
    )
    row = baseline.model_copy(
        update={
            "provider": provider,
            "api_family": "openai_responses" if provider == "openai" else "google_generate_content",
            "model_id": "fixture-model",
            "health": health,
            "price": price,
        }
    )
    return ModelRegistry(
        company_id=UUID(int=1), revision="registry-1", pricebook_version="prices-1", models=(row,)
    )


def response(provider: str) -> dict[str, object]:
    if provider == "openai":
        return {
            "id": "resp-fixture",
            "object": "response",
            "created_at": 1,
            "model": "fixture-model",
            "status": "completed",
            "output": [
                {
                    "id": "message-fixture",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {"type": "output_text", "text": '{"result":"ready"}', "annotations": []}
                    ],
                }
            ],
            "usage": {
                "input_tokens": 100,
                "output_tokens": 20,
                "total_tokens": 120,
                "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                "output_tokens_details": {"reasoning_tokens": 5},
            },
        }
    return {
        "responseId": "google-fixture",
        "modelVersion": "fixture-model",
        "candidates": [
            {
                "content": {"role": "model", "parts": [{"text": '{"result":"ready"}'}]},
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 100,
            "candidatesTokenCount": 15,
            "thoughtsTokenCount": 5,
            "totalTokenCount": 120,
            "cachedContentTokenCount": 0,
            "toolUsePromptTokenCount": 0,
        },
    }


def adapter(
    provider: str,
    handler: httpx2.MockTransport,
    authority: Authorizer | None = None,
    *,
    timeout_seconds: float = 1,
) -> CompanyModelAdapters:
    """Keep the short default; response tests may opt into a bounded SDK setup window."""
    endpoint = ServerEndpoint(
        endpoint_id="fixture-endpoint",
        provider=provider,
        api_family="openai_responses" if provider == "openai" else "google_generate_content",
        base_url="https://offline.invalid/v1"
        if provider == "openai"
        else "https://offline.invalid",
        api_key=SecretStr(KEY),
        transport=handler,
        timeout_seconds=timeout_seconds,
    )
    return CompanyModelAdapters(
        catalog(provider), EndpointResolver(endpoint), authority or Authorizer()
    )


@pytest.mark.parametrize("provider", ["openai", "google"])
async def test_single_sdk_native_request_has_exact_family_model_cap_and_complete_usage(
    provider: str,
) -> None:
    captured: list[httpx2.Request] = []

    def handle(wire: httpx2.Request) -> httpx2.Response:
        captured.append(wire)
        return httpx2.Response(200, json=response(provider))

    result = await adapter(provider, httpx2.MockTransport(handle), timeout_seconds=10).request_once(
        request(), now=NOW
    )
    assert result.status == "response" and result.billing == "known"
    assert result.usage is not None and result.usage.output_tokens == 20
    assert result.usage.reasoning_tokens == 5 and len(captured) == 1
    body = json.loads(captured[0].content)
    assert KEY not in str(captured[0].url) and KEY not in captured[0].content.decode()
    if provider == "openai":
        assert captured[0].url.path == "/v1/responses" and body["model"] == "fixture-model"
        assert body["max_output_tokens"] == 64 and body["text"]["format"]["type"] == "json_schema"
    else:
        assert captured[0].url.path.endswith("/models/fixture-model:generateContent")
        assert body["generationConfig"]["maxOutputTokens"] == 64
        assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert KEY not in result.model_dump_json() and KEY not in request().model_dump_json()


@pytest.mark.parametrize("provider", ["openai", "google"])
@pytest.mark.parametrize(
    "broken",
    [
        "missing",
        "negative",
        "bool",
        "string",
        "total",
        "write",
        "model",
        "missing_reasoning",
        "unsupported_cache",
    ],
)
async def test_wire_usage_never_uses_sdk_default_zero_or_unsupported_billing(
    provider: str, broken: str
) -> None:
    body = response(provider)
    usage_key = "usage" if provider == "openai" else "usageMetadata"
    usage = body[usage_key]
    assert isinstance(usage, dict)
    if broken == "missing":
        body.pop(usage_key)
    if broken in {"negative", "bool", "string"}:
        usage["input_tokens" if provider == "openai" else "promptTokenCount"] = {
            "negative": -1,
            "bool": True,
            "string": "100",
        }[broken]
    if broken == "total":
        usage["total_tokens" if provider == "openai" else "totalTokenCount"] = 999
    if broken == "write":
        if provider == "openai":
            usage["input_tokens_details"] = {"cached_tokens": 0, "cache_write_tokens": 1}
        else:
            usage["toolUsePromptTokenCount"] = 1
    if broken == "model":
        body["model" if provider == "openai" else "modelVersion"] = "another-model"
    if broken == "missing_reasoning":
        if provider == "openai":
            usage["output_tokens_details"] = {}
        else:
            usage.pop("thoughtsTokenCount")
    if broken == "unsupported_cache":
        if provider == "openai":
            usage["input_tokens_details"] = {"cached_tokens": 1, "cache_write_tokens": 0}
        else:
            usage["cachedContentTokenCount"] = 1
    count = 0

    def handle(_: httpx2.Request) -> httpx2.Response:
        nonlocal count
        count += 1
        return httpx2.Response(200, json=body)

    result = await adapter(provider, httpx2.MockTransport(handle), timeout_seconds=10).request_once(
        request(), now=NOW
    )
    assert result.status == "failed" and result.billing == "unknown" and result.usage is None
    assert count == 1


@pytest.mark.parametrize("provider", ["openai", "google"])
@pytest.mark.parametrize("failure", ["429", "timeout", "json"])
async def test_transient_or_malformed_failure_has_one_wire_attempt_and_unknown_hold(
    provider: str, failure: str
) -> None:
    count = 0

    def handle(wire: httpx2.Request) -> httpx2.Response:
        nonlocal count
        count += 1
        if failure == "timeout":
            raise httpx2.ReadTimeout("fixture timeout", request=wire)
        if failure == "json":
            return httpx2.Response(200, content=b"not-json")
        return httpx2.Response(429, json={"error": {"message": "offline busy", "code": 429}})

    result = await adapter(provider, httpx2.MockTransport(handle), timeout_seconds=10).request_once(
        request(), now=NOW
    )
    assert result.status == "failed" and result.billing == "unknown" and count == 1


@pytest.mark.parametrize("provider", ["openai", "google"])
async def test_cancelled_model_call_preserves_unknown_billing_and_cancellation(
    provider: str,
) -> None:
    entered = asyncio.Event()
    count = 0

    async def handle(_: httpx2.Request) -> httpx2.Response:
        nonlocal count
        count += 1
        entered.set()
        await asyncio.Event().wait()
        return httpx2.Response(200, json=response(provider))

    task = asyncio.create_task(
        adapter(provider, httpx2.MockTransport(handle)).request_once(request(), now=NOW)
    )
    await asyncio.wait_for(entered.wait(), timeout=5)
    task.cancel()
    with pytest.raises(ModelRequestCancelledError) as caught:
        await task
    assert caught.value.result.billing == "unknown" and count == 1


@pytest.mark.parametrize("denial", ["denied", "wrong", "duplicate"])
async def test_required_trusted_one_time_exact_claim_precedes_any_provider_request(
    denial: str,
) -> None:
    count = 0

    def handle(_: httpx2.Request) -> httpx2.Response:
        nonlocal count
        count += 1
        return httpx2.Response(200, json=response("openai"))

    authority = Authorizer(denied=denial == "denied", wrong=denial == "wrong")
    calls = adapter(
        "openai",
        httpx2.MockTransport(handle),
        authority,
        timeout_seconds=10 if denial == "duplicate" else 1,
    )
    if denial == "duplicate":
        assert (await calls.request_once(request(), now=NOW)).billing == "known"
    result = await calls.request_once(request(), now=NOW)
    assert result.status == "denied" and result.billing == "not_issued"
    assert count == (1 if denial == "duplicate" else 0)


@pytest.mark.parametrize("ref", ["https://remote.invalid/schema", "file:///private/schema"])
def test_remote_schema_references_are_rejected_without_retrieval(
    ref: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import urllib.request

    def no_http(*_: object, **__: object) -> None:
        raise AssertionError("schema validation must not retrieve remote content")

    monkeypatch.setattr(urllib.request, "urlopen", no_http)
    monkeypatch.setattr(httpx2, "get", no_http)
    with pytest.raises(ValidationError):
        JsonSchemaDocument(schema_json=json.dumps({"type": "object", "$ref": ref}))


@pytest.mark.parametrize("provider", ["openai", "google"])
async def test_function_calls_are_returned_as_validated_proposals_never_executed(
    provider: str,
) -> None:
    body = response(provider)
    if provider == "openai":
        body["output"] = [
            {
                "id": "fc1",
                "type": "function_call",
                "name": "lookup",
                "call_id": "call1",
                "arguments": '{"key":"ready"}',
                "status": "completed",
            }
        ]
    else:
        body["candidates"] = [
            {
                "content": {
                    "role": "model",
                    "parts": [{"functionCall": {"name": "lookup", "args": {"key": "ready"}}}],
                },
                "finishReason": "STOP",
            }
        ]
    captured: list[httpx2.Request] = []

    def handle(wire: httpx2.Request) -> httpx2.Response:
        captured.append(wire)
        return httpx2.Response(200, json=body)

    tool = ModelTool(name="lookup", description="Read a bounded fact", parameters=TOOL_SCHEMA)
    result = await adapter(provider, httpx2.MockTransport(handle), timeout_seconds=10).request_once(
        request(output_schema=None, tools=(tool,)), now=NOW
    )
    assert result.status == "response" and len(result.tool_calls) == 1 and len(captured) == 1
    assert json.loads(result.tool_calls[0].arguments_json) == {"key": "ready"}


@pytest.mark.parametrize("provider", ["openai", "google"])
async def test_known_usage_is_retained_when_native_output_schema_is_invalid(provider: str) -> None:
    body = response(provider)
    if provider == "openai":
        body["output"] = [
            {
                "id": "m1",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": '{"result":12}', "annotations": []}],
            }
        ]
    else:
        body["candidates"] = [
            {
                "content": {"role": "model", "parts": [{"text": '{"result":12}'}]},
                "finishReason": "STOP",
            }
        ]
    result = await adapter(
        provider,
        httpx2.MockTransport(lambda _: httpx2.Response(200, json=body)),
        timeout_seconds=10,
    ).request_once(request(), now=NOW)
    assert result.status == "failed" and result.billing == "known" and result.usage is not None


@pytest.mark.parametrize("key", ["$dynamicRef", "$id"])
def test_other_remote_schema_identity_or_references_are_denied(key: str) -> None:
    with pytest.raises(ValidationError):
        JsonSchemaDocument(
            schema_json=json.dumps({"type": "object", key: "https://remote.invalid/data"})
        )


def test_local_schema_refs_work_without_network_and_missing_or_cycles_deny() -> None:
    schema = {
        "type": "object",
        "properties": {"result": {"$ref": "#/$defs/value"}},
        "$defs": {"value": {"type": "string"}},
        "required": ["result"],
    }
    valid = JsonSchemaDocument(schema_json=json.dumps(schema))
    assert json.loads(valid.validate_output('{"result":"ok"}')) == {"result": "ok"}
    for reference in ("#/$defs/missing", "#/$defs/value"):
        invalid = schema | {"$defs": {"value": {"$ref": reference}}}
        with pytest.raises(ValidationError):
            JsonSchemaDocument(schema_json=json.dumps(invalid))


@pytest.mark.parametrize(
    "updates",
    [
        {"base_url": "https://user:secret@offline.invalid"},
        {"api_key": "client-secret"},
        {"bounds": TokenBounds(input_tokens=0, max_output_tokens=64)},
        {"input_text": "😀" * 30000},
    ],
)
def test_request_rejects_client_config_or_unbounded_inputs(updates: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        request(**updates)


@pytest.mark.parametrize(
    "change",
    [
        {"registry_id": "unregistered"},
        {"registry_revision": "new-catalog"},
        {"price_version": "different-price"},
        {"data_classification": "confidential"},
        {"bounds": TokenBounds(input_tokens=1000, max_output_tokens=2001)},
        {"bounds": TokenBounds(input_tokens=9999, max_output_tokens=64)},
    ],
)
async def test_catalog_scope_and_bounds_denials_do_not_claim_or_send(
    change: dict[str, object],
) -> None:
    count = 0

    def handle(_: httpx2.Request) -> httpx2.Response:
        nonlocal count
        count += 1
        return httpx2.Response(200, json=response("openai"))

    authority = Authorizer()
    result = await adapter("openai", httpx2.MockTransport(handle), authority).request_once(
        request(**change), now=NOW
    )
    assert result.status == "denied" and result.billing == "not_issued"
    assert count == 0 and authority.claims == 0


@pytest.mark.parametrize("provider", ["openai", "google"])
async def test_unrequested_hosted_or_multimodal_response_preserves_unknown_billing(
    provider: str,
) -> None:
    body = response(provider)
    if provider == "openai":
        body["output"] = [{"type": "web_search_call", "id": "hosted-1"}]
    else:
        body["candidates"] = [
            {
                "content": {
                    "role": "model",
                    "parts": [{"inlineData": {"mimeType": "image/png", "data": "AA=="}}],
                }
            }
        ]
    result = await adapter(
        provider,
        httpx2.MockTransport(lambda _: httpx2.Response(200, json=body)),
        timeout_seconds=10,
    ).request_once(request(), now=NOW)
    assert result.status == "failed" and result.billing == "unknown"


@pytest.mark.parametrize("provider", ["openai", "google"])
async def test_credential_echo_is_rejected_without_serializing_it(provider: str) -> None:
    body = response(provider)
    text = json.dumps({"result": KEY})
    if provider == "openai":
        body["output"] = [
            {
                "type": "message",
                "id": "m1",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        ]
    else:
        body["candidates"] = [
            {"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": "STOP"}
        ]
    result = await adapter(
        provider,
        httpx2.MockTransport(lambda _: httpx2.Response(200, json=body)),
        timeout_seconds=10,
    ).request_once(request(), now=NOW)
    assert result.status == "failed" and result.billing == "known"
    assert KEY not in result.model_dump_json()


def test_schema_depth_and_nonfinite_json_are_rejected_before_processing() -> None:
    with pytest.raises(ValidationError):
        JsonSchemaDocument(schema_json='{"type":"object","const":NaN}')
    deep = '{"type":"object","properties":' + '{"node":' * 25 + "{}" + "}" * 25 + "}"
    with pytest.raises(ValidationError):
        JsonSchemaDocument(schema_json=deep)


async def test_credential_echo_in_tool_call_metadata_cannot_be_serialized() -> None:
    body = response("openai")
    body["output"] = [
        {
            "id": "fc1",
            "type": "function_call",
            "name": "lookup",
            "call_id": KEY,
            "arguments": '{"key":"ready"}',
            "status": "completed",
        }
    ]
    tool = ModelTool(name="lookup", description="Read a fact", parameters=TOOL_SCHEMA)
    result = await adapter(
        "openai",
        httpx2.MockTransport(lambda _: httpx2.Response(200, json=body)),
        timeout_seconds=10,
    ).request_once(request(output_schema=None, tools=(tool,)), now=NOW)
    assert result.status == "failed" and KEY not in result.model_dump_json()

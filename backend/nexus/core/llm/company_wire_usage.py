"""Validate actual response bytes before the SDK can replace absent usage with zero."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx2

from nexus.core.llm.company_pricing import TokenUsage
from nexus.core.llm.company_registry import ModelRegistration


def _object(value: object) -> dict[str, Any]:
    # SDK/provider JSON is dynamic; validate its shape before selecting known fields.
    if not isinstance(value, dict):
        raise ValueError("provider field must be an object")
    return value


def _integer(value: object) -> int:
    if type(value) is not int or value < 0 or value > 1_000_000_000:
        raise ValueError("provider token field must be an explicit bounded integer")
    return value


def _unsupported_units(fields: dict[str, Any], allowed: set[str]) -> None:
    for name, value in fields.items():
        if name not in allowed and value not in (None, 0):
            raise ValueError("provider reports unsupported billable units")


def _text_only_parts(body: dict[str, Any], provider: str) -> None:
    if provider == "openai":
        for item in body.get("output", []):
            if not isinstance(item, dict) or item.get("type") not in {
                "message",
                "function_call",
                "reasoning",
            }:
                raise ValueError("provider returned unsupported hosted/multimodal output")
            if item.get("type") == "message":
                for part in item.get("content", []):
                    if not isinstance(part, dict) or part.get("type") not in {
                        "output_text",
                        "refusal",
                    }:
                        raise ValueError("provider returned unsupported multimodal content")
    else:
        for candidate in body.get("candidates", []):
            for part in _object(candidate.get("content", {})).get("parts", []):
                if not isinstance(part, dict) or not set(part) <= {
                    "text",
                    "functionCall",
                    "thought",
                    "thoughtSignature",
                }:
                    raise ValueError("provider returned unsupported hosted/multimodal output")


def _openai(body: dict[str, Any]) -> TokenUsage:
    raw = _object(body.get("usage"))
    input_tokens, output_tokens = (
        _integer(raw.get("input_tokens")),
        _integer(raw.get("output_tokens")),
    )
    if _integer(raw.get("total_tokens")) != input_tokens + output_tokens:
        raise ValueError("provider total is inconsistent")
    inputs, outputs = (
        _object(raw.get("input_tokens_details")),
        _object(raw.get("output_tokens_details")),
    )
    _unsupported_units(
        raw,
        {
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "input_tokens_details",
            "output_tokens_details",
        },
    )
    _unsupported_units(inputs, {"cached_tokens", "cache_write_tokens"})
    _unsupported_units(outputs, {"reasoning_tokens"})
    if _integer(inputs.get("cache_write_tokens", 0)):
        raise ValueError("cache write billing is unsupported")
    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_input_tokens=_integer(inputs.get("cached_tokens")),
        reasoning_tokens=_integer(outputs.get("reasoning_tokens")),
    )


def _google(body: dict[str, Any]) -> TokenUsage:
    raw = _object(body.get("usageMetadata"))
    inputs = _integer(raw.get("promptTokenCount"))
    candidates, thoughts = (
        _integer(raw.get("candidatesTokenCount")),
        _integer(raw.get("thoughtsTokenCount")),
    )
    if _integer(raw.get("totalTokenCount")) != inputs + candidates + thoughts:
        raise ValueError("provider total is inconsistent")
    if _integer(raw.get("toolUsePromptTokenCount", 0)):
        raise ValueError("hosted tool prompt billing is unsupported")
    _unsupported_units(
        raw,
        {
            "promptTokenCount",
            "candidatesTokenCount",
            "thoughtsTokenCount",
            "totalTokenCount",
            "cachedContentTokenCount",
            "toolUsePromptTokenCount",
        },
    )
    return TokenUsage(
        input_tokens=inputs,
        output_tokens=candidates + thoughts,
        cached_input_tokens=_integer(raw.get("cachedContentTokenCount")),
        reasoning_tokens=thoughts,
    )


@dataclass(slots=True)
class WireObserver:
    """Per-call wire observation only, not a persistent reservation or billing receipt."""

    model: ModelRegistration
    usage: TokenUsage | None = None
    error_code: str | None = None

    async def observe(self, response: httpx2.Response) -> None:
        """Reject malformed/unsupported usage before normal provider SDK decoding."""
        if not 200 <= response.status_code < 300:
            return
        try:
            content = await response.aread()
            if len(content) > 2_000_000:
                raise ValueError("provider response exceeds byte allowance")
            body = _object(json.loads(content))
            resolved = body.get("model" if self.model.provider == "openai" else "modelVersion")
            if resolved != self.model.model_id:
                raise ValueError("unregistered resolved model/alias")
            _text_only_parts(body, self.model.provider)
            self.usage = _openai(body) if self.model.provider == "openai" else _google(body)
            price = self.model.price
            if price is None or (
                self.usage.cached_input_tokens and price.cache_semantics == "none"
            ):
                raise ValueError("cached usage has no supported price semantics")
            if self.usage.reasoning_tokens and price.reasoning_semantics != "included_in_output":
                raise ValueError("reasoning usage has no supported price semantics")
        except (ValueError, TypeError, KeyError) as exc:
            self.usage = None
            self.error_code = "invalid_usage"
            raise ValueError("provider response has no supported complete usage") from exc

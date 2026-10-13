"""Provider factory migration preserves endpoint, model name and API-family binding."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from pydantic_ai.providers.google import GoogleProvider

from nexus.core.llm.factory import resolve_model
from nexus.settings import settings


@pytest.fixture(autouse=True)
def offline_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure fixture-only keys and make an accidental network call fail."""
    for name in ("openai_api_key", "google_api_key", "cerebras_api_key", "openrouter_api_key"):
        monkeypatch.setattr(settings, name, "nexus-offline-fixture-not-a-real-key")
    monkeypatch.setattr(settings, "openai_compat_api_key", "")
    monkeypatch.setattr(
        httpx.AsyncClient, "request", AsyncMock(side_effect=AssertionError("Network forbidden"))
    )


@pytest.mark.parametrize("name", ["gpt-4o", "openai:gpt-4o", "openai-chat:gpt-4o", "o3-mini"])
def test_legacy_openai_resolution_keeps_chat_completions(name: str) -> None:
    model = resolve_model(name)
    assert isinstance(model, OpenAIChatModel)
    assert not isinstance(model, OpenAIResponsesModel)
    assert model.model_name == name.removeprefix("openai:").removeprefix("openai-chat:")


def test_explicit_responses_prefix_selects_responses_api() -> None:
    model = resolve_model("openai-responses:gpt-4o")
    assert isinstance(model, OpenAIResponsesModel)
    assert not isinstance(model, OpenAIChatModel)
    assert model.model_name == "gpt-4o"


@pytest.mark.parametrize(
    "configured, expected",
    [
        ("openai-compat:fixture-model", "fixture-model"),
        ("ollama:llama3", "llama3"),
        ("cerebras:llama-3.3-70b", "llama-3.3-70b"),
        ("openrouter:openai/gpt-4o-mini", "openai/gpt-4o-mini"),
    ],
)
def test_compatible_endpoints_remain_chat_models(configured: str, expected: str) -> None:
    model = resolve_model(configured)
    assert isinstance(model, OpenAIChatModel)
    assert model.model_name == expected


@pytest.mark.parametrize(
    "configured",
    [
        "gemini-2.0-flash",
        "gemini:gemini-2.0-flash",
        "google:gemini-2.0-flash",
        "google-gla:gemini-2.0-flash",
    ],
)
def test_google_resolution_keeps_developer_key_provider(configured: str) -> None:
    model = resolve_model(configured)
    assert isinstance(model, GoogleModel)
    assert model.model_name == "gemini-2.0-flash"
    assert isinstance(model._provider, GoogleProvider)


@pytest.mark.parametrize("name", ["openai:gpt-4o", "openai-chat:gpt-4o", "openai-responses:gpt-4o"])
def test_all_openai_api_families_require_configured_key(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "openai_api_key", "")
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        resolve_model(name)


@pytest.mark.parametrize("name", ["gemini-2.0-flash", "google:gemini-2.0-flash"])
def test_google_resolver_requires_configured_developer_key(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "google_api_key", "")
    with pytest.raises(ValueError, match="GOOGLE_API_KEY"):
        resolve_model(name)

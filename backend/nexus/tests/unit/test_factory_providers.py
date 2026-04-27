"""Tests for new free-tier providers in the LLM model factory.

Cerebras and OpenRouter are OpenAI-compatible — these tests verify the
prefix dispatch, key validation, and the OpenRouter free-SKU allowlist
warning behaviour without making real network calls.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from nexus.core.llm.factory import (
    _PROVIDER_RESOLVERS,
    _resolve_cerebras,
    _resolve_openrouter,
    resolve_model,
)


@pytest.fixture
def with_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set non-empty test keys for both new providers."""
    from nexus.settings import settings

    monkeypatch.setattr(settings, "cerebras_api_key", "test-cerebras-key")
    monkeypatch.setattr(settings, "openrouter_api_key", "test-openrouter-key")


def test_cerebras_prefix_registered() -> None:
    """The cerebras: prefix must be wired into the dispatch table."""
    prefixes = [p for p, _ in _PROVIDER_RESOLVERS]
    assert "cerebras:" in prefixes


def test_openrouter_prefix_registered() -> None:
    """The openrouter: prefix must be wired into the dispatch table."""
    prefixes = [p for p, _ in _PROVIDER_RESOLVERS]
    assert "openrouter:" in prefixes


def test_cerebras_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolver fails fast (with helpful message) when CEREBRAS_API_KEY is unset."""
    from nexus.settings import settings

    monkeypatch.setattr(settings, "cerebras_api_key", "")
    with pytest.raises(ValueError, match="CEREBRAS_API_KEY"):
        _resolve_cerebras("cerebras:llama-3.3-70b")


def test_openrouter_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolver fails fast when OPENROUTER_API_KEY is unset."""
    from nexus.settings import settings

    monkeypatch.setattr(settings, "openrouter_api_key", "")
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        _resolve_openrouter("openrouter:deepseek/deepseek-chat-v3:free")


def test_cerebras_resolves_to_openai_model(with_keys: None) -> None:
    """Cerebras returns an OpenAI-compatible Model instance pointed at the right base URL."""
    from nexus.settings import settings

    model = _resolve_cerebras("cerebras:llama-3.3-70b")
    # pydantic-ai's OpenAIModel exposes the underlying model identifier.
    assert getattr(model, "model_name", None) == "llama-3.3-70b"
    # Provider must default to the Cerebras endpoint
    assert settings.cerebras_base_url == "https://api.cerebras.ai/v1"


def test_openrouter_resolves_for_allowlisted_free_model(
    with_keys: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An allowlisted :free SKU must not emit the off-allowlist warning."""
    import logging

    caplog.set_level(logging.WARNING, logger="nexus.core.llm.factory")
    _resolve_openrouter("openrouter:deepseek/deepseek-chat-v3:free")
    # No off-allowlist warning should appear.
    messages = [r.message for r in caplog.records]
    assert not any("off_allowlist" in m for m in messages), messages


def test_openrouter_warns_for_off_allowlist_free_model(
    with_keys: None,
) -> None:
    """An unverified :free SKU emits a structured warning but still resolves."""
    with patch("nexus.core.llm.factory.logger") as mock_logger:
        _resolve_openrouter("openrouter:google/gemma-3-27b:free")
        # The factory uses structlog .warning(event_name, **kwargs) — assert the
        # canonical event name was recorded.
        warn_events = [
            call.args[0] for call in mock_logger.warning.call_args_list if call.args
        ]
        assert "openrouter_free_model_off_allowlist" in warn_events


def test_openrouter_no_warning_for_paid_model(with_keys: None) -> None:
    """Paid models (no :free suffix) bypass the allowlist check entirely."""
    with patch("nexus.core.llm.factory.logger") as mock_logger:
        _resolve_openrouter("openrouter:openai/gpt-4o-mini")
        warn_events = [
            call.args[0] for call in mock_logger.warning.call_args_list if call.args
        ]
        assert "openrouter_free_model_off_allowlist" not in warn_events


def test_resolve_model_dispatches_cerebras(with_keys: None) -> None:
    """End-to-end: resolve_model picks the cerebras resolver for cerebras: prefixes."""
    model = resolve_model("cerebras:llama-3.3-70b")
    assert model is not None


def test_resolve_model_dispatches_openrouter(with_keys: None) -> None:
    """End-to-end: resolve_model picks the openrouter resolver for openrouter: prefixes."""
    model = resolve_model("openrouter:deepseek/deepseek-chat-v3:free")
    assert model is not None


def test_provider_extraction_for_new_providers() -> None:
    """provider_health._extract_provider should map the new prefixes correctly."""
    from nexus.core.llm.provider_health import _extract_provider

    assert _extract_provider("cerebras:llama-3.3-70b") == "cerebras"
    assert _extract_provider("openrouter:deepseek/deepseek-chat-v3:free") == "openrouter"

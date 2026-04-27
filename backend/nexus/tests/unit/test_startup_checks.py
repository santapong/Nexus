"""Tests for startup-time provider detection in app.py.

Without at least one configured LLM provider, no agent can run a task.
The detection helper drives the startup gate that hard-fails the API in
that case, so its boundaries deserve explicit coverage.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def clean_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wipe every LLM-related setting to a known empty state."""
    from nexus.settings import settings

    for attr in (
        "anthropic_api_key",
        "google_api_key",
        "openai_api_key",
        "groq_api_key",
        "mistral_api_key",
        "openai_compat_api_key",
    ):
        monkeypatch.setattr(settings, attr, "")
    # Cerebras / OpenRouter only exist on branches that pulled in feat/llm —
    # set them defensively if the attribute is present.
    if hasattr(settings, "cerebras_api_key"):
        monkeypatch.setattr(settings, "cerebras_api_key", "")
    if hasattr(settings, "openrouter_api_key"):
        monkeypatch.setattr(settings, "openrouter_api_key", "")
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_COMPAT_BASE_URL", raising=False)


def test_detect_returns_empty_list_when_nothing_configured(clean_settings: None) -> None:
    from nexus.core.startup import detect_llm_providers

    assert detect_llm_providers() == []


def test_detect_picks_up_anthropic(
    clean_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.core.startup import detect_llm_providers
    from nexus.settings import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-test")
    assert detect_llm_providers() == ["anthropic"]


def test_detect_picks_up_groq_and_google(
    clean_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.core.startup import detect_llm_providers
    from nexus.settings import settings

    monkeypatch.setattr(settings, "groq_api_key", "gsk_test")
    monkeypatch.setattr(settings, "google_api_key", "AIza_test")
    available = detect_llm_providers()
    assert "google" in available
    assert "groq" in available


def test_detect_ignores_default_ollama_url(clean_settings: None) -> None:
    """Ollama's schema default is always populated — detection must not count it
    as available unless OLLAMA_BASE_URL is explicitly set in the env."""
    from nexus.core.startup import detect_llm_providers

    assert "ollama" not in detect_llm_providers()


def test_detect_picks_up_explicit_ollama(
    clean_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.core.startup import detect_llm_providers

    monkeypatch.setenv("OLLAMA_BASE_URL", "http://192.168.1.10:11434/v1")
    assert "ollama" in detect_llm_providers()


def test_detect_orders_results_stably(
    clean_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Order of providers is stable so structured logs remain diff-friendly."""
    from nexus.core.startup import detect_llm_providers
    from nexus.settings import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "x")
    monkeypatch.setattr(settings, "google_api_key", "y")
    monkeypatch.setattr(settings, "groq_api_key", "z")
    assert detect_llm_providers() == ["anthropic", "google", "groq"]


def test_detect_picks_up_cerebras_when_configured(
    clean_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cerebras is recognised when its setting is present and populated.

    Guarded with a hasattr check so the test still passes on branches
    that pre-date the cerebras_api_key setting (it just becomes a no-op
    rather than failing).
    """
    from nexus.core.startup import detect_llm_providers
    from nexus.settings import settings

    if not hasattr(settings, "cerebras_api_key"):
        pytest.skip("cerebras_api_key setting not present on this branch")

    monkeypatch.setattr(settings, "cerebras_api_key", "csk_test")
    assert "cerebras" in detect_llm_providers()


def test_detect_explicit_openai_compat(
    clean_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """openai-compat counts only when an API key OR an explicit base URL is set."""
    from nexus.core.startup import detect_llm_providers
    from nexus.settings import settings

    monkeypatch.setattr(settings, "openai_compat_api_key", "")
    assert "openai-compat" not in detect_llm_providers()

    monkeypatch.setenv("OPENAI_COMPAT_BASE_URL", "http://my-vllm:8000/v1")
    assert "openai-compat" in detect_llm_providers()

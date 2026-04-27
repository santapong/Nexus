"""Tests for the LLM preflight tool-calling validator."""

from __future__ import annotations

import pytest

from nexus.core.llm.preflight import PreflightOutcome, gather_role_models, probe_model


def test_gather_role_models_returns_unique_in_order() -> None:
    """The configured set of role+fallback models is enumerated, deduped, in order."""
    models = gather_role_models()

    assert len(models) > 0
    # No duplicates
    assert len(models) == len(set(models))
    # Every entry is a non-empty stripped string
    assert all(m and m == m.strip() for m in models)


def test_gather_role_models_includes_diversified_fallbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the operator diversifies fallbacks, every distinct entry shows up."""
    from nexus.settings import settings

    monkeypatch.setattr(settings, "model_ceo", "test:primary")
    monkeypatch.setattr(
        settings,
        "model_ceo_fallbacks",
        "cerebras:llama-3.3-70b,groq:llama-3.3-70b-versatile,gemini-2.5-flash",
    )
    models = gather_role_models()
    assert "test:primary" in models
    assert "cerebras:llama-3.3-70b" in models
    assert "groq:llama-3.3-70b-versatile" in models
    assert "gemini-2.5-flash" in models


@pytest.mark.asyncio
async def test_probe_model_returns_failure_when_resolver_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A model whose resolver raises (e.g. missing key) returns a failed PreflightOutcome."""
    from nexus.settings import settings

    monkeypatch.setattr(settings, "cerebras_api_key", "")

    outcome = await probe_model("cerebras:llama-3.3-70b", timeout_seconds=1.0)

    assert isinstance(outcome, PreflightOutcome)
    assert outcome.ok is False
    assert outcome.error is not None
    assert "resolve_failed" in outcome.error
    assert outcome.latency_ms >= 0


def test_preflight_outcome_serialises_to_dict() -> None:
    """PreflightOutcome.as_dict produces a JSON-friendly snapshot."""
    outcome = PreflightOutcome(
        model_name="cerebras:llama-3.3-70b",
        ok=True,
        latency_ms=123,
        error=None,
    )
    assert outcome.as_dict() == {
        "model_name": "cerebras:llama-3.3-70b",
        "ok": True,
        "latency_ms": 123,
        "error": None,
    }

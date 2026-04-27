"""Startup-time configuration detection helpers.

Lives outside ``nexus.app`` so unit tests can import these helpers without
running ``create_app()`` (which has unrelated side effects). The Litestar
``on_startup`` hook in ``nexus.app`` calls into this module.
"""

from __future__ import annotations

import os

from nexus.settings import settings


def detect_llm_providers() -> list[str]:
    """List the LLM providers that look configured.

    A provider counts when its API key is set. Self-hosted providers
    (Ollama, generic openai-compat) require an explicit opt-in via
    environment variable — their schema defaults are always populated
    so we can't infer intent from the value alone. Returns provider
    names in a stable order so structured logs are diff-friendly.
    """
    available: list[str] = []
    if settings.anthropic_api_key:
        available.append("anthropic")
    if settings.google_api_key:
        available.append("google")
    if settings.openai_api_key:
        available.append("openai")
    if settings.groq_api_key:
        available.append("groq")
    if settings.mistral_api_key:
        available.append("mistral")
    # Cerebras and OpenRouter only attach if their settings exist on this
    # branch — guarded with getattr so the helper works on older configs.
    if getattr(settings, "cerebras_api_key", ""):
        available.append("cerebras")
    if getattr(settings, "openrouter_api_key", ""):
        available.append("openrouter")
    # Ollama only counts when the operator has explicitly set OLLAMA_BASE_URL
    # in the environment — the schema default is populated even when Ollama
    # is not running, which would otherwise mask a "no providers at all"
    # misconfiguration.
    if os.environ.get("OLLAMA_BASE_URL"):
        available.append("ollama")
    # openai-compat opts in via either OPENAI_COMPAT_API_KEY or a non-default
    # base URL, since its schema default also points at localhost.
    if settings.openai_compat_api_key or os.environ.get("OPENAI_COMPAT_BASE_URL"):
        available.append("openai-compat")
    return available

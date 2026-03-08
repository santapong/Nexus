"""Universal model factory — provider-agnostic LLM resolution.

Supports any provider that pydantic-ai ships with: Anthropic (Claude),
Google (Gemini), OpenAI, Groq, Mistral, Ollama, and any OpenAI-compatible endpoint.

Agent code never references a specific provider. All resolution happens here.
All provider imports are lazy — only loaded when the provider is actually used.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from nexus.db.models import AgentRole
from nexus.settings import settings

if TYPE_CHECKING:
    from pydantic_ai.models import Model

logger = structlog.get_logger()

# Role -> model name mapping from settings
_AGENT_MODEL_MAP: dict[AgentRole, str] = {
    AgentRole.CEO: settings.model_ceo,
    AgentRole.ENGINEER: settings.model_engineer,
    AgentRole.ANALYST: settings.model_analyst,
    AgentRole.WRITER: settings.model_writer,
    AgentRole.QA: settings.model_qa,
    AgentRole.PROMPT_CREATOR: settings.model_prompt_creator,
}

# ─── Provider prefix → resolver ─────────────────────────────────────────────
#
# Each entry maps a model name prefix to a callable that creates the Model.
# Providers are resolved in registration order; first match wins.
# All imports are lazy (inside the function body) to avoid triggering
# ImportErrors for providers that aren't installed or have SDK version issues.
# Add new providers here — no changes needed anywhere else in the codebase.


def _resolve_anthropic(model_name: str) -> Model:
    api_key = settings.anthropic_api_key
    if not api_key:
        msg = f"ANTHROPIC_API_KEY required to use model '{model_name}'. Set it in .env."
        raise ValueError(msg)

    try:
        from pydantic_ai.models.anthropic import AnthropicModel
        from pydantic_ai.providers.anthropic import AnthropicProvider

        return AnthropicModel(model_name, provider=AnthropicProvider(api_key=api_key))
    except ImportError as exc:
        msg = (
            f"Cannot load Anthropic provider for '{model_name}'. "
            f"This is likely a version mismatch between pydantic-ai and anthropic SDK. "
            f"Run: pip install 'anthropic>=0.80.0,<0.83.0' to fix. Original error: {exc}"
        )
        raise ImportError(msg) from exc


def _resolve_gemini(model_name: str) -> Model:
    from pydantic_ai.models.gemini import GeminiModel
    from pydantic_ai.providers.google_gla import GoogleGLAProvider

    api_key = settings.google_api_key
    if not api_key:
        msg = f"GOOGLE_API_KEY required to use model '{model_name}'. Set it in .env."
        raise ValueError(msg)
    return GeminiModel(model_name, provider=GoogleGLAProvider(api_key=api_key))


def _resolve_openai(model_name: str) -> Model:
    from pydantic_ai.models.openai import OpenAIModel
    from pydantic_ai.providers.openai import OpenAIProvider

    name = model_name.removeprefix("openai:")
    api_key = settings.openai_api_key
    if not api_key:
        msg = f"OPENAI_API_KEY required to use model '{model_name}'. Set it in .env."
        raise ValueError(msg)
    return OpenAIModel(name, provider=OpenAIProvider(api_key=api_key))


def _resolve_groq(model_name: str) -> Model:
    from pydantic_ai.models.groq import GroqModel
    from pydantic_ai.providers.groq import GroqProvider

    name = model_name.removeprefix("groq:")
    api_key = settings.groq_api_key
    if not api_key:
        msg = f"GROQ_API_KEY required to use model '{model_name}'. Set it in .env."
        raise ValueError(msg)
    return GroqModel(name, provider=GroqProvider(api_key=api_key))


def _resolve_mistral(model_name: str) -> Model:
    from pydantic_ai.models.mistral import MistralModel
    from pydantic_ai.providers.mistral import MistralProvider

    name = model_name.removeprefix("mistral:")
    api_key = settings.mistral_api_key
    if not api_key:
        msg = f"MISTRAL_API_KEY required to use model '{model_name}'. Set it in .env."
        raise ValueError(msg)
    return MistralModel(name, provider=MistralProvider(api_key=api_key))


def _resolve_ollama(model_name: str) -> Model:
    """Ollama models via OpenAI-compatible API at a local endpoint."""
    from pydantic_ai.models.openai import OpenAIModel
    from pydantic_ai.providers.openai import OpenAIProvider

    name = model_name.removeprefix("ollama:")
    provider = OpenAIProvider(
        base_url=settings.ollama_base_url,
        api_key="ollama",
    )
    return OpenAIModel(name, provider=provider)


def _resolve_test(model_name: str) -> Model:  # noqa: ARG001
    """Test model for stress testing and CI — no API calls, deterministic output."""
    from pydantic_ai.models.test import TestModel

    return TestModel()


def _resolve_openai_compatible(model_name: str) -> Model:
    """Any OpenAI-compatible API (LiteLLM, vLLM, LocalAI, etc.).

    Format: "openai-compat:<model_name>"
    Uses OPENAI_COMPAT_BASE_URL and OPENAI_COMPAT_API_KEY from settings.
    """
    from pydantic_ai.models.openai import OpenAIModel
    from pydantic_ai.providers.openai import OpenAIProvider

    name = model_name.removeprefix("openai-compat:")
    provider = OpenAIProvider(
        base_url=settings.openai_compat_base_url,
        api_key=settings.openai_compat_api_key or "no-key",
    )
    return OpenAIModel(name, provider=provider)


# Ordered prefix → resolver map. First match wins.
_PROVIDER_RESOLVERS: list[tuple[str, Any]] = [
    ("test:", _resolve_test),
    ("claude", _resolve_anthropic),
    ("gemini", _resolve_gemini),
    ("openai-compat:", _resolve_openai_compatible),
    ("openai:", _resolve_openai),
    ("gpt-", _resolve_openai),
    ("o1-", _resolve_openai),
    ("o3-", _resolve_openai),
    ("groq:", _resolve_groq),
    ("mistral:", _resolve_mistral),
    ("ollama:", _resolve_ollama),
]


def resolve_model(model_name: str) -> Model:
    """Resolve a model name string to a pydantic-ai Model instance.

    Checks prefixes in order against the provider registry.
    This is the single point where provider-specific imports happen.

    Args:
        model_name: Model identifier string (e.g. "claude-sonnet-4-20250514",
            "gemini-2.0-flash", "openai:gpt-4o", "groq:llama-3.3-70b",
            "ollama:llama3", "openai-compat:my-model").

    Returns:
        A configured pydantic-ai Model instance.

    Raises:
        ValueError: If no provider matches the model name.
    """
    for prefix, resolver in _PROVIDER_RESOLVERS:
        if model_name.startswith(prefix):
            return resolver(model_name)  # type: ignore[no-any-return]

    msg = (
        f"Unknown model provider for '{model_name}'. "
        f"Supported prefixes: {[p for p, _ in _PROVIDER_RESOLVERS]}. "
        f"Use 'openai-compat:' prefix for custom OpenAI-compatible endpoints."
    )
    raise ValueError(msg)


class ModelFactory:
    """Creates Pydantic AI model instances based on agent role.

    No agent code references a specific provider directly.
    All provider resolution is handled by resolve_model().
    """

    @staticmethod
    def get_model(role: AgentRole, override: str | None = None) -> Model:
        """Get the appropriate LLM model for an agent role.

        Args:
            role: The agent's role determining which model to use.
            override: Optional model name to override the default.

        Returns:
            A Pydantic AI model instance.
        """
        model_name = override or _AGENT_MODEL_MAP[role]

        logger.debug(
            "model_resolved",
            role=role.value,
            model_name=model_name,
            overridden=override is not None,
        )

        return resolve_model(model_name)

    @staticmethod
    def get_model_by_name(model_name: str) -> Model:
        """Resolve a model directly by name, bypassing role mapping.

        Useful for ad-hoc LLM calls (embeddings, evals, etc.)
        that are not tied to a specific agent role.

        Args:
            model_name: Model identifier string.

        Returns:
            A configured pydantic-ai Model instance.
        """
        return resolve_model(model_name)

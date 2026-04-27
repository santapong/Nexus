"""Pre-flight validation for free-tier LLM providers.

Before UAT relies on a free model in a fallback chain, we issue a single
function-calling probe to confirm the model actually returns structured
output. Many ``:free`` SKUs on OpenRouter advertise tool support but
silently break Pydantic AI parsing (Pydantic AI #2976: Gemma, Phi, etc.),
which only surfaces at runtime when an agent task fails.

This module is intended for:
- ``make verify-models`` style operator scripts before launching UAT
- /health probes that gate "ready for traffic" status

It is *not* called on the hot path — runtime errors are still handled by
the circuit breaker and FallbackModel chain.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import perf_counter
from typing import Any

import structlog
from pydantic import BaseModel, Field

from nexus.core.llm.factory import resolve_model

logger = structlog.get_logger()


class _PingResult(BaseModel):
    """Schema the probe asks the model to return.

    Forces the model to emit a structured response with a known field — if
    Pydantic AI parsing fails we know the model can't be used as an agent.
    """

    ok: bool = Field(description="Always set to true to confirm structured output works")
    echo: str = Field(description="Echo back the word 'pong'")


@dataclass(frozen=True)
class PreflightOutcome:
    """Result of a pre-flight probe for one model."""

    model_name: str
    ok: bool
    latency_ms: int
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "ok": self.ok,
            "latency_ms": self.latency_ms,
            "error": self.error,
        }


async def probe_model(model_name: str, *, timeout_seconds: float = 20.0) -> PreflightOutcome:
    """Issue a single tool-calling probe at ``model_name``.

    The probe asks the model for a structured _PingResult. A model that
    cannot emit valid structured output — common on free-tier SKUs that
    nominally support tools — will fail with a parsing error rather than
    a quota error, telling us up front it's unfit for agent duty.

    Args:
        model_name: Any model string ``resolve_model`` understands.
        timeout_seconds: Hard cap on the probe call.

    Returns:
        PreflightOutcome with success, latency, and any error.
    """
    from pydantic_ai import Agent

    start = perf_counter()
    try:
        model = resolve_model(model_name)
    except (ValueError, ImportError) as exc:
        return PreflightOutcome(
            model_name=model_name,
            ok=False,
            latency_ms=int((perf_counter() - start) * 1000),
            error=f"resolve_failed: {exc}",
        )

    agent = Agent[None, _PingResult](
        model,
        output_type=_PingResult,
        system_prompt=(
            "You are a connectivity probe. When asked to ping, respond with "
            "structured output {ok: true, echo: 'pong'} and nothing else."
        ),
    )

    try:
        result = await asyncio.wait_for(agent.run("ping"), timeout=timeout_seconds)
    except TimeoutError:
        return PreflightOutcome(
            model_name=model_name,
            ok=False,
            latency_ms=int((perf_counter() - start) * 1000),
            error=f"timeout after {timeout_seconds}s",
        )
    except Exception as exc:  # noqa: BLE001 — capture anything from the SDK
        return PreflightOutcome(
            model_name=model_name,
            ok=False,
            latency_ms=int((perf_counter() - start) * 1000),
            error=f"{type(exc).__name__}: {exc}"[:300],
        )

    latency_ms = int((perf_counter() - start) * 1000)
    output = getattr(result, "output", None) or getattr(result, "data", None)

    if not isinstance(output, _PingResult) or not output.ok:
        return PreflightOutcome(
            model_name=model_name,
            ok=False,
            latency_ms=latency_ms,
            error=f"invalid_structured_output: {output!r}",
        )

    return PreflightOutcome(model_name=model_name, ok=True, latency_ms=latency_ms)


async def probe_models(
    model_names: list[str],
    *,
    timeout_seconds: float = 20.0,
    concurrency: int = 4,
) -> list[PreflightOutcome]:
    """Probe a list of models concurrently and return all outcomes."""
    semaphore = asyncio.Semaphore(concurrency)

    async def _bounded(name: str) -> PreflightOutcome:
        async with semaphore:
            return await probe_model(name, timeout_seconds=timeout_seconds)

    return await asyncio.gather(*(_bounded(n) for n in model_names))


def gather_role_models() -> list[str]:
    """Collect every model name configured across all role + fallback settings.

    De-duplicated, in declaration order. Used by the operator probe script to
    exercise everything the system might fall back onto.
    """
    from nexus.settings import settings

    seen: list[str] = []
    fields = [
        settings.model_ceo,
        settings.model_director,
        settings.model_engineer,
        settings.model_analyst,
        settings.model_writer,
        settings.model_qa,
        settings.model_prompt_creator,
        settings.model_ceo_fallbacks,
        settings.model_director_fallbacks,
        settings.model_engineer_fallbacks,
        settings.model_analyst_fallbacks,
        settings.model_writer_fallbacks,
        settings.model_qa_fallbacks,
        settings.model_prompt_creator_fallbacks,
    ]
    for raw in fields:
        for name in raw.split(","):
            stripped = name.strip()
            if stripped and stripped not in seen:
                seen.append(stripped)
    return seen

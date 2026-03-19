"""OpenTelemetry distributed tracing for NEXUS.

Provides trace context propagation across Kafka → agent → tools → LLM calls.
Replaces structured-logs-only observability with proper distributed traces.

Degrades gracefully — if OTel is not configured, all trace operations are no-ops.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from contextlib import asynccontextmanager, contextmanager
from typing import Any

import structlog

from nexus.settings import settings

logger = structlog.get_logger()

# Lazy imports — only load OpenTelemetry if configured
_tracer_provider = None
_initialized = False


def _ensure_initialized() -> bool:
    """Initialize OpenTelemetry SDK if configured. Returns True if active."""
    global _tracer_provider, _initialized

    if _initialized:
        return _tracer_provider is not None

    _initialized = True

    if not settings.otel_exporter_endpoint:
        logger.info("otel_disabled", reason="No OTEL_EXPORTER_ENDPOINT configured")
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({
            "service.name": settings.otel_service_name,
            "service.version": "0.6.0",
            "deployment.environment": settings.app_env,
        })

        exporter = OTLPSpanExporter(
            endpoint=settings.otel_exporter_endpoint,
        )

        _tracer_provider = TracerProvider(resource=resource)
        _tracer_provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(_tracer_provider)

        logger.info(
            "otel_initialized",
            endpoint=settings.otel_exporter_endpoint,
            service=settings.otel_service_name,
        )
        return True

    except Exception as exc:
        logger.warning("otel_init_failed", error=str(exc))
        _tracer_provider = None
        return False


def get_tracer(name: str = "nexus") -> Any:
    """Get an OpenTelemetry tracer instance.

    Returns a real tracer if OTel is configured, otherwise a no-op tracer.

    Args:
        name: Tracer name (typically module name).

    Returns:
        An OpenTelemetry Tracer or NoOpTracer.
    """
    if _ensure_initialized() and _tracer_provider is not None:
        from opentelemetry import trace

        return trace.get_tracer(name)

    return _NoOpTracer()


class _NoOpSpan:
    """No-op span that does nothing when OTel is not configured."""

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def set_status(self, status: Any, description: str | None = None) -> None:
        pass

    def record_exception(self, exception: Exception) -> None:
        pass

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        pass

    def end(self) -> None:
        pass

    def __enter__(self) -> _NoOpSpan:
        return self

    def __exit__(self, *args: Any) -> None:
        pass


class _NoOpTracer:
    """No-op tracer that returns no-op spans."""

    def start_span(self, name: str, **kwargs: Any) -> _NoOpSpan:
        return _NoOpSpan()

    def start_as_current_span(self, name: str, **kwargs: Any) -> _NoOpSpan:
        return _NoOpSpan()


@asynccontextmanager
async def trace_agent_task(
    agent_role: str,
    task_id: str,
    trace_id: str,
):
    """Context manager for tracing an agent task execution.

    Creates a span covering the entire task lifecycle with standard attributes.

    Args:
        agent_role: The executing agent's role.
        task_id: The task being executed.
        trace_id: The trace/correlation ID.

    Yields:
        The active span (real or no-op).
    """
    tracer = get_tracer("nexus.agents")
    span = tracer.start_span(
        f"agent.{agent_role}.handle_task",
        attributes={
            "nexus.agent.role": agent_role,
            "nexus.task.id": task_id,
            "nexus.trace.id": trace_id,
        },
    )
    try:
        yield span
    except Exception as exc:
        span.record_exception(exc)
        if _ensure_initialized():
            from opentelemetry.trace import StatusCode

            span.set_status(StatusCode.ERROR, str(exc))
        raise
    finally:
        span.end()


@asynccontextmanager
async def trace_llm_call(
    model_name: str,
    agent_role: str,
    task_id: str,
):
    """Context manager for tracing an LLM API call.

    Args:
        model_name: The LLM model being called.
        agent_role: The agent making the call.
        task_id: The associated task.

    Yields:
        The active span.
    """
    tracer = get_tracer("nexus.llm")
    span = tracer.start_span(
        f"llm.call.{model_name}",
        attributes={
            "nexus.llm.model": model_name,
            "nexus.agent.role": agent_role,
            "nexus.task.id": task_id,
        },
    )
    try:
        yield span
    except Exception as exc:
        span.record_exception(exc)
        raise
    finally:
        span.end()


@asynccontextmanager
async def trace_tool_call(
    tool_name: str,
    agent_role: str,
    task_id: str,
):
    """Context manager for tracing a tool execution.

    Args:
        tool_name: The tool being called.
        agent_role: The agent using the tool.
        task_id: The associated task.

    Yields:
        The active span.
    """
    tracer = get_tracer("nexus.tools")
    span = tracer.start_span(
        f"tool.{tool_name}",
        attributes={
            "nexus.tool.name": tool_name,
            "nexus.agent.role": agent_role,
            "nexus.task.id": task_id,
        },
    )
    try:
        yield span
    except Exception as exc:
        span.record_exception(exc)
        raise
    finally:
        span.end()


@asynccontextmanager
async def trace_kafka_consume(
    topic: str,
    message_id: str,
    task_id: str,
):
    """Context manager for tracing Kafka message consumption.

    Args:
        topic: The Kafka topic consumed from.
        message_id: The message being processed.
        task_id: The associated task.

    Yields:
        The active span.
    """
    tracer = get_tracer("nexus.kafka")
    span = tracer.start_span(
        f"kafka.consume.{topic}",
        attributes={
            "messaging.system": "kafka",
            "messaging.destination": topic,
            "messaging.message_id": message_id,
            "nexus.task.id": task_id,
        },
    )
    try:
        yield span
    except Exception as exc:
        span.record_exception(exc)
        raise
    finally:
        span.end()


def traced(name: str | None = None) -> Callable:
    """Decorator for tracing async functions.

    Args:
        name: Optional span name (defaults to function name).

    Returns:
        Decorated function with automatic tracing.
    """

    def decorator(func: Callable) -> Callable:
        span_name = name or f"{func.__module__}.{func.__qualname__}"

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = get_tracer(func.__module__)
            span = tracer.start_span(span_name)
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as exc:
                span.record_exception(exc)
                raise
            finally:
                span.end()

        return wrapper

    return decorator


def shutdown() -> None:
    """Flush pending spans and shutdown the tracer provider."""
    global _tracer_provider
    if _tracer_provider is not None:
        _tracer_provider.shutdown()
        logger.info("otel_shutdown")

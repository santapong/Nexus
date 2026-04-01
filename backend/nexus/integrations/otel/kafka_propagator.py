"""Kafka trace context propagation for OpenTelemetry.

Injects and extracts W3C trace context (traceparent/tracestate) from
Kafka message headers so distributed traces span across agents.

When OTel is not configured, all operations are no-ops — zero overhead.
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger()

# W3C Trace Context header names
_TRACEPARENT_KEY = "traceparent"
_TRACESTATE_KEY = "tracestate"


def inject_trace_context(headers: dict[str, Any] | None = None) -> dict[str, Any]:
    """Inject current OTel trace context into Kafka message headers.

    Call this in the producer before publishing a message. If OTel is not
    configured, returns the headers dict unchanged (or empty dict).

    Args:
        headers: Existing message headers to extend.

    Returns:
        Headers dict with traceparent/tracestate injected if OTel is active.
    """
    if headers is None:
        headers = {}

    try:
        from nexus.integrations.otel.tracing import _ensure_initialized

        if not _ensure_initialized():
            return headers

        from opentelemetry import context, trace
        from opentelemetry.trace import format_span_id, format_trace_id

        span = trace.get_current_span()
        span_context = span.get_span_context()

        if span_context.is_valid:
            # Build W3C traceparent: version-trace_id-span_id-trace_flags
            traceparent = (
                f"00-{format_trace_id(span_context.trace_id)}"
                f"-{format_span_id(span_context.span_id)}"
                f"-{span_context.trace_flags:02x}"
            )
            headers[_TRACEPARENT_KEY] = traceparent

            tracestate = span_context.trace_state.to_header()
            if tracestate:
                headers[_TRACESTATE_KEY] = tracestate

    except Exception:
        # Never let tracing failures break message publishing
        pass

    return headers


def extract_trace_context(headers: dict[str, Any] | None) -> Any:
    """Extract OTel trace context from Kafka message headers.

    Call this in the consumer before processing a message. Returns an
    OTel context that can be used as parent for new spans.

    Args:
        headers: Message headers containing traceparent/tracestate.

    Returns:
        An OpenTelemetry Context with the extracted trace, or the current context.
    """
    try:
        from nexus.integrations.otel.tracing import _ensure_initialized

        if not _ensure_initialized() or not headers:
            from opentelemetry import context
            return context.get_current()

        from opentelemetry import context
        from opentelemetry.trace import TraceFlags
        from opentelemetry.trace.span import SpanContext, TraceState

        traceparent = headers.get(_TRACEPARENT_KEY)
        if not traceparent or not isinstance(traceparent, str):
            return context.get_current()

        # Parse W3C traceparent: version-trace_id-span_id-trace_flags
        parts = traceparent.split("-")
        if len(parts) != 4:
            return context.get_current()

        trace_id = int(parts[1], 16)
        span_id = int(parts[2], 16)
        trace_flags = TraceFlags(int(parts[3], 16))

        tracestate_header = headers.get(_TRACESTATE_KEY, "")
        trace_state = TraceState.from_header(
            [tracestate_header] if tracestate_header else []
        )

        span_context = SpanContext(
            trace_id=trace_id,
            span_id=span_id,
            is_remote=True,
            trace_flags=trace_flags,
            trace_state=trace_state,
        )

        from opentelemetry.trace import NonRecordingSpan, set_span_in_context

        parent_span = NonRecordingSpan(span_context)
        return set_span_in_context(parent_span)

    except Exception:
        # Gracefully degrade — return current context on any parsing error
        try:
            from opentelemetry import context
            return context.get_current()
        except Exception:
            return None

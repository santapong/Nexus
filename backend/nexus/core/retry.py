"""Configurable retry policy framework.

Provides retry strategies with exponential backoff, jitter, and
circuit breaker integration for all I/O operations in the system.

Enterprise-grade retry handling that prevents thundering herds,
respects rate limits, and integrates with observability.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

import structlog

logger = structlog.get_logger()

T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    """Configuration for retry behavior.

    Attributes:
        max_retries: Maximum number of retry attempts.
        base_delay: Initial delay in seconds before first retry.
        max_delay: Maximum delay cap in seconds.
        exponential_base: Multiplier for exponential backoff.
        jitter: Whether to add random jitter to prevent thundering herd.
        retryable_exceptions: Tuple of exception types that should trigger retry.
        non_retryable_exceptions: Exceptions that should NOT be retried.
    """

    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,)
    non_retryable_exceptions: tuple[type[Exception], ...] = ()


# ─── Pre-configured policies ───────────────────────────────────────────────

LLM_RETRY_POLICY = RetryPolicy(
    max_retries=5,
    base_delay=2.0,
    max_delay=45.0,
    exponential_base=2.0,
    jitter=True,
)

KAFKA_RETRY_POLICY = RetryPolicy(
    max_retries=3,
    base_delay=1.0,
    max_delay=30.0,
    exponential_base=2.0,
    jitter=True,
)

DB_RETRY_POLICY = RetryPolicy(
    max_retries=3,
    base_delay=0.5,
    max_delay=10.0,
    exponential_base=2.0,
    jitter=True,
)

REDIS_RETRY_POLICY = RetryPolicy(
    max_retries=3,
    base_delay=0.2,
    max_delay=5.0,
    exponential_base=2.0,
    jitter=True,
)


def _compute_delay(policy: RetryPolicy, attempt: int) -> float:
    """Compute the delay for a given retry attempt.

    Uses exponential backoff with optional jitter.

    Args:
        policy: The retry policy configuration.
        attempt: Zero-based attempt number.

    Returns:
        Delay in seconds.
    """
    delay = min(
        policy.base_delay * (policy.exponential_base ** attempt),
        policy.max_delay,
    )
    if policy.jitter:
        delay = delay * (0.5 + random.random() * 0.5)  # noqa: S311
    return delay


async def retry_async(
    fn: Callable[..., Awaitable[T]],
    *args: Any,
    policy: RetryPolicy = RetryPolicy(),
    operation_name: str = "operation",
    context: dict[str, Any] | None = None,
    **kwargs: Any,
) -> T:
    """Execute an async function with retry logic.

    Args:
        fn: The async function to execute.
        *args: Positional arguments for fn.
        policy: Retry policy to use.
        operation_name: Name for logging context.
        context: Additional context for logging.
        **kwargs: Keyword arguments for fn.

    Returns:
        The result of fn.

    Raises:
        The last exception if all retries are exhausted.
    """
    last_error: Exception | None = None
    log_ctx = context or {}

    for attempt in range(policy.max_retries + 1):
        try:
            return await fn(*args, **kwargs)
        except policy.non_retryable_exceptions as exc:
            # Don't retry these — raise immediately
            logger.warning(
                "non_retryable_error",
                operation=operation_name,
                error=str(exc),
                **log_ctx,
            )
            raise
        except policy.retryable_exceptions as exc:
            last_error = exc

            if attempt >= policy.max_retries:
                break

            delay = _compute_delay(policy, attempt)

            logger.warning(
                "retry_attempt",
                operation=operation_name,
                attempt=attempt + 1,
                max_retries=policy.max_retries,
                delay_seconds=round(delay, 2),
                error=str(exc),
                **log_ctx,
            )

            await asyncio.sleep(delay)

    logger.error(
        "retry_exhausted",
        operation=operation_name,
        max_retries=policy.max_retries,
        error=str(last_error),
        **log_ctx,
    )
    raise last_error  # type: ignore[misc]


def is_rate_limited(exc: Exception) -> bool:
    """Check if an exception indicates rate limiting.

    Args:
        exc: The exception to check.

    Returns:
        True if the exception is a rate limit error.
    """
    error_str = str(exc).lower()
    return "429" in error_str or "rate_limit" in error_str or "too many requests" in error_str

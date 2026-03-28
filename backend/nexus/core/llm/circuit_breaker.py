"""Circuit breaker for LLM provider calls — enterprise edition.

Prevents cascading failures when an LLM provider is down.
Each provider gets its own circuit breaker instance with:
- Sliding window failure tracking (not just consecutive failures)
- Health score computation (0.0 = dead, 1.0 = healthy)
- Latency tracking for performance monitoring
- Automatic recovery with half-open testing

States:
- CLOSED: normal operation, calls go through
- OPEN: provider failing, reject calls immediately (use fallback)
- HALF_OPEN: test with one call to see if provider recovered
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum

import structlog

logger = structlog.get_logger()

# Sliding window configuration
WINDOW_SIZE = 20  # Track last N calls
FAILURE_RATE_THRESHOLD = 0.5  # Open circuit if >50% failures in window
SLOW_CALL_THRESHOLD_MS = 10_000  # Calls slower than 10s are "slow"
SLOW_CALL_RATE_THRESHOLD = 0.8  # Open if >80% of calls are slow


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    """Raised when a circuit breaker is open and calls are rejected."""

    def __init__(self, provider: str, recovery_at: float) -> None:
        self.provider = provider
        self.recovery_at = recovery_at
        wait = max(0, int(recovery_at - time.monotonic()))
        super().__init__(f"Circuit open for {provider}, retry in {wait}s")


@dataclass
class CallRecord:
    """Record of a single call through the circuit breaker."""

    timestamp: float
    success: bool
    latency_ms: float
    error_type: str = ""


class CircuitBreaker:
    """Per-provider circuit breaker with sliding window and health scoring.

    Enterprise-grade circuit breaker that tracks:
    - Failure rate over a sliding window (not just consecutive failures)
    - Call latency for slow-call detection
    - Health score for monitoring and dashboards
    - Total call counts for analytics

    Args:
        provider: Provider identifier (e.g., 'anthropic', 'google').
        failure_threshold: Legacy: consecutive failures before opening.
        recovery_timeout: Seconds to wait before trying half-open.
        window_size: Number of recent calls to track for failure rate.
    """

    def __init__(
        self,
        provider: str,
        *,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        window_size: int = WINDOW_SIZE,
    ) -> None:
        self.provider = provider
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.window_size = window_size
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._success_count = 0
        self._total_calls = 0

        # Sliding window for enterprise health tracking
        self._window: deque[CallRecord] = deque(maxlen=window_size)
        self._last_state_change = time.monotonic()

    @property
    def state(self) -> CircuitState:
        """Current circuit state, checking for recovery timeout."""
        if self._state == CircuitState.OPEN and (
            time.monotonic() - self._last_failure_time >= self.recovery_timeout
        ):
            self._state = CircuitState.HALF_OPEN
            self._last_state_change = time.monotonic()
            logger.info(
                "circuit_half_open",
                provider=self.provider,
            )
        return self._state

    @property
    def health_score(self) -> float:
        """Compute provider health score from 0.0 (dead) to 1.0 (healthy).

        Factors:
        - Failure rate in sliding window (primary)
        - Slow call rate (secondary)
        - Current circuit state (tertiary)
        """
        if self._state == CircuitState.OPEN:
            return 0.0

        if not self._window:
            return 1.0  # No data = assume healthy

        # Failure rate component (weight: 0.6)
        failures = sum(1 for r in self._window if not r.success)
        failure_rate = failures / len(self._window)
        failure_score = max(0.0, 1.0 - (failure_rate * 2))  # 50% failures = 0.0

        # Slow call rate component (weight: 0.3)
        slow_calls = sum(1 for r in self._window if r.latency_ms > SLOW_CALL_THRESHOLD_MS)
        slow_rate = slow_calls / len(self._window)
        slow_score = max(0.0, 1.0 - slow_rate)

        # State component (weight: 0.1)
        state_score = 1.0 if self._state == CircuitState.CLOSED else 0.5

        return round(failure_score * 0.6 + slow_score * 0.3 + state_score * 0.1, 3)

    @property
    def failure_rate(self) -> float:
        """Current failure rate in the sliding window."""
        if not self._window:
            return 0.0
        failures = sum(1 for r in self._window if not r.success)
        return round(failures / len(self._window), 3)

    @property
    def avg_latency_ms(self) -> float:
        """Average latency of calls in the sliding window."""
        if not self._window:
            return 0.0
        return round(sum(r.latency_ms for r in self._window) / len(self._window), 1)

    def check(self) -> None:
        """Check if call is allowed. Raises CircuitOpenError if not.

        Raises:
            CircuitOpenError: If the circuit is open and calls are blocked.
        """
        current = self.state
        if current == CircuitState.OPEN:
            raise CircuitOpenError(
                self.provider,
                self._last_failure_time + self.recovery_timeout,
            )

    def record_success(self, latency_ms: float = 0.0) -> None:
        """Record a successful call.

        Args:
            latency_ms: Call latency in milliseconds.
        """
        self._total_calls += 1
        self._window.append(CallRecord(
            timestamp=time.monotonic(),
            success=True,
            latency_ms=latency_ms,
        ))

        if self._state == CircuitState.HALF_OPEN:
            logger.info(
                "circuit_closed",
                provider=self.provider,
                previous_failures=self._failure_count,
                health_score=self.health_score,
            )
            self._last_state_change = time.monotonic()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count += 1

    def record_failure(self, latency_ms: float = 0.0, error_type: str = "") -> None:
        """Record a failed call. Opens circuit if threshold exceeded.

        Args:
            latency_ms: Call latency in milliseconds.
            error_type: Type of error for analytics.
        """
        self._total_calls += 1
        self._failure_count += 1
        self._last_failure_time = time.monotonic()

        self._window.append(CallRecord(
            timestamp=time.monotonic(),
            success=False,
            latency_ms=latency_ms,
            error_type=error_type,
        ))

        # Check both consecutive failures AND sliding window failure rate
        should_open = (
            self._failure_count >= self.failure_threshold
            or (len(self._window) >= 5 and self.failure_rate > FAILURE_RATE_THRESHOLD)
        )

        if should_open and self._state != CircuitState.OPEN:
            self._state = CircuitState.OPEN
            self._last_state_change = time.monotonic()
            logger.warning(
                "circuit_opened",
                provider=self.provider,
                failure_count=self._failure_count,
                failure_rate=self.failure_rate,
                health_score=self.health_score,
                recovery_timeout=self.recovery_timeout,
                error_type=error_type,
            )

    def reset(self) -> None:
        """Manually reset the circuit breaker."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._window.clear()
        self._last_state_change = time.monotonic()

    def get_stats(self) -> dict[str, object]:
        """Get comprehensive stats for monitoring dashboards.

        Returns:
            Dict with health score, failure rate, latency, and state info.
        """
        return {
            "provider": self.provider,
            "state": self.state.value,
            "health_score": self.health_score,
            "failure_rate": self.failure_rate,
            "avg_latency_ms": self.avg_latency_ms,
            "total_calls": self._total_calls,
            "total_successes": self._success_count,
            "consecutive_failures": self._failure_count,
            "window_size": len(self._window),
            "seconds_in_state": round(time.monotonic() - self._last_state_change, 1),
        }


# ─── Global registry of circuit breakers per provider ─────────────────────────

_breakers: dict[str, CircuitBreaker] = {}


def get_breaker(provider: str) -> CircuitBreaker:
    """Get or create a circuit breaker for a provider.

    Args:
        provider: Provider name (e.g., 'anthropic', 'google', 'groq').

    Returns:
        The circuit breaker instance for this provider.
    """
    if provider not in _breakers:
        _breakers[provider] = CircuitBreaker(provider)
    return _breakers[provider]


def get_all_breaker_states() -> dict[str, str]:
    """Get state of all circuit breakers for health reporting."""
    return {name: breaker.state.value for name, breaker in _breakers.items()}


def get_all_breaker_stats() -> dict[str, dict[str, object]]:
    """Get comprehensive stats for all circuit breakers.

    Returns:
        Dict mapping provider name to stats dict.
    """
    return {name: breaker.get_stats() for name, breaker in _breakers.items()}


def get_system_health_score() -> float:
    """Compute overall system health from all provider health scores.

    Returns:
        Average health score across all providers (0.0 to 1.0).
    """
    if not _breakers:
        return 1.0
    scores = [b.health_score for b in _breakers.values()]
    return round(sum(scores) / len(scores), 3)

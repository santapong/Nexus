"""Circuit breaker for LLM provider calls.

Prevents cascading failures when an LLM provider is down.
Each provider gets its own circuit breaker instance.

States:
- CLOSED: normal operation, calls go through
- OPEN: provider failing, reject calls immediately (use fallback)
- HALF_OPEN: test with one call to see if provider recovered
"""

from __future__ import annotations

import time
from enum import StrEnum

import structlog

logger = structlog.get_logger()


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


class CircuitBreaker:
    """Per-provider circuit breaker with configurable thresholds.

    Args:
        provider: Provider identifier (e.g., 'anthropic', 'google').
        failure_threshold: Number of consecutive failures before opening.
        recovery_timeout: Seconds to wait before trying half-open.
    """

    def __init__(
        self,
        provider: str,
        *,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
    ) -> None:
        self.provider = provider
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._success_count = 0

    @property
    def state(self) -> CircuitState:
        """Current circuit state, checking for recovery timeout."""
        if self._state == CircuitState.OPEN:
            if time.monotonic() - self._last_failure_time >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                logger.info(
                    "circuit_half_open",
                    provider=self.provider,
                )
        return self._state

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

    def record_success(self) -> None:
        """Record a successful call. Resets failure count."""
        if self._state == CircuitState.HALF_OPEN:
            logger.info(
                "circuit_closed",
                provider=self.provider,
                previous_failures=self._failure_count,
            )
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count += 1

    def record_failure(self) -> None:
        """Record a failed call. Opens circuit if threshold exceeded."""
        self._failure_count += 1
        self._last_failure_time = time.monotonic()

        if self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            logger.warning(
                "circuit_opened",
                provider=self.provider,
                failure_count=self._failure_count,
                recovery_timeout=self.recovery_timeout,
            )

    def reset(self) -> None:
        """Manually reset the circuit breaker."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0


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

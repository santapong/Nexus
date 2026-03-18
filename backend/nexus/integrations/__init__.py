"""Pluggable external service integrations.

These services are optional — the system degrades gracefully when they're down.
Core infrastructure (Kafka, Redis, LLM) lives in nexus.core/.
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger()


class ServiceAvailability:
    """Tracks availability of optional external services.

    Agents and API endpoints check this before using optional services.
    Fallback behavior:
    - Temporal down → use Taskiq (default task queue)
    - KeepSave down → use env vars for secrets
    - Eval (LangFuse) down → skip quality scoring
    """

    temporal_available: bool = False
    keepsave_available: bool = False
    eval_available: bool = False

    def update(
        self,
        *,
        temporal: bool | None = None,
        keepsave: bool | None = None,
        eval_service: bool | None = None,
    ) -> None:
        """Update service availability status."""
        if temporal is not None:
            self.temporal_available = temporal
        if keepsave is not None:
            self.keepsave_available = keepsave
        if eval_service is not None:
            self.eval_available = eval_service

        logger.info(
            "service_availability_updated",
            temporal=self.temporal_available,
            keepsave=self.keepsave_available,
            eval=self.eval_available,
        )


# Singleton — import and check from anywhere
service_status = ServiceAvailability()

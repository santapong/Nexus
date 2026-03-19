from __future__ import annotations

from typing import Any

import structlog
from litestar import Controller, get

logger = structlog.get_logger()

# Core services — system cannot function without these
_CORE_SERVICES = {
    "postgres", "redis_working", "redis_cache",
    "redis_pubsub", "redis_locks", "kafka",
}


class HealthController(Controller):
    path = "/health"

    @get()
    async def health_check(self) -> dict[str, Any]:
        """Health check endpoint — verifies core and optional service connectivity.

        Returns:
            status: 'healthy' (all core OK), 'degraded' (optional down), 'unhealthy' (core down)
            checks: per-service status
            optional: optional service status
            circuit_breakers: LLM provider circuit breaker states
        """
        checks: dict[str, str] = {}

        # Check PostgreSQL
        try:
            from sqlalchemy import text

            from nexus.db.session import sqlalchemy_config

            async with sqlalchemy_config.get_engine().connect() as conn:
                await conn.execute(text("SELECT 1"))
            checks["postgres"] = "ok"
        except Exception as exc:
            logger.error("health_check_postgres_failed", error=str(exc))
            checks["postgres"] = f"error: {exc}"

        # Check Redis (all 4 databases)
        from nexus.core.redis.clients import (
            redis_cache,
            redis_locks,
            redis_pubsub,
            redis_working,
        )

        for name, client in [
            ("redis_working", redis_working),
            ("redis_cache", redis_cache),
            ("redis_pubsub", redis_pubsub),
            ("redis_locks", redis_locks),
        ]:
            try:
                await client.ping()
                checks[name] = "ok"
            except Exception as exc:
                logger.error("health_check_redis_failed", db=name, error=str(exc))
                checks[name] = f"error: {exc}"

        # Check Kafka
        try:
            from aiokafka import AIOKafkaProducer

            from nexus.settings import settings

            producer = AIOKafkaProducer(
                bootstrap_servers=settings.kafka_bootstrap_servers,
            )
            await producer.start()
            await producer.stop()
            checks["kafka"] = "ok"
        except Exception as exc:
            logger.error("health_check_kafka_failed", error=str(exc))
            checks["kafka"] = f"error: {exc}"

        # ─── Optional services ───────────────────────────────────────────
        optional: dict[str, str] = {}

        # Temporal
        try:
            import httpx

            from nexus.settings import settings as s

            if s.temporal_host:
                async with httpx.AsyncClient() as client:
                    host = s.temporal_host.replace(":7233", ":7233")
                    resp = await client.get(f"http://{host}/api/v1/namespaces", timeout=3.0)
                    optional["temporal"] = "ok" if resp.status_code < 500 else "error"
            else:
                optional["temporal"] = "not_configured"
        except Exception:
            optional["temporal"] = "unavailable"

        # KeepSave
        try:
            from nexus.settings import settings as s

            if s.keepsave_url:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(f"{s.keepsave_url}/health", timeout=3.0)
                    optional["keepsave"] = "ok" if resp.status_code == 200 else "error"
            else:
                optional["keepsave"] = "not_configured"
        except Exception:
            optional["keepsave"] = "unavailable"

        # LangFuse (eval)
        try:
            from nexus.settings import settings as s

            if s.langfuse_host:
                optional["langfuse"] = "configured"
            else:
                optional["langfuse"] = "not_configured"
        except Exception:
            optional["langfuse"] = "unavailable"

        # ─── Circuit breaker states ──────────────────────────────────────
        from nexus.core.llm.circuit_breaker import get_all_breaker_states

        breaker_states = get_all_breaker_states()

        # ─── Determine overall status ────────────────────────────────────
        core_ok = all(checks.get(svc) == "ok" for svc in _CORE_SERVICES)
        optional_ok = all(v in ("ok", "configured", "not_configured") for v in optional.values())

        if core_ok and optional_ok:
            status = "healthy"
        elif core_ok:
            status = "degraded"
        else:
            status = "unhealthy"

        return {
            "status": status,
            "checks": checks,
            "optional": optional,
            "circuit_breakers": breaker_states,
        }

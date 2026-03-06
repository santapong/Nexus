from __future__ import annotations

from typing import Any

import structlog
from litestar import Controller, get

logger = structlog.get_logger()


class HealthController(Controller):
    path = "/health"

    @get()
    async def health_check(self) -> dict[str, Any]:
        """Health check endpoint — verifies DB, Redis, Kafka connectivity."""
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
        from nexus.redis.clients import redis_cache, redis_locks, redis_pubsub, redis_working

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

        all_ok = all(v == "ok" for v in checks.values())

        return {
            "status": "healthy" if all_ok else "degraded",
            "checks": checks,
        }

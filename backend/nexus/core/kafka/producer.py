"""Kafka producer with automatic reconnection and health checking.

Singleton pattern with reconnect-on-failure. If the producer detects
a stale connection, it recreates the underlying AIOKafkaProducer.
"""

from __future__ import annotations

import asyncio
import json
import time

import structlog
from aiokafka import AIOKafkaProducer

from nexus.core.kafka.schemas import KafkaMessage
from nexus.settings import settings

logger = structlog.get_logger()

_producer: AIOKafkaProducer | None = None
_last_health_check: float = 0
_HEALTH_CHECK_INTERVAL = 60  # seconds
_MAX_RECONNECT_ATTEMPTS = 3
_RECONNECT_DELAY = 2  # seconds


async def get_producer() -> AIOKafkaProducer:
    """Get or create the singleton Kafka producer.

    Checks health periodically and reconnects if stale.

    Returns:
        A started AIOKafkaProducer.
    """
    global _producer, _last_health_check

    if _producer is not None:
        # Periodic health check
        now = time.monotonic()
        if now - _last_health_check > _HEALTH_CHECK_INTERVAL:
            _last_health_check = now
            if not await _check_producer_health():
                logger.warning("kafka_producer_unhealthy_reconnecting")
                await _reconnect()

        return _producer

    _producer = await _create_producer()
    _last_health_check = time.monotonic()
    return _producer


async def _create_producer() -> AIOKafkaProducer:
    """Create and start a new Kafka producer."""
    producer = AIOKafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        key_serializer=lambda k: k.encode("utf-8") if k else None,
        request_timeout_ms=30000,
        retry_backoff_ms=500,
        max_batch_size=16384,
    )
    await producer.start()
    logger.info("kafka_producer_started")
    return producer


async def _check_producer_health() -> bool:
    """Check if the producer connection is healthy."""
    if _producer is None:
        return False
    try:
        # partitions_for returns quickly if broker is reachable
        await asyncio.wait_for(
            _producer.partitions_for("__consumer_offsets"),
            timeout=5.0,
        )
        return True
    except Exception:
        return False


async def _reconnect() -> None:
    """Reconnect the producer with retry logic."""
    global _producer

    # Close existing
    if _producer is not None:
        import contextlib

        with contextlib.suppress(Exception):
            await _producer.stop()
        _producer = None

    for attempt in range(1, _MAX_RECONNECT_ATTEMPTS + 1):
        try:
            _producer = await _create_producer()
            logger.info(
                "kafka_producer_reconnected",
                attempt=attempt,
            )
            return
        except Exception as exc:
            logger.warning(
                "kafka_producer_reconnect_failed",
                attempt=attempt,
                error=str(exc),
            )
            if attempt < _MAX_RECONNECT_ATTEMPTS:
                await asyncio.sleep(_RECONNECT_DELAY * attempt)

    logger.error("kafka_producer_reconnect_exhausted")


async def publish(topic: str, message: KafkaMessage, key: str | None = None) -> None:
    """Publish a message to a Kafka topic with automatic reconnection.

    Signs messages with HMAC-SHA256 before publishing for integrity
    verification on the consumer side.

    Args:
        topic: Topic name (must be from Topics constants).
        message: The KafkaMessage to publish.
        key: Optional partition key.

    Raises:
        Exception: If publish fails after reconnection attempts.
    """
    from nexus.core.kafka.signing import inject_signature

    producer = await get_producer()
    value = message.model_dump(mode="json")

    # Sign message for integrity verification
    value = inject_signature(value)

    try:
        await producer.send_and_wait(topic, value=value, key=key)
    except Exception as exc:
        # Try reconnecting once and retrying
        logger.warning(
            "kafka_publish_failed_retrying",
            topic=topic,
            error=str(exc),
        )
        await _reconnect()
        producer = await get_producer()
        await producer.send_and_wait(topic, value=value, key=key)

    logger.info(
        "kafka_message_published",
        topic=topic,
        task_id=str(message.task_id),
        trace_id=str(message.trace_id),
        agent_id=message.agent_id,
    )


async def close_producer() -> None:
    """Gracefully close the Kafka producer."""
    global _producer
    if _producer is not None:
        await _producer.stop()
        _producer = None
        logger.info("kafka_producer_stopped")

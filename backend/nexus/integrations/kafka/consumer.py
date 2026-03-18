from __future__ import annotations

import json

import structlog
from aiokafka import AIOKafkaConsumer

from nexus.integrations.redis.clients import redis_locks
from nexus.settings import settings

logger = structlog.get_logger()


async def create_consumer(
    *topics: str,
    group_id: str,
) -> AIOKafkaConsumer:
    """Create and start a Kafka consumer for the given topics.

    Args:
        topics: Topic names to subscribe to.
        group_id: Consumer group ID.

    Returns:
        A started AIOKafkaConsumer.
    """
    consumer = AIOKafkaConsumer(
        *topics,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=group_id,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        auto_offset_reset="earliest",
        enable_auto_commit=True,
    )
    await consumer.start()
    logger.info("kafka_consumer_started", topics=topics, group_id=group_id)
    return consumer


async def check_idempotency(message_id: str) -> bool:
    """Check and set idempotency key. Returns True if message is new.

    Args:
        message_id: Unique message identifier.

    Returns:
        True if this is a new message, False if already processed.
    """
    key = f"idempotency:{message_id}"
    # SET NX returns True if key was set (new message)
    was_set = await redis_locks.set(key, "1", nx=True, ex=86400)  # 24h TTL
    return bool(was_set)

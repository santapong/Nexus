"""Dead letter queue publisher — routes failed messages after max retries.

After 3 consecutive failures, a message is published to {topic}.dead_letter
and a DeadLetter record is persisted to PostgreSQL for dashboard monitoring.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import structlog

from nexus.db.models import DeadLetter
from nexus.kafka.topics import Topics
from nexus.redis.clients import redis_locks

logger = structlog.get_logger()

MAX_RETRIES = 3
_RETRY_KEY_TTL = 3600  # 1 hour


async def increment_retry(message_id: str) -> int:
    """Increment retry counter for a message.

    Args:
        message_id: Unique message identifier.

    Returns:
        The new retry count after increment.
    """
    key = f"retry:{message_id}"
    count = await redis_locks.incr(key)
    if count == 1:
        await redis_locks.expire(key, _RETRY_KEY_TTL)
    return int(count)


async def publish_dead_letter(
    *,
    source_topic: str,
    raw_message: dict[str, Any],
    error: str,
    task_id: str | None,
    db_session_factory: Callable[..., Any],
) -> None:
    """Publish a failed message to the dead letter topic and persist to DB.

    Args:
        source_topic: The original topic where the message was consumed.
        raw_message: The raw message dict that failed processing.
        error: Error description from the last failure.
        task_id: Task ID from the message, if extractable.
        db_session_factory: Factory for creating async DB sessions.
    """
    dl_topic = Topics.dead_letter_for(source_topic)
    message_id = raw_message.get("message_id", "unknown")

    # Publish to dead letter Kafka topic
    try:
        from nexus.kafka.producer import get_producer

        producer = await get_producer()
        await producer.send_and_wait(dl_topic, value=raw_message, key=task_id)
        logger.warning(
            "dead_letter_published",
            source_topic=source_topic,
            dl_topic=dl_topic,
            message_id=message_id,
            task_id=task_id,
            error=error,
        )
    except Exception as kafka_exc:
        logger.error(
            "dead_letter_kafka_publish_failed",
            source_topic=source_topic,
            message_id=message_id,
            error=str(kafka_exc),
        )

    # Persist to DB for dashboard monitoring
    try:
        async with db_session_factory() as session:
            record = DeadLetter(
                source_topic=source_topic,
                message_id=str(message_id),
                task_id=task_id,
                error=error,
                raw_message=raw_message,
                retry_count=MAX_RETRIES,
            )
            session.add(record)
            await session.commit()
            logger.info(
                "dead_letter_persisted",
                source_topic=source_topic,
                message_id=message_id,
                task_id=task_id,
            )
    except Exception as db_exc:
        logger.error(
            "dead_letter_db_persist_failed",
            source_topic=source_topic,
            message_id=message_id,
            error=str(db_exc),
        )

    # Clean up retry counter
    await redis_locks.delete(f"retry:{message_id}")

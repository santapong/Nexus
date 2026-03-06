from __future__ import annotations

import json

import structlog
from aiokafka import AIOKafkaProducer

from nexus.kafka.schemas import KafkaMessage
from nexus.settings import settings

logger = structlog.get_logger()

_producer: AIOKafkaProducer | None = None


async def get_producer() -> AIOKafkaProducer:
    """Get or create the singleton Kafka producer."""
    global _producer  # noqa: PLW0603
    if _producer is None:
        _producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if k else None,
        )
        await _producer.start()
        logger.info("kafka_producer_started")
    return _producer


async def publish(topic: str, message: KafkaMessage, key: str | None = None) -> None:
    """Publish a message to a Kafka topic.

    Args:
        topic: Topic name (must be from Topics constants).
        message: The KafkaMessage to publish.
        key: Optional partition key.
    """
    producer = await get_producer()
    value = message.model_dump(mode="json")
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
    global _producer  # noqa: PLW0603
    if _producer is not None:
        await _producer.stop()
        _producer = None
        logger.info("kafka_producer_stopped")

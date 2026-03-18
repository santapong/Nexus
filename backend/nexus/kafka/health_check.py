"""Kafka health check script. Run with: python -m nexus.kafka.health_check"""

from __future__ import annotations

import asyncio
import sys

import structlog
from aiokafka import AIOKafkaProducer
from aiokafka.admin import AIOKafkaAdminClient, NewTopic

from nexus.kafka.topics import Topics
from nexus.settings import settings

logger = structlog.get_logger()


async def check_kafka() -> bool:
    """Verify Kafka connectivity and create topics if missing."""
    logger.info("kafka_health_check_start", bootstrap_servers=settings.kafka_bootstrap_servers)

    try:
        producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers,
        )
        await producer.start()
        await producer.stop()
        logger.info("kafka_producer_connection", status="ok")
    except Exception as e:
        logger.error("kafka_producer_connection", status="failed", error=str(e))
        return False

    try:
        admin = AIOKafkaAdminClient(
            bootstrap_servers=settings.kafka_bootstrap_servers,
        )
        await admin.start()

        existing = await admin.list_topics()
        all_topics = Topics.all_topics()
        missing = [t for t in all_topics if t not in existing]

        if missing:
            new_topics = [NewTopic(name=t, num_partitions=1, replication_factor=1) for t in missing]
            await admin.create_topics(new_topics)
            logger.info("kafka_topics_created", count=len(missing), topics=missing)
        else:
            logger.info("kafka_topics_exist", count=len(all_topics))

        await admin.close()
        logger.info("kafka_admin_connection", status="ok")
    except Exception as e:
        logger.error("kafka_admin_connection", status="failed", error=str(e))
        return False

    logger.info("kafka_health_check_passed")
    return True


if __name__ == "__main__":
    result = asyncio.run(check_kafka())
    sys.exit(0 if result else 1)

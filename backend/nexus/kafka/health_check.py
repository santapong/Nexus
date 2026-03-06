"""Kafka health check script. Run with: python -m nexus.kafka.health_check"""
from __future__ import annotations

import asyncio
import sys

from aiokafka import AIOKafkaProducer
from aiokafka.admin import AIOKafkaAdminClient, NewTopic

from nexus.kafka.topics import Topics
from nexus.settings import settings


async def check_kafka() -> bool:
    """Verify Kafka connectivity and create topics if missing."""
    print(f"Connecting to Kafka at {settings.kafka_bootstrap_servers}...")

    try:
        # Test producer connectivity
        producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers,
        )
        await producer.start()
        await producer.stop()
        print("  Producer connection: OK")
    except Exception as e:
        print(f"  Producer connection: FAILED - {e}")
        return False

    try:
        # Create topics if they don't exist
        admin = AIOKafkaAdminClient(
            bootstrap_servers=settings.kafka_bootstrap_servers,
        )
        await admin.start()

        existing = await admin.list_topics()
        all_topics = Topics.all_topics()
        missing = [t for t in all_topics if t not in existing]

        if missing:
            new_topics = [
                NewTopic(name=t, num_partitions=1, replication_factor=1)
                for t in missing
            ]
            await admin.create_topics(new_topics)
            print(f"  Created {len(missing)} topics: {missing}")
        else:
            print(f"  All {len(all_topics)} topics exist")

        await admin.close()
        print("  Admin connection: OK")
    except Exception as e:
        print(f"  Admin connection: FAILED - {e}")
        return False

    print("Kafka health check: PASSED")
    return True


if __name__ == "__main__":
    result = asyncio.run(check_kafka())
    sys.exit(0 if result else 1)

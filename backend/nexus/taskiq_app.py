from __future__ import annotations

from taskiq_aio_kafka import AioKafkaBroker
from taskiq_redis import RedisAsyncResultBackend

from nexus.settings import settings

broker = AioKafkaBroker(
    bootstrap_servers=settings.kafka_bootstrap_servers,
).with_result_backend(
    RedisAsyncResultBackend(
        redis_url=f"{settings.redis_url}/1",
    )
)

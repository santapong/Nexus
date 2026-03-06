from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def mock_redis_locks() -> AsyncMock:
    """Mock Redis db:3 (locks/idempotency)."""
    mock = AsyncMock()
    mock.set.return_value = True  # idempotency: message is new
    return mock


@pytest.fixture
def mock_redis_cache() -> AsyncMock:
    """Mock Redis db:1 (cache/budget)."""
    mock = AsyncMock()
    mock.get.return_value = None  # within budget (no usage recorded)
    return mock


@pytest.fixture
def mock_redis_pubsub() -> AsyncMock:
    """Mock Redis db:2 (pub/sub)."""
    mock = AsyncMock()
    mock.publish.return_value = 1
    return mock


@pytest.fixture
def mock_kafka_producer() -> AsyncMock:
    """Mock Kafka producer."""
    mock = AsyncMock()
    mock.send_and_wait.return_value = None
    return mock

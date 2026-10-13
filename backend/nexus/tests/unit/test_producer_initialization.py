"""A failed/cancelled Kafka startup closes the allocated client and preserves the error."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from nexus.core.kafka.producer import _create_producer


@pytest.mark.parametrize("failure", [RuntimeError("unavailable"), asyncio.CancelledError()])
async def test_unsuccessful_startup_closes_client(failure: BaseException) -> None:
    producer = AsyncMock()
    producer.start.side_effect = failure
    with (
        patch("nexus.core.kafka.producer.AIOKafkaProducer", return_value=producer),
        pytest.raises(type(failure)) as raised,
    ):
        await _create_producer()
    assert raised.value is failure
    producer.stop.assert_awaited_once()


async def test_cleanup_failure_does_not_hide_original_startup_error() -> None:
    producer = AsyncMock()
    original = RuntimeError("startup unavailable")
    producer.start.side_effect = original
    producer.stop.side_effect = ValueError("cleanup failed")
    with (
        patch("nexus.core.kafka.producer.AIOKafkaProducer", return_value=producer),
        pytest.raises(RuntimeError) as raised,
    ):
        await _create_producer()
    assert raised.value is original
    producer.stop.assert_awaited_once()

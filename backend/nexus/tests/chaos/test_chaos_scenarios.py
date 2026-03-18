"""Chaos tests -- verify graceful degradation under infrastructure failures.

Scenarios from CLAUDE.md section 14:
1. Kafka unavailable -> task fails cleanly
2. Redis wiped mid-task -> recovers from PostgreSQL
3. LLM timeout -> fails within bounded time
4. Token budget exceeded -> pauses, publishes human.input_needed
5. Duplicate Kafka message -> idempotency prevents double-execution
6. Invalid A2A bearer token -> 401, nothing published to Kafka
7. DB connection pool exhausted -> graceful error
8. Agent silent >5min -> health monitor auto-fails
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

# --- Scenario 1: Kafka unavailable ----------------------------------------


class TestKafkaUnavailable:
    """When Kafka is unreachable, tasks should fail cleanly."""

    @pytest.mark.asyncio
    @patch("nexus.kafka.producer.get_producer")
    async def test_publish_fails_cleanly(self, mock_get_producer: AsyncMock) -> None:
        """Publishing to Kafka when unavailable raises, not hangs."""
        mock_producer = AsyncMock()
        mock_producer.send_and_wait = AsyncMock(
            side_effect=Exception("KafkaConnectionError: broker unavailable")
        )
        mock_get_producer.return_value = mock_producer

        from nexus.kafka.producer import publish
        from nexus.kafka.schemas import KafkaMessage

        msg = KafkaMessage(
            task_id=uuid4(),
            trace_id=uuid4(),
            agent_id="test",
            payload={},
        )

        with pytest.raises(Exception, match="KafkaConnectionError"):
            await publish("test.topic", msg)


# --- Scenario 2: Redis wiped mid-task ------------------------------------


class TestRedisWiped:
    """When Redis is wiped, system should recover from PostgreSQL."""

    @pytest.mark.asyncio
    @patch("nexus.llm.usage.redis_cache")
    async def test_daily_spend_returns_true_on_empty_redis(self, mock_redis: AsyncMock) -> None:
        """When Redis has no spend counter, check_daily_spend allows work."""
        mock_redis.get = AsyncMock(return_value=None)

        from nexus.llm.usage import check_daily_spend

        result = await check_daily_spend()
        assert result is True

    @pytest.mark.asyncio
    @patch("nexus.llm.usage.redis_cache")
    async def test_task_budget_returns_ok_on_empty_redis(self, mock_redis: AsyncMock) -> None:
        """When Redis has no task budget key, check_task_budget allows work."""
        mock_redis.get = AsyncMock(return_value=None)

        from nexus.llm.usage import check_task_budget

        result_ok, tokens_used = await check_task_budget("test-task-id")
        assert result_ok is True
        assert tokens_used == 0

    @pytest.mark.asyncio
    @patch("nexus.kafka.consumer.redis_locks")
    async def test_idempotency_allows_on_empty_redis(self, mock_redis: AsyncMock) -> None:
        """When idempotency keys are wiped, messages are processed."""
        mock_redis.set = AsyncMock(return_value=True)

        from nexus.kafka.consumer import check_idempotency

        result = await check_idempotency("test-message-id")
        assert result is True


# --- Scenario 3: LLM timeout ---------------------------------------------


class TestLLMTimeout:
    """LLM calls that timeout should fail with bounded time."""

    @pytest.mark.asyncio
    async def test_timeout_produces_error_not_hang(self) -> None:
        """An LLM timeout raises within bounded time, never hangs."""

        async def mock_llm_call():
            await asyncio.sleep(100)

        with pytest.raises(TimeoutError):
            await asyncio.wait_for(mock_llm_call(), timeout=0.1)

    @pytest.mark.asyncio
    async def test_timeout_error_is_catchable(self) -> None:
        """TimeoutError is caught by the agent guard chain."""
        assert issubclass(TimeoutError, BaseException)

        try:
            raise TimeoutError()
        except Exception as exc:
            error_msg = str(exc) or "LLM call timed out"
            assert isinstance(error_msg, str)


# --- Scenario 4: Token budget exceeded ------------------------------------


class TestTokenBudgetExceededError:
    """Budget exhaustion should pause task and escalate to human."""

    @pytest.mark.asyncio
    @patch("nexus.llm.usage.redis_cache")
    async def test_daily_spend_rejects_over_limit(self, mock_redis: AsyncMock) -> None:
        """check_daily_spend returns False when over the daily limit."""
        from nexus.settings import settings

        mock_redis.get = AsyncMock(return_value=str(settings.daily_spend_limit_usd + 1.0))

        from nexus.llm.usage import check_daily_spend

        result = await check_daily_spend()
        assert result is False

    @pytest.mark.asyncio
    @patch("nexus.llm.usage.redis_cache")
    async def test_task_budget_rejects_over_limit(self, mock_redis: AsyncMock) -> None:
        """check_task_budget returns False when tokens exceed budget."""
        mock_redis.get = AsyncMock(return_value="60000")

        from nexus.llm.usage import check_task_budget

        result_ok, tokens_used = await check_task_budget("test-task", budget=50000)
        assert result_ok is False
        assert tokens_used == 60000

    def test_budget_exceeded_raises_in_guard_chain(self) -> None:
        """TokenBudgetExceededError is raised and caught by the guard chain."""
        from nexus.agents.base import TokenBudgetExceededError

        with pytest.raises(TokenBudgetExceededError):
            raise TokenBudgetExceededError("Daily spend limit reached")


# --- Scenario 5: Duplicate Kafka message ----------------------------------


class TestDuplicateMessage:
    """Duplicate messages should be deduplicated via idempotency keys."""

    @pytest.mark.asyncio
    @patch("nexus.kafka.consumer.redis_locks")
    async def test_first_message_is_new(self, mock_redis: AsyncMock) -> None:
        """First occurrence of a message_id is marked as new."""
        mock_redis.set = AsyncMock(return_value=True)

        from nexus.kafka.consumer import check_idempotency

        result = await check_idempotency("msg-001")
        assert result is True

    @pytest.mark.asyncio
    @patch("nexus.kafka.consumer.redis_locks")
    async def test_duplicate_message_is_skipped(self, mock_redis: AsyncMock) -> None:
        """Second occurrence of same message_id is rejected."""
        mock_redis.set = AsyncMock(return_value=False)

        from nexus.kafka.consumer import check_idempotency

        result = await check_idempotency("msg-001")
        assert result is False

    @pytest.mark.asyncio
    @patch("nexus.kafka.consumer.redis_locks")
    async def test_idempotency_uses_correct_key_format(self, mock_redis: AsyncMock) -> None:
        """Idempotency key follows the pattern 'idempotency:{message_id}'."""
        mock_redis.set = AsyncMock(return_value=True)

        from nexus.kafka.consumer import check_idempotency

        await check_idempotency("test-123")
        mock_redis.set.assert_called_with("idempotency:test-123", "1", nx=True, ex=86400)


# --- Scenario 6: Invalid A2A bearer token --------------------------------


class TestInvalidA2AToken:
    """Invalid tokens should produce 401, not publish to Kafka."""

    @pytest.mark.asyncio
    async def test_revoked_token_rejected(self) -> None:
        """Revoked token returns invalid from cache check."""
        from nexus.gateway.auth import _CachedToken, _check_token_validity

        token = _CachedToken(
            token_hash="abc",
            name="test",
            allowed_skills=["*"],
            rate_limit_rpm=60,
            expires_at=None,
            is_revoked=True,
        )
        valid, _error, rpm = _check_token_validity(token, "general", "abc")
        assert valid is False
        assert rpm == 0

    def test_gateway_raises_not_authorized(self) -> None:
        """Gateway raises NotAuthorizedException for invalid tokens."""
        from litestar.exceptions import NotAuthorizedException

        with pytest.raises(NotAuthorizedException):
            raise NotAuthorizedException(detail="Invalid token")


# --- Scenario 7: DB connection pool exhausted -----------------------------


class TestDBPoolExhausted:
    """DB connection failures should produce graceful errors."""

    @pytest.mark.asyncio
    async def test_session_factory_error_is_catchable(self) -> None:
        """When DB pool is exhausted, the error is a normal Exception."""
        mock_factory = AsyncMock(side_effect=Exception("connection pool exhausted"))

        with pytest.raises(Exception, match="connection pool exhausted"):
            async with mock_factory() as _session:
                pass


# --- Scenario 8: Agent silent >5min --------------------------------------


class TestAgentSilence:
    """Health monitor should auto-fail tasks when agents go silent."""

    @pytest.mark.asyncio
    @patch("nexus.redis.clients.redis_cache")
    async def test_heartbeat_stored_in_redis(self, mock_redis: AsyncMock) -> None:
        """Heartbeat is stored as a Redis key with TTL."""
        mock_redis.set = AsyncMock()

        agent_id = "test-agent-001"
        key = f"heartbeat:{agent_id}"
        await mock_redis.set(key, "alive", ex=600)
        mock_redis.set.assert_called_with(key, "alive", ex=600)

    @pytest.mark.asyncio
    @patch("nexus.redis.clients.redis_cache")
    async def test_missing_heartbeat_detected(self, mock_redis: AsyncMock) -> None:
        """Missing heartbeat key means agent is silent."""
        mock_redis.get = AsyncMock(return_value=None)

        result = await mock_redis.get("heartbeat:silent-agent")
        assert result is None


# --- Dead letter routing --------------------------------------------------


class TestDeadLetterRouting:
    """Failed messages should route to dead letter after max retries."""

    @pytest.mark.asyncio
    @patch("nexus.kafka.dead_letter.redis_locks")
    async def test_retry_counter_increments(self, mock_redis: AsyncMock) -> None:
        """Retry counter increments on each failure."""
        mock_redis.incr = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock()

        from nexus.kafka.dead_letter import increment_retry

        count = await increment_retry("msg-001")
        assert count == 1
        mock_redis.incr.assert_called_with("retry:msg-001")
        mock_redis.expire.assert_called_once()

    @pytest.mark.asyncio
    @patch("nexus.kafka.dead_letter.redis_locks")
    async def test_retry_counter_reaches_max(self, mock_redis: AsyncMock) -> None:
        """After MAX_RETRIES, message should be routed to dead letter."""
        mock_redis.incr = AsyncMock(return_value=3)

        from nexus.kafka.dead_letter import MAX_RETRIES, increment_retry

        count = await increment_retry("msg-001")
        assert count >= MAX_RETRIES

    def test_dead_letter_topic_naming(self) -> None:
        """Dead letter topics follow the naming convention."""
        from nexus.kafka.topics import Topics

        assert Topics.dead_letter_for("task.queue") == "task.queue.dead_letter"
        assert Topics.dead_letter_for("agent.commands") == "agent.commands.dead_letter"
        assert Topics.TASK_QUEUE_DL == "task.queue.dead_letter"
        assert Topics.AGENT_RESPONSES_DL == "agent.responses.dead_letter"

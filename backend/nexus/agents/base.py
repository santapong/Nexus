"""AgentBase — the most critical class in the system.

All agents extend this base. It provides:
- Kafka consumer loop
- Full guard chain (idempotency → budget → memory → execute → write → publish)
- Heartbeat loop
- Human input escalation
- Error handling with structured logging

Subclasses implement handle_task() only.
"""
from __future__ import annotations

import asyncio
import json
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any
from uuid import UUID

import structlog
from pydantic_ai import Agent as PydanticAgent
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import AgentRole, TaskStatus
from nexus.kafka.consumer import check_idempotency, create_consumer
from nexus.kafka.producer import get_producer, publish
from nexus.kafka.schemas import AgentCommand, AgentResponse, HeartbeatMessage, KafkaMessage
from nexus.kafka.topics import Topics
from nexus.llm.usage import check_daily_spend, check_task_budget
from nexus.memory.embeddings import generate_embedding
from nexus.memory.episodic import recall_similar, write_episode
from nexus.memory.working import clear_working_memory, get_working_memory
from nexus.redis.clients import redis_pubsub

logger = structlog.get_logger()

# ─── Exceptions ──────────────────────────────────────────────────────────────


class TokenBudgetExceeded(Exception):
    """Raised when the daily or per-task token budget is exceeded."""


class ToolCallLimitExceeded(Exception):
    """Raised when the agent exceeds 20 tool calls per task."""


# ─── AgentBase ───────────────────────────────────────────────────────────────


class AgentBase(ABC):
    """Abstract base class for all NEXUS agents.

    Provides the full lifecycle: consume → guard → execute → memory → publish.
    Subclasses only implement handle_task().
    """

    MAX_TOOL_CALLS = 20

    def __init__(
        self,
        *,
        role: AgentRole,
        agent_id: str,
        subscribe_topics: list[str],
        group_id: str,
        llm_agent: PydanticAgent[Any, str],
        db_session_factory: Callable[..., Any],
    ) -> None:
        self.role = role
        self.agent_id = agent_id
        self.subscribe_topics = subscribe_topics
        self.group_id = group_id
        self.llm_agent = llm_agent
        self.db_session_factory = db_session_factory
        self._running = False

    @abstractmethod
    async def handle_task(
        self, message: AgentCommand, session: AsyncSession
    ) -> AgentResponse:
        """Execute the agent's core logic for a task.

        Subclasses implement this method. The guard chain in
        _execute_with_guards() wraps every call with idempotency,
        budget checks, memory loading, and result publishing.

        Args:
            message: The incoming command with task details.
            session: Database session for the task's transaction.

        Returns:
            AgentResponse with status and output.
        """
        ...

    # ─── Main loop ───────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Main Kafka consumer loop. Runs indefinitely until stopped."""
        consumer = await create_consumer(
            *self.subscribe_topics, group_id=self.group_id
        )
        self._running = True
        heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        logger.info(
            "agent_started",
            agent_id=self.agent_id,
            role=self.role.value,
            topics=self.subscribe_topics,
        )

        try:
            async for msg in consumer:
                try:
                    await self._process_message(msg.value)
                except Exception as exc:
                    logger.error(
                        "message_processing_error",
                        agent_id=self.agent_id,
                        error=str(exc),
                    )
        finally:
            self._running = False
            heartbeat_task.cancel()
            await consumer.stop()
            logger.info("agent_stopped", agent_id=self.agent_id)

    async def _process_message(self, raw: dict[str, Any]) -> None:
        """Deserialize message and execute with guards if targeted at this role."""
        try:
            command = AgentCommand.model_validate(raw)
        except Exception:
            logger.warning(
                "invalid_message_format",
                agent_id=self.agent_id,
                raw_keys=list(raw.keys()),
            )
            return

        # Filter: only process commands targeting this role
        if command.target_role != self.role.value:
            return

        logger.info(
            "task_received",
            agent_id=self.agent_id,
            task_id=str(command.task_id),
            trace_id=str(command.trace_id),
        )

        await self._execute_with_guards(command)

    # ─── Guard chain ─────────────────────────────────────────────────────────

    async def _execute_with_guards(self, command: AgentCommand) -> None:
        """Full guard chain protecting every task execution.

        Order (invariant — do not reorder):
        1. Idempotency check (Redis db:3)
        2. Budget check (daily spend + per-task)
        3. Load memory context
        4. handle_task() — subclass logic
        5. Write episodic memory — MUST succeed before step 6
        6. Publish result to Kafka
        7. Broadcast to Redis pub/sub for dashboard
        8. Clear working memory
        """
        msg_id = str(command.message_id)
        task_id = str(command.task_id)
        trace_id = str(command.trace_id)

        # 1. Idempotency
        is_new = await check_idempotency(msg_id)
        if not is_new:
            logger.info(
                "duplicate_message_skipped",
                message_id=msg_id,
                task_id=task_id,
                agent_id=self.agent_id,
            )
            return

        start_time = time.monotonic()

        try:
            # 2. Budget check
            await self._check_budget(task_id)

            async with self.db_session_factory() as session:
                # 3. Load memory context (available to handle_task via self)
                self._memory_context = await self._load_memory(session, command)

                # 4. Execute task
                response = await self.handle_task(command, session)

                # 5. Write memory BEFORE publishing result (Pattern A)
                duration = int(time.monotonic() - start_time)
                await self._write_memory(session, command, response, duration)

                await session.commit()

            # 6. Publish result to Kafka
            await publish(Topics.AGENT_RESPONSES, response, key=task_id)

            # 7. Broadcast for dashboard
            await self._broadcast({
                "event": "task_completed",
                "agent_id": self.agent_id,
                "task_id": task_id,
                "status": response.status,
            })

            # 8. Clear working memory
            await clear_working_memory(self.agent_id, task_id)

            logger.info(
                "task_completed",
                agent_id=self.agent_id,
                task_id=task_id,
                trace_id=trace_id,
                status=response.status,
                duration_seconds=int(time.monotonic() - start_time),
            )

        except TokenBudgetExceeded as exc:
            logger.warning(
                "token_budget_exceeded",
                agent_id=self.agent_id,
                task_id=task_id,
                error=str(exc),
            )
            await self._request_human_input(command, reason="token_budget_exceeded")

        except Exception as exc:
            logger.error(
                "task_execution_failed",
                agent_id=self.agent_id,
                task_id=task_id,
                trace_id=trace_id,
                error=str(exc),
                exc_info=True,
            )
            error_response = AgentResponse(
                task_id=command.task_id,
                trace_id=command.trace_id,
                agent_id=self.agent_id,
                payload={},
                status="failed",
                error=str(exc),
            )
            await publish(Topics.AGENT_RESPONSES, error_response, key=task_id)
            await self._broadcast({
                "event": "task_failed",
                "agent_id": self.agent_id,
                "task_id": task_id,
                "error": str(exc),
            })

    # ─── Budget enforcement ──────────────────────────────────────────────────

    async def _check_budget(self, task_id: str) -> None:
        """Check both daily spend limit and per-task token budget.

        Raises TokenBudgetExceeded if either limit is reached.
        Must be called before every LLM call.
        """
        daily_ok = await check_daily_spend()
        if not daily_ok:
            raise TokenBudgetExceeded("Daily spend limit reached")

        task_ok, used = await check_task_budget(task_id)
        if not task_ok:
            raise TokenBudgetExceeded(
                f"Task token budget exceeded: {used} tokens used"
            )

    # ─── Memory operations ───────────────────────────────────────────────────

    async def _load_memory(
        self, session: AsyncSession, command: AgentCommand
    ) -> dict[str, Any]:
        """Load episodic + working memory context for the task."""
        # Generate embedding for similarity search
        embedding = await generate_embedding(command.instruction)

        episodes: list[Any] = []
        if embedding:
            episodes = await recall_similar(
                session=session,
                agent_id=self.agent_id,
                query_embedding=embedding,
                limit=5,
            )

        # Load working memory from Redis
        working = await get_working_memory(self.agent_id, str(command.task_id))

        return {
            "similar_episodes": [e.summary for e in episodes],
            "working_memory": working,
        }

    async def _write_memory(
        self,
        session: AsyncSession,
        command: AgentCommand,
        response: AgentResponse,
        duration: int,
    ) -> None:
        """Write episodic memory. MUST complete before result is published."""
        await write_episode(
            session=session,
            agent_id=self.agent_id,
            task_id=str(command.task_id),
            summary=command.instruction[:500],
            full_context={
                "instruction": command.instruction,
                "output": response.output,
                "error": response.error,
            },
            outcome=response.status,
            tokens_used=response.tokens_used,
            duration_seconds=duration,
        )

    # ─── Broadcasting ────────────────────────────────────────────────────────

    async def _broadcast(self, event: dict[str, Any]) -> None:
        """Publish event to Redis pub/sub for dashboard WebSocket."""
        channel = f"agent_activity:{self.agent_id}"
        await redis_pubsub.publish(channel, json.dumps(event))

    # ─── Heartbeat ───────────────────────────────────────────────────────────

    async def _heartbeat_loop(self) -> None:
        """Publish heartbeat every 30 seconds to agent.heartbeat topic."""
        while self._running:
            try:
                hb = HeartbeatMessage(agent_id=self.agent_id)
                producer = await get_producer()
                await producer.send_and_wait(
                    Topics.AGENT_HEARTBEAT,
                    value=json.dumps(hb.model_dump(mode="json")).encode("utf-8"),
                )
            except Exception as exc:
                logger.warning(
                    "heartbeat_failed",
                    agent_id=self.agent_id,
                    error=str(exc),
                )
            await asyncio.sleep(30)

    # ─── Human escalation ────────────────────────────────────────────────────

    async def _request_human_input(
        self, command: AgentCommand, *, reason: str
    ) -> None:
        """Pause task and publish to human.input_needed topic."""
        msg = KafkaMessage(
            task_id=command.task_id,
            trace_id=command.trace_id,
            agent_id=self.agent_id,
            payload={
                "reason": reason,
                "instruction": command.instruction,
                "agent_role": self.role.value,
            },
        )
        await publish(Topics.HUMAN_INPUT_NEEDED, msg, key=str(command.task_id))

        await self._broadcast({
            "event": "human_input_needed",
            "agent_id": self.agent_id,
            "task_id": str(command.task_id),
            "reason": reason,
        })

        logger.info(
            "human_input_requested",
            agent_id=self.agent_id,
            task_id=str(command.task_id),
            reason=reason,
        )

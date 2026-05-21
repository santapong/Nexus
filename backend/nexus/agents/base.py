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
import contextlib
import json
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

import structlog
from pydantic_ai import Agent as PydanticAgent
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.audit.service import AuditEventType, log_event
from nexus.core.kafka.consumer import check_idempotency, create_consumer
from nexus.core.kafka.dead_letter import MAX_RETRIES, increment_retry, publish_dead_letter
from nexus.core.kafka.producer import get_producer, publish
from nexus.core.kafka.schemas import (
    AgentCommand,
    AgentResponse,
    HeartbeatMessage,
    KafkaMessage,
    MeetingCommand,
)
from nexus.core.kafka.topics import Topics
from nexus.core.llm.usage import check_daily_spend, check_task_budget
from nexus.core.redis.clients import redis_pubsub
from nexus.db.models import Agent as AgentModel
from nexus.db.models import AgentRole
from nexus.memory.embeddings import generate_embedding
from nexus.memory.episodic import recall_similar, write_episode
from nexus.memory.working import clear_working_memory, get_working_memory

logger = structlog.get_logger()

# ─── Exceptions ──────────────────────────────────────────────────────────────


class TokenBudgetExceededError(Exception):
    """Raised when the daily or per-task token budget is exceeded."""


class ToolCallLimitExceededError(Exception):
    """Raised when the agent exceeds 20 tool calls per task."""


class ToolAccessDenied(Exception):  # noqa: N818  — name fixed by integration contract (temporal/activities.py)
    """Raised when an agent attempts to call a tool outside its allow-list.

    Enforces CLAUDE.md §20 NEVER rule 2: agents must never access tools
    outside their tool_access list. Distinct from approval guards — this
    is an ACL violation that signals a misconfigured agent or a prompt
    that escaped registry filtering.
    """


class MemoryWriteFailed(Exception):  # noqa: N818  — sentinel name surfaced in logs and the DLQ payload
    """Raised when episodic memory write fails.

    CLAUDE.md §20 MUST rule 2 invariant: memory must succeed before result
    is published. This sentinel is recognized by the outer exception handler
    to route the failure to the dead-letter queue WITHOUT publishing a
    user-visible (and misleading) result.
    """


# ─── AgentBase ───────────────────────────────────────────────────────────────


class AgentBase(ABC):
    """Abstract base class for all NEXUS agents.

    Provides the full lifecycle: consume → guard → execute → memory → publish.
    Subclasses only implement handle_task().
    """

    MAX_TOOL_CALLS = 20
    # Meeting response LLM call timeout (Risk 5: avoid silent hangs in meetings)
    MEETING_RESPONSE_TIMEOUT_SECONDS = 60
    # Prompt reload cache TTL — avoid hammering the DB for every task
    _PROMPT_CACHE_TTL_SECONDS = 300.0

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
        # Track current system prompt for hot-reload detection
        self._current_system_prompt: str | None = None
        # Strong reference to heartbeat task — without this Python's GC can
        # collect the asyncio.Task and silently stop heartbeating, causing
        # the health monitor to auto-fail this agent (Risk 5).
        self._heartbeat_task: asyncio.Task[None] | None = None
        # Prompt reload cache: maps agent_id -> (db_prompt, expires_at).
        # Prevents one DB query per task when the prompt is unchanged.
        self._prompt_cache: dict[str, tuple[str, float]] = {}
        # Snapshot of allowed tool names for this role (for runtime ACL check).
        # Populated lazily on first access to avoid a circular import at module
        # load time (nexus.tools.registry imports from nexus.agents indirectly).
        self._tool_access_cache: frozenset[str] | None = None

    @abstractmethod
    async def handle_task(self, message: AgentCommand, session: AsyncSession) -> AgentResponse:
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
        """Main Kafka consumer loop. Runs indefinitely until stopped.

        Shutdown-aware: checks for graceful shutdown signal before
        processing new messages. In-flight tasks are tracked for
        clean draining during shutdown.
        """
        consumer = await create_consumer(*self.subscribe_topics, group_id=self.group_id)
        self._running = True
        # Hold a strong reference on self so the event loop won't GC the task
        # mid-flight (see PEP 3156 / asyncio.create_task docs).
        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(), name=f"heartbeat-{self.agent_id}"
        )

        logger.info(
            "agent_started",
            agent_id=self.agent_id,
            role=self.role.value,
            topics=self.subscribe_topics,
        )

        try:
            async for msg in consumer:
                # Check for graceful shutdown before processing new messages
                from nexus.core.shutdown import is_shutting_down

                if is_shutting_down():
                    logger.info(
                        "agent_rejecting_new_task_shutdown",
                        agent_id=self.agent_id,
                    )
                    break

                # Validate message signature
                from nexus.core.kafka.consumer import validate_message_signature

                if not validate_message_signature(msg.value):
                    logger.warning(
                        "invalid_message_signature_rejected",
                        agent_id=self.agent_id,
                        topic=msg.topic,
                    )
                    continue

                try:
                    await self._process_message(msg.value)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    try:
                        await self._handle_consumer_error(msg.value, msg.topic, exc)
                    except asyncio.CancelledError:
                        raise
                    except Exception as handler_exc:
                        # The error handler itself failed (e.g. Redis/Kafka down).
                        # Log loudly but never let it tear down the consumer loop.
                        logger.error(
                            "consumer_error_handler_failed",
                            agent_id=self.agent_id,
                            topic=msg.topic,
                            original_error=str(exc),
                            handler_error=str(handler_exc),
                            exc_info=True,
                        )
        finally:
            self._running = False
            if self._heartbeat_task is not None:
                self._heartbeat_task.cancel()
                # Cancellation is expected; any other exception during teardown
                # is non-fatal — we're shutting down anyway.
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await self._heartbeat_task
                self._heartbeat_task = None
            await consumer.stop()
            logger.info("agent_stopped", agent_id=self.agent_id)

    async def _process_message(self, raw: dict[str, Any]) -> None:
        """Deserialize message and execute with guards if targeted at this role.

        Handles two message types:
        1. MeetingCommand — conference room messages (has meeting_id + participants)
        2. AgentCommand — standard task commands (has target_role)
        """
        # Check if this is a meeting room message
        if "meeting_id" in raw and "participants" in raw:
            try:
                meeting_cmd = MeetingCommand.model_validate(raw)
            except Exception:
                logger.warning(
                    "invalid_meeting_message_format",
                    agent_id=self.agent_id,
                    raw_keys=list(raw.keys()),
                )
                return

            # Only process if this agent's role is in the participants list
            if self.role.value not in meeting_cmd.participants:
                return

            logger.info(
                "meeting_message_received",
                agent_id=self.agent_id,
                meeting_id=meeting_cmd.meeting_id,
                task_id=str(meeting_cmd.task_id),
                round=meeting_cmd.round_number,
            )

            await self._handle_meeting_message(meeting_cmd)
            return

        # Standard AgentCommand flow
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

        Wrapped with OpenTelemetry trace span when OTel is configured.
        """
        from nexus.integrations.otel.tracing import trace_agent_task

        msg_id = str(command.message_id)
        task_id = str(command.task_id)
        trace_id = str(command.trace_id)

        async with trace_agent_task(self.role.value, task_id, trace_id) as span:
            await self._execute_guarded_inner(command, span, msg_id, task_id, trace_id)

    async def _execute_guarded_inner(
        self,
        command: AgentCommand,
        span: Any,
        msg_id: str,
        task_id: str,
        trace_id: str,
    ) -> None:
        """Inner guard chain wrapped by OTel trace span."""
        # Track active task for graceful shutdown draining
        from nexus.core.shutdown import register_active_task, unregister_active_task

        register_active_task(task_id)

        # Guaranteed cleanup of the active-task registry — without try/finally
        # any handler failure (including in the error path) could leak the
        # task forever, blocking graceful shutdown drain.
        try:
            await self._execute_guarded_body(command, msg_id, task_id, trace_id)
        finally:
            unregister_active_task(task_id)

    async def _execute_guarded_body(
        self,
        command: AgentCommand,
        msg_id: str,
        task_id: str,
        trace_id: str,
    ) -> None:
        """Body of the guard chain, wrapped by _execute_guarded_inner for cleanup."""
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

        # Reset tool call counter for this task
        if hasattr(self, "_tool_call_counter"):
            self._tool_call_counter["count"] = 0

        try:
            # 0. Hot-reload system prompt if changed in DB
            await self._check_prompt_reload()

            async with self.db_session_factory() as session:
                # 2. Budget check (inside session for DB fallback on Redis failure)
                await self._check_budget(task_id, session=session)
                # Audit: task_received
                await log_event(
                    session=session,
                    task_id=task_id,
                    trace_id=trace_id,
                    agent_id=self.agent_id,
                    event_type=AuditEventType.TASK_RECEIVED,
                    event_data={
                        "role": self.role.value,
                        "instruction": command.instruction[:200],
                    },
                )

                # 2b. Broadcast task_started for the live UX. Doing this after
                # budget check + audit ensures we never tell the dashboard a
                # task started that immediately got bounced for budget. A
                # broadcast failure must never abort the task — best effort.
                try:
                    await self._broadcast(
                        {
                            "event": "task_started",
                            "agent_id": self.agent_id,
                            "task_id": task_id,
                            "trace_id": trace_id,
                            "role": self.role.value,
                            "instruction_snippet": command.instruction[:140],
                        }
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning(
                        "task_started_broadcast_failed",
                        agent_id=self.agent_id,
                        task_id=task_id,
                        error=str(exc),
                    )

                # 3. Load memory context (available to handle_task via self)
                self._memory_context = await self._load_memory(session, command)

                # 4. Execute task
                response = await self.handle_task(command, session)

                # 4.5 Validate output + PII sanitization
                response = self._validate_output(response)
                response = self._sanitize_output_pii(response, task_id)

                # 5. Write memory BEFORE publishing result (CLAUDE.md §20 rule 2).
                #    Memory failure MUST NOT result in a published "success"
                #    response — route to DLQ instead via MemoryWriteFailed.
                duration = int(time.monotonic() - start_time)
                try:
                    await self._write_memory(session, command, response, duration)
                except asyncio.CancelledError:
                    raise
                except Exception as mem_exc:
                    raise MemoryWriteFailed(f"episodic memory write failed: {mem_exc}") from mem_exc

                # Audit: task_completed
                await log_event(
                    session=session,
                    task_id=task_id,
                    trace_id=trace_id,
                    agent_id=self.agent_id,
                    event_type=AuditEventType.TASK_COMPLETED,
                    event_data={
                        "role": self.role.value,
                        "status": response.status,
                        "duration_seconds": duration,
                        "tokens_used": response.tokens_used,
                    },
                )

                await session.commit()

            # 6. Publish result to Kafka
            await publish(Topics.AGENT_RESPONSES, response, key=task_id)

            # 7. Broadcast for dashboard
            await self._broadcast(
                {
                    "event": "task_completed",
                    "agent_id": self.agent_id,
                    "task_id": task_id,
                    "status": response.status,
                }
            )

            # 8. Clear working memory (skip for orchestration responses
            #    that need tracking state to persist across subtasks)
            if not self._is_orchestration_response(response):
                await clear_working_memory(self.agent_id, task_id)

            logger.info(
                "task_completed",
                agent_id=self.agent_id,
                task_id=task_id,
                trace_id=trace_id,
                status=response.status,
                duration_seconds=int(time.monotonic() - start_time),
            )

        except asyncio.CancelledError:
            # Graceful shutdown / external cancellation must propagate cleanly —
            # do NOT swallow it in the broad Exception clause below.
            raise

        except TokenBudgetExceededError as exc:
            logger.warning(
                "token_budget_exceeded",
                agent_id=self.agent_id,
                task_id=task_id,
                error=str(exc),
            )
            await self._audit_outside_transaction(
                task_id,
                trace_id,
                AuditEventType.BUDGET_EXCEEDED,
                {"error": str(exc), "role": self.role.value},
            )
            await self._request_human_input(command, reason="token_budget_exceeded")

        except ToolCallLimitExceededError as exc:
            logger.warning(
                "tool_call_limit_exceeded",
                agent_id=self.agent_id,
                task_id=task_id,
                error=str(exc),
            )
            await self._audit_outside_transaction(
                task_id,
                trace_id,
                AuditEventType.TOOL_CALL_LIMIT_REACHED,
                {"error": str(exc), "role": self.role.value},
            )
            await self._request_human_input(command, reason="tool_call_limit_exceeded")

        except MemoryWriteFailed as exc:
            # Fail-closed on memory write: do NOT publish a user-visible
            # response — the invariant "memory written before publish" is
            # broken, so we route to the dead-letter queue for human review.
            logger.error(
                "memory_write_failed_routing_to_dlq",
                agent_id=self.agent_id,
                task_id=task_id,
                trace_id=trace_id,
                error=str(exc),
                exc_info=True,
            )
            await self._audit_outside_transaction(
                task_id,
                trace_id,
                AuditEventType.TASK_FAILED,
                {
                    "error": str(exc),
                    "role": self.role.value,
                    "reason": "memory_write_failed",
                },
            )
            try:
                await publish_dead_letter(
                    source_topic=Topics.AGENT_COMMANDS,
                    raw_message=command.model_dump(mode="json"),
                    error=f"memory_write_failed: {exc}",
                    task_id=task_id,
                    db_session_factory=self.db_session_factory,
                )
            except asyncio.CancelledError:
                raise
            except Exception as dlq_exc:
                logger.error(
                    "memory_write_dlq_publish_failed",
                    agent_id=self.agent_id,
                    task_id=task_id,
                    error=str(dlq_exc),
                )
            # Best-effort dashboard notification — no user-visible result is
            # published to agent.responses since the task is effectively lost
            # until an operator inspects the DLQ.
            try:
                await self._broadcast(
                    {
                        "event": "task_failed",
                        "agent_id": self.agent_id,
                        "task_id": task_id,
                        "error": "memory_write_failed",
                    }
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                pass

        except Exception as exc:
            logger.error(
                "task_execution_failed",
                agent_id=self.agent_id,
                task_id=task_id,
                trace_id=trace_id,
                error=str(exc),
                exc_info=True,
            )
            await self._audit_outside_transaction(
                task_id,
                trace_id,
                AuditEventType.TASK_FAILED,
                {"error": str(exc), "role": self.role.value},
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
            await self._broadcast(
                {
                    "event": "task_failed",
                    "agent_id": self.agent_id,
                    "task_id": task_id,
                    "error": str(exc),
                }
            )

    # ─── Budget enforcement ──────────────────────────────────────────────────

    async def _check_budget(
        self,
        task_id: str,
        *,
        session: AsyncSession | None = None,
    ) -> None:
        """Check daily spend, per-task token budget, and per-agent cost alerts.

        Raises TokenBudgetExceededError if any limit is reached.
        Must be called before every LLM call.
        """
        daily_ok = await check_daily_spend(session=session)
        if not daily_ok:
            raise TokenBudgetExceededError("Daily spend limit reached")

        task_ok, used = await check_task_budget(task_id)
        if not task_ok:
            raise TokenBudgetExceededError(f"Task token budget exceeded: {used} tokens used")

        # Per-agent cost alert check
        if session is not None:
            try:
                from nexus.core.llm.cost_alerts import check_agent_daily_cost

                within_budget, current_spend, limit = await check_agent_daily_cost(
                    self.agent_id, session
                )
                if not within_budget:
                    raise TokenBudgetExceededError(
                        f"Agent daily cost limit reached: ${current_spend:.4f} / ${limit:.2f}"
                    )
            except TokenBudgetExceededError:
                raise
            except Exception as exc:
                logger.warning(
                    "agent_cost_alert_check_failed",
                    agent_id=self.agent_id,
                    task_id=task_id,
                    error=str(exc),
                )

    # ─── Prompt hot-reload ──────────────────────────────────────────────────

    async def _check_prompt_reload(self) -> None:
        """Reload system prompt from DB if it was changed via the API.

        Compares agents.system_prompt against the cached value. If different,
        reconstructs the PydanticAgent with the new prompt.

        Uses an in-memory TTL cache (_PROMPT_CACHE_TTL_SECONDS) to avoid
        hitting the DB on every task — the prompt rarely changes.
        """
        if self._current_system_prompt is None:
            return

        # In-process TTL cache: skip DB lookup if we checked recently and the
        # cached prompt still matches the current one in memory.
        now = time.monotonic()
        cache_entry = self._prompt_cache.get(self.agent_id)
        if (
            cache_entry is not None
            and cache_entry[1] > now
            and cache_entry[0] == self._current_system_prompt
        ):
            return

        try:
            async with self.db_session_factory() as session:
                stmt = select(AgentModel).where(AgentModel.id == self.agent_id)
                result = await session.execute(stmt)
                agent_record = result.scalar_one_or_none()

                if agent_record is None:
                    return

                db_prompt = agent_record.system_prompt
                # Refresh cache regardless of whether the prompt changed.
                self._prompt_cache[self.agent_id] = (
                    db_prompt or "",
                    now + self._PROMPT_CACHE_TTL_SECONDS,
                )

                if db_prompt and db_prompt != self._current_system_prompt:
                    from nexus.tools.registry import get_tools_for_role

                    tools = get_tools_for_role(self.role)
                    self.llm_agent = PydanticAgent(
                        model=self.llm_agent.model,
                        system_prompt=db_prompt,
                        tools=tools,
                    )
                    self._current_system_prompt = db_prompt
                    # Invalidate tool ACL snapshot so it's rebuilt on next check.
                    self._tool_access_cache = None
                    logger.info(
                        "system_prompt_hot_reloaded",
                        agent_id=self.agent_id,
                        role=self.role.value,
                    )
        except Exception as exc:
            logger.warning(
                "prompt_reload_check_failed",
                agent_id=self.agent_id,
                error=str(exc),
            )

    # ─── Audit helpers ─────────────────────────────────────────────────────

    async def _audit_outside_transaction(
        self,
        task_id: str,
        trace_id: str,
        event_type: AuditEventType,
        event_data: dict[str, Any],
    ) -> None:
        """Write an audit event using a fresh DB session.

        Used in exception handlers where the main session has been rolled back.
        """
        try:
            async with self.db_session_factory() as session:
                await log_event(
                    session=session,
                    task_id=task_id,
                    trace_id=trace_id,
                    agent_id=self.agent_id,
                    event_type=event_type,
                    event_data=event_data,
                )
                await session.commit()
        except Exception as exc:
            logger.warning(
                "audit_log_failed",
                task_id=task_id,
                event_type=event_type.value
                if isinstance(event_type, AuditEventType)
                else event_type,
                error=str(exc),
            )

    # ─── Memory operations ───────────────────────────────────────────────────

    async def _load_memory(self, session: AsyncSession, command: AgentCommand) -> dict[str, Any]:
        """Load episodic + working + workspace memory context for the task."""
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

        result: dict[str, Any] = {
            "similar_episodes": [e.summary for e in episodes],
            "working_memory": working,
        }

        # Load workspace files via smart context (if embedding available)
        if embedding:
            try:
                workspace_id = await self._resolve_workspace_id(session, command)
                if workspace_id:
                    from nexus.core.workspace.service import load_context_for_task

                    ws_context = await load_context_for_task(
                        session,
                        workspace_id=workspace_id,
                        instruction_embedding=embedding,
                        agent_id=self.agent_id,
                    )
                    if ws_context.files:
                        result["workspace_files"] = [
                            {
                                "path": f.file_path,
                                "content": f.content,
                                "summary": f.content_summary,
                            }
                            for f in ws_context.files
                        ]
            except Exception:
                logger.warning(
                    "workspace_context_load_failed",
                    task_id=str(command.task_id),
                    agent_id=self.agent_id,
                    exc_info=True,
                )

        return result

    async def _resolve_workspace_id(
        self, session: AsyncSession, command: AgentCommand
    ) -> str | None:
        """Resolve workspace_id from the task record.

        Args:
            session: Database session.
            command: The agent command containing task_id.

        Returns:
            Workspace ID string or None if not found.
        """
        from sqlalchemy import select

        from nexus.db.models import Task

        stmt = select(Task.workspace_id).where(Task.id == str(command.task_id))
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        return row

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

    # ─── Output validation ──────────────────────────────────────────────────

    # Patterns that suggest leaked secrets in output
    _SECRET_PATTERNS = (
        "sk-",
        "AKIA",
        "Bearer ",
        "ghp_",
        "gho_",
        "github_pat_",
        "xoxb-",
        "xoxp-",
        "-----BEGIN PRIVATE KEY",
    )
    _MAX_OUTPUT_SIZE = 100_000  # 100KB

    def _validate_output(self, response: AgentResponse) -> AgentResponse:
        """Validate agent output before publishing.

        Checks:
        1. Output is not empty for success status
        2. Output does not contain potential secret patterns
        3. Output size is within limits
        """
        if response.status == "success" and not response.output:
            logger.warning(
                "empty_output_on_success",
                agent_id=self.agent_id,
                task_id=str(response.task_id),
            )
            response.status = "partial"

        # Check for secret patterns in output
        if response.output:
            output_str = (
                json.dumps(response.output)
                if isinstance(response.output, dict)
                else str(response.output)
            )

            for pattern in self._SECRET_PATTERNS:
                if pattern in output_str:
                    logger.warning(
                        "potential_secret_in_output",
                        agent_id=self.agent_id,
                        task_id=str(response.task_id),
                        pattern=pattern[:4] + "***",
                    )
                    # Redact the pattern occurrence
                    output_str = output_str.replace(pattern, "[REDACTED]")

            # Check size limit
            if len(output_str) > self._MAX_OUTPUT_SIZE:
                logger.warning(
                    "output_truncated",
                    agent_id=self.agent_id,
                    task_id=str(response.task_id),
                    original_size=len(output_str),
                )
                if isinstance(response.output, dict):
                    response.output["_truncated"] = True
                    response.output["_original_size"] = len(output_str)

        return response

    # ─── PII sanitization ──────────────────────────────────────────────────

    def _sanitize_output_pii(self, response: AgentResponse, task_id: str) -> AgentResponse:
        """Sanitize agent output by redacting PII patterns.

        Enterprise-grade data protection: scans for API keys, emails,
        phone numbers, SSNs, credit cards, JWTs, and other sensitive
        data before the output leaves the agent boundary.
        """
        if response.output is None:
            return response

        try:
            from nexus.core.sanitization import sanitize_output

            response.output = sanitize_output(
                response.output,
                task_id=task_id,
                agent_id=self.agent_id,
            )
        except Exception as exc:
            logger.warning(
                "pii_sanitization_failed",
                agent_id=self.agent_id,
                task_id=task_id,
                error=str(exc),
            )
        return response

    # ─── Tool access enforcement ────────────────────────────────────────────

    def _allowed_tool_names(self) -> frozenset[str]:
        """Snapshot of tool names this role is permitted to call.

        Built lazily from `tools.registry.get_tools_for_role(self.role)` and
        cached on the instance. Invalidated when the system prompt reloads
        (which may rebuild the PydanticAgent with a different tool set).
        """
        cached = self._tool_access_cache
        if cached is not None:
            return cached
        try:
            from nexus.tools.registry import get_tools_for_role

            allowed = frozenset(fn.__name__ for fn in get_tools_for_role(self.role))
        except Exception as exc:
            logger.warning(
                "tool_access_snapshot_failed",
                agent_id=self.agent_id,
                role=self.role.value,
                error=str(exc),
            )
            allowed = frozenset()
        self._tool_access_cache = allowed
        return allowed

    async def _check_tool_access(
        self,
        tool_name: str,
        *,
        task_id: str | None = None,
        trace_id: str | None = None,
    ) -> None:
        """Runtime ACL check before invoking any tool from an LLM response.

        Enforces CLAUDE.md §20 NEVER rule 2 at the call site. The registry
        already filters tools at agent construction, but a hot-reloaded
        prompt or a future code path that bypasses the registry could still
        attempt an out-of-policy call. Raise loudly and write a security
        audit event when that happens.
        """
        allowed = self._allowed_tool_names()
        # Empty allow-list means we couldn't introspect the registry; fail
        # open (log only) rather than blocking every call by mistake.
        if not allowed:
            return
        if tool_name in allowed:
            return

        logger.error(
            "tool_access_denied",
            agent_id=self.agent_id,
            role=self.role.value,
            tool_name=tool_name,
            task_id=task_id,
            trace_id=trace_id,
        )
        try:
            await self._audit_outside_transaction(
                task_id or "unknown",
                trace_id or "unknown",
                AuditEventType.TASK_FAILED,
                {
                    "reason": "tool_access_denied",
                    "tool_name": tool_name,
                    "role": self.role.value,
                    "allowed": sorted(allowed),
                },
            )
        except Exception as audit_exc:
            logger.warning(
                "tool_access_denied_audit_failed",
                agent_id=self.agent_id,
                tool_name=tool_name,
                error=str(audit_exc),
            )
        raise ToolAccessDenied(
            f"agent role={self.role.value} is not permitted to call tool "
            f"'{tool_name}' (allowed: {sorted(allowed)})"
        )

    # ─── Orchestration detection ─────────────────────────────────────────────

    _ORCHESTRATION_ACTIONS = frozenset(
        {
            "decomposed",
            "subtask_tracked",
            "aggregated_and_sent_to_qa",
            "aggregated_and_sent_to_director",
            "director_synthesized_and_sent_to_qa",
            "conference_in_progress",
            "awaiting_plan_approval",
            "evaluation_passed",
            "evaluation_rework",
        }
    )

    def _is_orchestration_response(self, response: AgentResponse) -> bool:
        """Check if a response represents an ongoing orchestration flow.

        Returns True if the CEO is still tracking subtasks and needs its
        working memory to persist across multiple Kafka message cycles.
        """
        if response.output and isinstance(response.output, dict):
            return response.output.get("action") in self._ORCHESTRATION_ACTIONS
        return False

    # ─── Meeting room participation ─────────────────────────────────────────

    async def _handle_meeting_message(self, meeting_cmd: MeetingCommand) -> None:
        """Respond to a conference room question using this agent's LLM.

        Loads the meeting from Redis, generates a response via the LLM,
        submits the response to the meeting room, and saves state.

        Args:
            meeting_cmd: The meeting command with question and participants.
        """
        from nexus.core.kafka.meeting import get_meeting, save_meeting

        task_id = str(meeting_cmd.task_id)
        meeting_id = meeting_cmd.meeting_id

        room = await get_meeting(meeting_id)
        if room is None:
            logger.warning(
                "meeting_not_found_for_response",
                agent_id=self.agent_id,
                meeting_id=meeting_id,
                task_id=task_id,
            )
            return

        # Build context for the LLM
        transcript = room.get_transcript()
        meeting_prompt = (
            f"You are in a conference room meeting as the {self.role.value} agent.\n\n"
            f"Meeting topic: {room.config.topic}\n\n"
        )
        if transcript:
            meeting_prompt += f"Discussion so far:\n{transcript}\n\n"
        meeting_prompt += (
            f"Current question (Round {meeting_cmd.round_number}):\n"
            f"{meeting_cmd.question}\n\n"
            f"Provide your expert perspective as a {self.role.value}. "
            f"Be specific, concise, and constructive. "
            f"If you agree with another agent, say so and add new insights. "
            f"If you disagree, explain why with reasoning."
        )

        try:
            # Bound the LLM call so a stalled provider can't hang the meeting
            # indefinitely — the conference room needs a response (or a stub)
            # to make progress toward convergence.
            try:
                async with asyncio.timeout(self.MEETING_RESPONSE_TIMEOUT_SECONDS):
                    result = await self.llm_agent.run(meeting_prompt)
                response_text = result.output
            except TimeoutError:
                logger.warning(
                    "meeting_response_timed_out",
                    agent_id=self.agent_id,
                    meeting_id=meeting_id,
                    task_id=task_id,
                    timeout_seconds=self.MEETING_RESPONSE_TIMEOUT_SECONDS,
                )
                # Stub response lets convergence detection see this agent as
                # "spoke but had nothing new" rather than blocking the round.
                response_text = (
                    f"[{self.role.value} did not respond within "
                    f"{self.MEETING_RESPONSE_TIMEOUT_SECONDS}s — skipping this round.]"
                )

            await room.submit_response(
                response=response_text,
                sender_role=self.role.value,
                sender_id=self.agent_id,
            )
            await save_meeting(room)

            logger.info(
                "meeting_response_submitted",
                agent_id=self.agent_id,
                meeting_id=meeting_id,
                task_id=task_id,
                round=meeting_cmd.round_number,
                response_length=len(response_text),
            )

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(
                "meeting_response_failed",
                agent_id=self.agent_id,
                meeting_id=meeting_id,
                task_id=task_id,
                error=str(exc),
            )

    # ─── Broadcasting ────────────────────────────────────────────────────────

    async def _broadcast(self, event: dict[str, Any]) -> None:
        """Publish event to Redis pub/sub for dashboard WebSocket.

        Best-effort — if Redis is down, log and continue.
        Dashboard streaming is non-critical.
        """
        try:
            channel = f"agent_activity:{self.agent_id}"
            await redis_pubsub.publish(channel, json.dumps(event))
        except Exception as exc:
            logger.warning(
                "broadcast_failed",
                agent_id=self.agent_id,
                error=str(exc),
            )

    # ─── Heartbeat ───────────────────────────────────────────────────────────

    async def _heartbeat_loop(self) -> None:
        """Publish heartbeat every 30 seconds to agent.heartbeat topic."""
        while self._running:
            try:
                hb = HeartbeatMessage(agent_id=self.agent_id)
                producer = await get_producer()
                await producer.send_and_wait(
                    Topics.AGENT_HEARTBEAT,
                    value=hb.model_dump(mode="json"),
                )
            except Exception as exc:
                logger.warning(
                    "heartbeat_failed",
                    agent_id=self.agent_id,
                    error=str(exc),
                )
            await asyncio.sleep(30)

    # ─── Human escalation ────────────────────────────────────────────────────

    async def _request_human_input(self, command: AgentCommand, *, reason: str) -> None:
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

        await self._broadcast(
            {
                "event": "human_input_needed",
                "agent_id": self.agent_id,
                "task_id": str(command.task_id),
                "reason": reason,
            }
        )

        logger.info(
            "human_input_requested",
            agent_id=self.agent_id,
            task_id=str(command.task_id),
            reason=reason,
        )

    # ─── Dead letter handling ─────────────────────────────────────────────

    async def _handle_consumer_error(
        self,
        raw_message: dict[str, Any],
        topic: str,
        exc: Exception,
    ) -> None:
        """Handle message processing failure with retry tracking.

        After MAX_RETRIES failures, routes the message to the dead letter
        queue. Otherwise logs the error for the next retry attempt.
        """
        message_id = raw_message.get("message_id", "unknown")
        task_id = raw_message.get("task_id")

        retry_count = await increment_retry(str(message_id))

        if retry_count >= MAX_RETRIES:
            logger.error(
                "message_max_retries_exceeded",
                agent_id=self.agent_id,
                message_id=message_id,
                task_id=task_id,
                topic=topic,
                retry_count=retry_count,
                error=str(exc),
            )
            await publish_dead_letter(
                source_topic=topic,
                raw_message=raw_message,
                error=str(exc),
                task_id=str(task_id) if task_id else None,
                db_session_factory=self.db_session_factory,
            )
        else:
            logger.warning(
                "message_processing_retry",
                agent_id=self.agent_id,
                message_id=message_id,
                task_id=task_id,
                topic=topic,
                retry_count=retry_count,
                max_retries=MAX_RETRIES,
                error=str(exc),
            )

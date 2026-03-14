"""CEO Agent — full task decomposer and orchestrator (Phase 2).

The CEO receives tasks from task.queue (human) and a2a.inbound (external),
decomposes them into subtasks using LLM reasoning, delegates to specialist
agents, aggregates responses, and routes to QA for final review.

Also subscribes to agent.responses to track subtask completion and
trigger aggregation once all subtasks are done.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import UUID

import structlog
from pydantic_ai import Agent as PydanticAgent
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.agents.base import AgentBase
from nexus.db.models import AgentRole, Task, TaskStatus
from nexus.kafka.producer import publish
from nexus.kafka.schemas import AgentCommand, AgentResponse
from nexus.kafka.topics import Topics
from nexus.llm.usage import calculate_cost, record_usage
from nexus.memory.episodic import write_episode
from nexus.memory.working import get_working_memory, set_working_memory

logger = structlog.get_logger()

_MAX_RETRIES = 5
_RETRY_BACKOFF_SECONDS = [5.0, 10.0, 20.0, 30.0, 45.0]

# Valid specialist roles the CEO can delegate to
_DELEGATABLE_ROLES = {"engineer", "analyst", "writer"}


class CEOAgent(AgentBase):
    """CEO agent — decomposes tasks and orchestrates multi-agent workflows."""

    async def handle_task(
        self, message: AgentCommand, session: AsyncSession
    ) -> AgentResponse:
        """Route based on message source: new task or agent response."""
        task_id = str(message.task_id)
        trace_id = str(message.trace_id)

        # Check if this is an agent response (aggregation trigger)
        if message.payload.get("_response_aggregation"):
            return await self._handle_agent_response(message, session)

        logger.info(
            "ceo_task_received",
            task_id=task_id,
            trace_id=trace_id,
            instruction=message.instruction[:200],
        )

        # Use LLM to decompose the task into subtasks
        subtasks = await self._decompose_task(message, session)

        if not subtasks:
            # BACKLOG-021: Track decomposition failure in episodic memory
            # so Prompt Creator can analyze patterns in CEO failures.
            logger.warning(
                "ceo_decomposition_empty",
                task_id=task_id,
                trace_id=trace_id,
                instruction_preview=message.instruction[:200],
                event_tag="decomposition_failure",  # structured tag for analytics queries
            )
            try:
                await write_episode(
                    session=session,
                    agent_id=self.agent_id,
                    task_id=task_id,
                    summary=f"CEO decomposition failed for: {message.instruction[:300]}",
                    full_context={
                        "instruction": message.instruction,
                        "failure_type": "decomposition_empty",
                        "fallback": "engineer",
                    },
                    outcome="failed",
                    tokens_used=0,
                    duration_seconds=0,
                )
            except Exception as mem_exc:
                logger.warning(
                    "ceo_decomposition_failure_write_error",
                    task_id=task_id,
                    error=str(mem_exc),
                )
            # Fallback: delegate everything to engineer
            subtasks = [{"role": "engineer", "instruction": message.instruction, "depends_on": []}]
        else:
            logger.info(
                "ceo_decomposition_success",
                task_id=task_id,
                trace_id=trace_id,
                subtask_count=len(subtasks),
                event_tag="decomposition_success",  # structured tag for analytics queries
            )

        # Create subtasks in DB and dispatch independent ones
        subtask_ids = await self._create_subtasks(session, message, subtasks)
        await session.commit()

        # Store subtask tracking state in Redis working memory
        tracking = {
            "parent_task_id": task_id,
            "original_instruction": message.instruction,
            "subtasks": {
                str(sid): {
                    "role": st["role"],
                    "instruction": st["instruction"],
                    "depends_on": [str(subtask_ids[i]) for i in st.get("depends_on", [])],
                    "status": "pending",
                    "output": None,
                }
                for sid, st in zip(subtask_ids, subtasks)
            },
            "total": len(subtask_ids),
            "completed": 0,
        }
        await set_working_memory(self.agent_id, task_id, tracking)

        # Dispatch subtasks that have no dependencies
        dispatched = 0
        for sid, st in zip(subtask_ids, subtasks):
            if not st.get("depends_on"):
                await self._dispatch_subtask(
                    task_id=str(sid),
                    trace_id=trace_id,
                    role=st["role"],
                    instruction=st["instruction"],
                    parent_task_id=task_id,
                )
                tracking["subtasks"][str(sid)]["status"] = "dispatched"
                dispatched += 1

        await set_working_memory(self.agent_id, task_id, tracking)

        logger.info(
            "ceo_task_decomposed",
            task_id=task_id,
            trace_id=trace_id,
            subtask_count=len(subtask_ids),
            dispatched=dispatched,
        )

        return AgentResponse(
            task_id=message.task_id,
            trace_id=message.trace_id,
            agent_id=self.agent_id,
            payload={},
            status="success",
            output={
                "action": "decomposed",
                "subtask_count": len(subtask_ids),
                "subtask_ids": [str(s) for s in subtask_ids],
            },
            tokens_used=0,
        )

    async def _decompose_task(
        self, message: AgentCommand, session: AsyncSession
    ) -> list[dict[str, Any]]:
        """Use LLM to analyze the task and produce a decomposition plan."""
        task_id = str(message.task_id)

        decompose_prompt = (
            f"Decompose the following task into subtasks.\n\n"
            f"Task: {message.instruction}\n\n"
            f"Available specialist agents:\n"
            f"- engineer: code, debugging, technical tasks\n"
            f"- analyst: research, data analysis, reports\n"
            f"- writer: content, emails, documentation\n\n"
            f"Respond ONLY with a JSON array of subtasks. Each subtask must have:\n"
            f'- "role": one of "engineer", "analyst", "writer"\n'
            f'- "instruction": clear, specific instructions\n'
            f'- "depends_on": array of subtask indices (0-based) this depends on\n\n'
            f"For simple single-agent tasks, return a single-item array.\n"
            'Example: [{"role": "analyst", "instruction": "Research...", "depends_on": []}]'
        )

        try:
            result = await self._run_with_retry(decompose_prompt, task_id)

            # Record LLM usage
            try:
                usage = result.usage()
                input_tokens = usage.request_tokens or 0
                output_tokens = usage.response_tokens or 0
                model_obj = self.llm_agent.model
                model_name = getattr(model_obj, "model_name", str(model_obj))[:100]
                await record_usage(
                    session=session,
                    task_id=task_id,
                    agent_id=self.agent_id,
                    model_name=model_name,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=calculate_cost(model_name, input_tokens, output_tokens),
                )
            except Exception as exc:
                logger.warning("ceo_usage_tracking_failed", task_id=task_id, error=str(exc))

            # Parse JSON from LLM response
            raw = result.output.strip()
            # Handle markdown code blocks
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
                raw = raw.rsplit("```", 1)[0]

            subtasks = json.loads(raw)

            # Validate structure
            if not isinstance(subtasks, list) or not subtasks:
                logger.warning("ceo_invalid_decomposition", task_id=task_id, raw=raw[:200])
                return []

            validated: list[dict[str, Any]] = []
            for st in subtasks:
                role = st.get("role", "engineer")
                if role not in _DELEGATABLE_ROLES:
                    role = "engineer"
                validated.append({
                    "role": role,
                    "instruction": st.get("instruction", message.instruction),
                    "depends_on": st.get("depends_on", []),
                })
            return validated

        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning("ceo_decomposition_parse_error", task_id=task_id, error=str(exc))
            return []
        except Exception as exc:
            logger.error("ceo_decomposition_failed", task_id=task_id, error=str(exc))
            return []

    async def _create_subtasks(
        self,
        session: AsyncSession,
        parent_message: AgentCommand,
        subtasks: list[dict[str, Any]],
    ) -> list[UUID]:
        """Create subtask records in the tasks table with parent_task_id linkage."""
        subtask_ids: list[UUID] = []
        parent_task_id = str(parent_message.task_id)

        for st in subtasks:
            subtask = Task(
                trace_id=str(parent_message.trace_id),
                parent_task_id=parent_task_id,
                instruction=st["instruction"],
                status=TaskStatus.QUEUED.value,
                source="internal",
            )
            session.add(subtask)
            await session.flush()
            subtask_ids.append(subtask.id)

            logger.info(
                "subtask_created",
                subtask_id=str(subtask.id),
                parent_task_id=parent_task_id,
                role=st["role"],
            )

        return subtask_ids

    async def _dispatch_subtask(
        self,
        *,
        task_id: str,
        trace_id: str,
        role: str,
        instruction: str,
        parent_task_id: str,
    ) -> None:
        """Publish a subtask command to agent.commands."""
        command = AgentCommand(
            task_id=UUID(task_id),
            trace_id=UUID(trace_id),
            agent_id=self.agent_id,
            payload={
                "parent_task_id": parent_task_id,
                "original_role": role,
            },
            target_role=role,
            instruction=instruction,
        )
        await publish(Topics.AGENT_COMMANDS, command, key=task_id)

        logger.info(
            "subtask_dispatched",
            task_id=task_id,
            target_role=role,
            parent_task_id=parent_task_id,
        )

    async def _handle_agent_response(
        self, message: AgentCommand, session: AsyncSession
    ) -> AgentResponse:
        """Handle an agent response — update tracking and aggregate if all done.

        This is called when the result consumer forwards responses for subtasks
        that belong to a multi-agent workflow.
        """
        subtask_id = str(message.payload.get("subtask_id", ""))
        parent_task_id = str(message.payload.get("parent_task_id", ""))
        subtask_output = message.payload.get("subtask_output", "")
        subtask_status = message.payload.get("subtask_status", "success")

        if not parent_task_id:
            logger.warning("ceo_response_missing_parent", subtask_id=subtask_id)
            return AgentResponse(
                task_id=message.task_id,
                trace_id=message.trace_id,
                agent_id=self.agent_id,
                payload={},
                status="failed",
                error="Missing parent_task_id in response",
            )

        # Load tracking state from working memory
        tracking = await get_working_memory(self.agent_id, parent_task_id)
        if not tracking:
            logger.warning("ceo_tracking_not_found", parent_task_id=parent_task_id)
            # Use orchestration action to prevent infinite forwarding loop:
            # without this, the "failed" response goes to agent.responses →
            # result consumer sees it's a subtask → forwards back → repeat.
            return AgentResponse(
                task_id=message.task_id,
                trace_id=message.trace_id,
                agent_id=self.agent_id,
                payload={},
                status="failed",
                output={"action": "subtask_tracked"},
                error="No tracking state found",
            )

        # Update subtask status — count any terminal status (including failed)
        # so the workflow doesn't get stuck when a subtask fails
        if subtask_id in tracking["subtasks"]:
            tracking["subtasks"][subtask_id]["status"] = subtask_status
            tracking["subtasks"][subtask_id]["output"] = subtask_output
            if subtask_status in ("success", "completed", "failed", "partial", "escalated"):
                tracking["completed"] = tracking.get("completed", 0) + 1

        await set_working_memory(self.agent_id, parent_task_id, tracking)

        # Check for newly unblocked subtasks (dependencies resolved)
        await self._dispatch_unblocked(parent_task_id, tracking, str(message.trace_id))

        # Check if all subtasks are complete
        if tracking["completed"] >= tracking["total"]:
            return await self._aggregate_and_route_to_qa(
                parent_task_id, tracking, message, session
            )

        logger.info(
            "ceo_subtask_completed",
            subtask_id=subtask_id,
            parent_task_id=parent_task_id,
            completed=tracking["completed"],
            total=tracking["total"],
        )

        return AgentResponse(
            task_id=message.task_id,
            trace_id=message.trace_id,
            agent_id=self.agent_id,
            payload={},
            status="success",
            output={
                "action": "subtask_tracked",
                "completed": tracking["completed"],
                "total": tracking["total"],
            },
            tokens_used=0,
        )

    async def _dispatch_unblocked(
        self, parent_task_id: str, tracking: dict[str, Any], trace_id: str
    ) -> None:
        """Dispatch subtasks whose dependencies are now all resolved (done or failed)."""
        completed_ids = {
            sid for sid, st in tracking["subtasks"].items()
            if st["status"] in ("success", "completed", "failed", "partial", "escalated")
        }

        for sid, st in tracking["subtasks"].items():
            if st["status"] not in ("pending",):
                continue
            deps = st.get("depends_on", [])
            if all(d in completed_ids for d in deps):
                # Include outputs from dependencies in the instruction
                dep_context = ""
                for dep_id in deps:
                    dep_output = tracking["subtasks"].get(dep_id, {}).get("output", "")
                    if dep_output:
                        dep_context += f"\n\nContext from previous step:\n{dep_output}"

                instruction = st["instruction"]
                if dep_context:
                    instruction += dep_context

                await self._dispatch_subtask(
                    task_id=sid,
                    trace_id=trace_id,
                    role=st["role"],
                    instruction=instruction,
                    parent_task_id=parent_task_id,
                )
                st["status"] = "dispatched"

        await set_working_memory(self.agent_id, parent_task_id, tracking)

    async def _aggregate_and_route_to_qa(
        self,
        parent_task_id: str,
        tracking: dict[str, Any],
        message: AgentCommand,
        session: AsyncSession,
    ) -> AgentResponse:
        """Aggregate all subtask outputs and send to QA for review."""
        # Collect all outputs
        outputs: list[str] = []
        for sid, st in tracking["subtasks"].items():
            output = st.get("output", "(no output)")
            outputs.append(f"[{st['role'].upper()}] {output}")

        aggregated = "\n\n---\n\n".join(outputs)

        logger.info(
            "ceo_aggregating_results",
            parent_task_id=parent_task_id,
            subtask_count=tracking["total"],
        )

        # Route to QA for review
        qa_command = AgentCommand(
            task_id=UUID(parent_task_id),
            trace_id=message.trace_id,
            agent_id=self.agent_id,
            payload={
                "aggregated_output": aggregated,
                "original_instruction": tracking.get("original_instruction", ""),
                "subtask_count": tracking["total"],
                "original_role": "ceo",
            },
            target_role=AgentRole.QA.value,
            instruction=f"Review the following aggregated output for the task:\n\n"
                        f"Original request: {tracking.get('original_instruction', '')}\n\n"
                        f"Aggregated output:\n{aggregated}",
        )
        await publish(Topics.TASK_REVIEW_QUEUE, qa_command, key=parent_task_id)

        logger.info(
            "ceo_routed_to_qa",
            parent_task_id=parent_task_id,
        )

        return AgentResponse(
            task_id=message.task_id,
            trace_id=message.trace_id,
            agent_id=self.agent_id,
            payload={},
            status="success",
            output={
                "action": "aggregated_and_sent_to_qa",
                "parent_task_id": parent_task_id,
                "subtask_count": tracking["total"],
            },
            tokens_used=0,
        )

    async def _run_with_retry(self, user_message: str, task_id: str) -> object:
        """Run LLM agent with retry logic for transient errors."""
        last_error: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                return await self.llm_agent.run(user_message)
            except Exception as exc:
                last_error = exc
                error_str = str(exc)

                if "429" in error_str or "rate_limit" in error_str.lower():
                    backoff = _RETRY_BACKOFF_SECONDS[min(attempt, len(_RETRY_BACKOFF_SECONDS) - 1)]
                    logger.warning(
                        "rate_limit_retry",
                        task_id=task_id,
                        attempt=attempt + 1,
                        backoff_seconds=backoff,
                    )
                    await asyncio.sleep(backoff)
                    continue

                if "tool_use_failed" in error_str or "tool call validation" in error_str:
                    logger.warning(
                        "tool_call_failed_retry_without_tools",
                        task_id=task_id,
                        attempt=attempt + 1,
                    )
                    no_tools_agent = PydanticAgent(
                        model=self.llm_agent.model,
                        system_prompt=(
                            "You are a CEO who decomposes tasks. "
                            "Respond with a JSON array of subtasks."
                        ),
                    )
                    return await no_tools_agent.run(user_message)

                raise

        raise last_error  # type: ignore[misc]

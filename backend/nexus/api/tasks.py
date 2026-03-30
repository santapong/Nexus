from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import structlog
from litestar import Controller, Request, get, post
from litestar.params import Parameter
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.api.auth import get_auth_user_from_request
from nexus.core.kafka.producer import publish
from nexus.core.kafka.schemas import AgentCommand, PlanApprovalMessage
from nexus.core.kafka.topics import Topics
from nexus.db.models import (
    AgentRole,
    ApprovalStatus,
    EpisodicMemory,
    HumanApproval,
    LLMUsage,
    Task,
    TaskSource,
    TaskStatus,
)

logger = structlog.get_logger()


class CreateTaskRequest(BaseModel):
    instruction: str
    source: str = TaskSource.HUMAN.value
    require_meeting: bool | None = None  # Override meeting auto-detection


class ApprovePlanRequest(BaseModel):
    """Request body for approving or rejecting a task plan."""

    approved: bool
    feedback: str = ""


class TaskResponse(BaseModel):
    id: str
    trace_id: str
    instruction: str
    status: str
    source: str
    tokens_used: int
    output: dict[str, Any] | None = None
    error: str | None = None
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None


def _get_workspace_id(request: Request[Any, Any, Any]) -> str | None:
    """Extract workspace_id from JWT via request state or auth header.

    Args:
        request: Litestar request object.

    Returns:
        Workspace ID string or None if not authenticated.
    """
    auth_user = get_auth_user_from_request(request)
    if auth_user is not None:
        return auth_user.workspace_id
    return None


class TaskController(Controller):
    path = "/tasks"

    @post()
    async def create_task(
        self,
        data: CreateTaskRequest,
        request: Request[Any, Any, Any],
        db_session: AsyncSession,
    ) -> dict[str, str]:
        """Create a new task and publish to task.queue."""
        from nexus.api.middleware import validate_instruction

        validation = validate_instruction(data.instruction)
        if not validation.valid:
            return {"error": validation.error or "Invalid instruction", "status": "rejected"}

        workspace_id = _get_workspace_id(request)

        trace_id = str(uuid4())
        task = Task(
            trace_id=trace_id,
            instruction=data.instruction,
            status=TaskStatus.QUEUED.value,
            source=data.source,
            workspace_id=workspace_id,
        )
        db_session.add(task)
        await db_session.flush()
        await db_session.commit()

        logger.info(
            "task_created",
            task_id=str(task.id),
            trace_id=trace_id,
            workspace_id=workspace_id,
        )

        # Publish to Kafka task.queue — CEO will pick this up
        task_payload: dict[str, Any] = {"instruction": data.instruction, "source": data.source}
        if data.require_meeting is not None:
            task_payload["require_meeting"] = data.require_meeting

        kafka_msg = AgentCommand(
            task_id=task.id,
            trace_id=UUID(trace_id),
            agent_id="api",
            payload=task_payload,
            target_role=AgentRole.CEO.value,
            instruction=data.instruction,
        )
        try:
            await publish(Topics.TASK_QUEUE, kafka_msg, key=str(task.id))
        except Exception as exc:
            # Mark task as failed since it won't reach the agent queue
            task.status = TaskStatus.FAILED.value
            task.error = f"Failed to publish to Kafka: {exc}"
            await db_session.commit()
            logger.error(
                "task_kafka_publish_failed",
                task_id=str(task.id),
                error=str(exc),
            )
            return {
                "task_id": str(task.id),
                "trace_id": trace_id,
                "status": "failed",
                "error": "Task created but could not be queued. Try again.",
            }

        return {
            "task_id": str(task.id),
            "trace_id": trace_id,
            "status": "queued",
        }

    @get()
    async def list_tasks(
        self,
        request: Request[Any, Any, Any],
        db_session: AsyncSession,
        status: str | None = Parameter(query="status", default=None),
        limit: int = Parameter(query="limit", default=50, ge=1, le=200),
        offset: int = Parameter(query="offset", default=0, ge=0),
    ) -> list[TaskResponse]:
        """List tasks with optional status filter, scoped to workspace."""
        workspace_id = _get_workspace_id(request)

        stmt = select(Task).order_by(Task.created_at.desc()).limit(limit).offset(offset)
        if workspace_id:
            stmt = stmt.where(Task.workspace_id == workspace_id)
        if status:
            stmt = stmt.where(Task.status == status)
        result = await db_session.execute(stmt)
        tasks = result.scalars().all()

        return [
            TaskResponse(
                id=str(t.id),
                trace_id=t.trace_id,
                instruction=t.instruction,
                status=t.status,
                source=t.source,
                tokens_used=t.tokens_used,
                output=t.output,
                error=t.error,
                created_at=str(t.created_at),
                started_at=str(t.started_at) if t.started_at else None,
                completed_at=str(t.completed_at) if t.completed_at else None,
            )
            for t in tasks
        ]

    @get("/{task_id:str}")
    async def get_task(
        self,
        task_id: str,
        request: Request[Any, Any, Any],
        db_session: AsyncSession,
    ) -> TaskResponse | dict[str, str]:
        """Get a single task by ID, scoped to workspace."""
        workspace_id = _get_workspace_id(request)

        stmt = select(Task).where(Task.id == task_id)
        if workspace_id:
            stmt = stmt.where(Task.workspace_id == workspace_id)
        result = await db_session.execute(stmt)
        task = result.scalar_one_or_none()

        if task is None:
            return {"error": "Task not found"}

        return TaskResponse(
            id=str(task.id),
            trace_id=task.trace_id,
            instruction=task.instruction,
            status=task.status,
            source=task.source,
            tokens_used=task.tokens_used,
            output=task.output,
            error=task.error,
            created_at=str(task.created_at),
            started_at=str(task.started_at) if task.started_at else None,
            completed_at=str(task.completed_at) if task.completed_at else None,
        )

    @get("/{task_id:str}/trace")
    async def get_task_trace(
        self,
        task_id: str,
        request: Request[Any, Any, Any],
        db_session: AsyncSession,
    ) -> dict[str, Any]:
        """Get a task with its full subtask tree for multi-agent tracing."""
        workspace_id = _get_workspace_id(request)

        stmt = select(Task).where(Task.id == task_id)
        if workspace_id:
            stmt = stmt.where(Task.workspace_id == workspace_id)
        result = await db_session.execute(stmt)
        parent = result.scalar_one_or_none()

        if parent is None:
            return {"error": "Task not found"}

        subtask_stmt = select(Task).where(Task.parent_task_id == task_id).order_by(Task.created_at)
        subtask_result = await db_session.execute(subtask_stmt)
        subtasks = subtask_result.scalars().all()

        def _to_dict(t: Task) -> dict[str, Any]:
            return {
                "id": str(t.id),
                "trace_id": t.trace_id,
                "parent_task_id": t.parent_task_id,
                "instruction": t.instruction,
                "status": t.status,
                "source": t.source,
                "tokens_used": t.tokens_used,
                "output": t.output,
                "error": t.error,
                "created_at": str(t.created_at),
                "started_at": str(t.started_at) if t.started_at else None,
                "completed_at": str(t.completed_at) if t.completed_at else None,
            }

        return {
            "parent": _to_dict(parent),
            "subtasks": [_to_dict(st) for st in subtasks],
            "total_subtasks": len(subtasks),
            "completed_subtasks": sum(
                1 for st in subtasks if st.status == TaskStatus.COMPLETED.value
            ),
        }

    @get("/{task_id:str}/replay")
    async def get_task_replay(
        self,
        task_id: str,
        request: Request[Any, Any, Any],
        db_session: AsyncSession,
    ) -> dict[str, Any]:
        """Get a task replay — episodic memory + LLM usage timeline.

        Returns the full agent execution timeline including conversation
        turns, tool calls, memory lookups, and LLM usage for debugging
        and understanding agent behavior.

        Args:
            task_id: The task UUID to replay.
            request: Litestar request object.
            db_session: Async database session.

        Returns:
            Dict with task info, episodic memories, and LLM usage entries.
        """
        workspace_id = _get_workspace_id(request)

        # Get the task
        task_stmt = select(Task).where(Task.id == task_id)
        if workspace_id:
            task_stmt = task_stmt.where(Task.workspace_id == workspace_id)
        task_result = await db_session.execute(task_stmt)
        task = task_result.scalar_one_or_none()

        if task is None:
            return {"error": "Task not found"}

        # Get episodic memories for this task
        mem_stmt = (
            select(EpisodicMemory)
            .where(EpisodicMemory.task_id == task_id)
            .order_by(EpisodicMemory.created_at)
        )
        mem_result = await db_session.execute(mem_stmt)
        memories = mem_result.scalars().all()

        # Get LLM usage for this task
        usage_stmt = (
            select(LLMUsage).where(LLMUsage.task_id == task_id).order_by(LLMUsage.created_at)
        )
        usage_result = await db_session.execute(usage_stmt)
        usages = usage_result.scalars().all()

        # Also check subtasks
        subtask_stmt = select(Task.id).where(Task.parent_task_id == task_id)
        subtask_result = await db_session.execute(subtask_stmt)
        subtask_ids = [str(row[0]) for row in subtask_result.all()]

        # Batch-fetch memories and usage for all subtasks (fixes N+1 query)
        subtask_memories: list[dict[str, Any]] = []
        subtask_usages: list[dict[str, Any]] = []
        if subtask_ids:
            sub_mem_stmt = (
                select(EpisodicMemory)
                .where(EpisodicMemory.task_id.in_(subtask_ids))
                .order_by(EpisodicMemory.created_at)
            )
            sub_mem_result = await db_session.execute(sub_mem_stmt)
            for m in sub_mem_result.scalars().all():
                subtask_memories.append(
                    {
                        "subtask_id": str(m.task_id),
                        "agent_id": m.agent_id,
                        "summary": m.summary,
                        "outcome": m.outcome,
                        "tools_used": m.tools_used,
                        "tokens_used": m.tokens_used,
                        "duration_seconds": m.duration_seconds,
                        "created_at": str(m.created_at),
                    }
                )

            sub_usage_stmt = (
                select(LLMUsage)
                .where(LLMUsage.task_id.in_(subtask_ids))
                .order_by(LLMUsage.created_at)
            )
            sub_usage_result = await db_session.execute(sub_usage_stmt)
            for u in sub_usage_result.scalars().all():
                subtask_usages.append(
                    {
                        "subtask_id": str(u.task_id),
                        "agent_id": u.agent_id,
                        "model_name": u.model_name,
                        "input_tokens": u.input_tokens,
                        "output_tokens": u.output_tokens,
                        "cost_usd": u.cost_usd,
                        "created_at": str(u.created_at),
                    }
                )

        return {
            "task": {
                "id": str(task.id),
                "instruction": task.instruction,
                "status": task.status,
                "tokens_used": task.tokens_used,
                "created_at": str(task.created_at),
                "completed_at": str(task.completed_at) if task.completed_at else None,
            },
            "episodes": [
                {
                    "agent_id": m.agent_id,
                    "summary": m.summary,
                    "full_context": m.full_context,
                    "outcome": m.outcome,
                    "tools_used": m.tools_used,
                    "tokens_used": m.tokens_used,
                    "duration_seconds": m.duration_seconds,
                    "importance_score": m.importance_score,
                    "created_at": str(m.created_at),
                }
                for m in memories
            ],
            "llm_calls": [
                {
                    "agent_id": u.agent_id,
                    "model_name": u.model_name,
                    "input_tokens": u.input_tokens,
                    "output_tokens": u.output_tokens,
                    "cost_usd": u.cost_usd,
                    "created_at": str(u.created_at),
                }
                for u in usages
            ],
            "subtask_episodes": subtask_memories,
            "subtask_llm_calls": subtask_usages,
            "total_episodes": len(memories) + len(subtask_memories),
            "total_llm_calls": len(usages) + len(subtask_usages),
        }

    @post("/{task_id:str}/approve-plan")
    async def approve_plan(
        self,
        task_id: str,
        data: ApprovePlanRequest,
        request: Request[Any, Any, Any],
        db_session: AsyncSession,
    ) -> dict[str, Any]:
        """Approve or reject a task's execution plan.

        After agents extract requirements and discuss in the conference room,
        the plan is presented to the user. This endpoint lets the user approve
        (proceed to execution) or reject (re-plan with feedback).
        """
        workspace_id = _get_workspace_id(request)

        # Verify task exists and is awaiting approval
        stmt = select(Task).where(Task.id == task_id)
        if workspace_id:
            stmt = stmt.where(Task.workspace_id == workspace_id)
        result = await db_session.execute(stmt)
        task = result.scalar_one_or_none()

        if task is None:
            return {"error": "Task not found"}

        if task.status != TaskStatus.AWAITING_APPROVAL.value:
            return {
                "error": f"Task is not awaiting approval (current status: {task.status})",
            }

        # Resolve the pending plan approval record
        approval_stmt = (
            select(HumanApproval)
            .where(HumanApproval.task_id == task_id)
            .where(HumanApproval.tool_name == "plan_approval")
            .where(HumanApproval.status == ApprovalStatus.PENDING.value)
        )
        approval_result = await db_session.execute(approval_stmt)
        approval = approval_result.scalar_one_or_none()

        if approval:
            from nexus.tools.guards import resolve_approval

            auth_user = get_auth_user_from_request(request)
            resolved_by = auth_user.email if auth_user else "anonymous"

            await resolve_approval(
                session=db_session,
                approval_id=str(approval.id),
                approved=data.approved,
                resolved_by=resolved_by,
            )

        # Publish plan approval to Kafka for CEO to consume
        approval_msg = AgentCommand(
            task_id=UUID(task_id),
            trace_id=UUID(task.trace_id),
            agent_id="api",
            payload={
                "_plan_approval": True,
                "approved": data.approved,
                "feedback": data.feedback,
            },
            target_role=AgentRole.CEO.value,
            instruction=f"Plan {'approved' if data.approved else 'rejected'}: {data.feedback}",
        )
        await publish(Topics.PLAN_APPROVAL, approval_msg, key=task_id)

        await db_session.commit()

        status = "approved" if data.approved else "rejected"
        logger.info(
            "task_plan_approval",
            task_id=task_id,
            approved=data.approved,
            feedback=data.feedback[:200] if data.feedback else "",
        )

        return {
            "task_id": task_id,
            "status": status,
            "message": f"Plan {status}. {'Execution will begin shortly.' if data.approved else 'CEO will re-plan with your feedback.'}",
        }

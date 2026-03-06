from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import structlog
from litestar import Controller, get, post
from litestar.params import Parameter
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import AgentRole, Task, TaskSource, TaskStatus
from nexus.kafka.producer import publish
from nexus.kafka.schemas import AgentCommand
from nexus.kafka.topics import Topics

logger = structlog.get_logger()


class CreateTaskRequest(BaseModel):
    instruction: str
    source: str = TaskSource.HUMAN.value


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


class TaskController(Controller):
    path = "/tasks"

    @post()
    async def create_task(
        self,
        data: CreateTaskRequest,
        db_session: AsyncSession,
    ) -> dict[str, str]:
        """Create a new task and publish to task.queue."""
        trace_id = str(uuid4())
        task = Task(
            trace_id=trace_id,
            instruction=data.instruction,
            status=TaskStatus.QUEUED.value,
            source=data.source,
        )
        db_session.add(task)
        await db_session.flush()

        logger.info(
            "task_created",
            task_id=str(task.id),
            trace_id=trace_id,
        )

        # Publish to Kafka task.queue — CEO will pick this up
        kafka_msg = AgentCommand(
            task_id=task.id,
            trace_id=UUID(trace_id),
            agent_id="api",
            payload={"instruction": data.instruction, "source": data.source},
            target_role=AgentRole.CEO.value,
            instruction=data.instruction,
        )
        await publish(Topics.TASK_QUEUE, kafka_msg, key=str(task.id))

        return {"task_id": str(task.id), "trace_id": trace_id, "status": "queued"}

    @get()
    async def list_tasks(
        self,
        db_session: AsyncSession,
        status: str | None = Parameter(query="status", default=None),
        limit: int = Parameter(query="limit", default=50, ge=1, le=200),
        offset: int = Parameter(query="offset", default=0, ge=0),
    ) -> list[TaskResponse]:
        """List tasks with optional status filter."""
        stmt = select(Task).order_by(Task.created_at.desc()).limit(limit).offset(offset)
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
        db_session: AsyncSession,
    ) -> TaskResponse | dict[str, str]:
        """Get a single task by ID."""
        stmt = select(Task).where(Task.id == task_id)
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

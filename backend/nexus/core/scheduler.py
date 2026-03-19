"""Scheduled & recurring tasks — cron-based task scheduler.

Evaluates cron expressions to find due schedules, creates tasks,
and publishes them to Kafka. Uses croniter for next-run calculation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import structlog
from croniter import croniter
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.core.kafka.producer import publish
from nexus.core.kafka.schemas import KafkaMessage
from nexus.core.kafka.topics import Topics
from nexus.db.models import Task, TaskSchedule, TaskStatus

logger = structlog.get_logger()


def calculate_next_run(cron_expression: str, timezone: str = "UTC") -> datetime:
    """Calculate the next run time from a cron expression.

    Args:
        cron_expression: Standard cron expression (5 fields).
        timezone: IANA timezone name.

    Returns:
        Next run datetime in UTC.
    """
    base = datetime.now(UTC)
    cron = croniter(cron_expression, base)
    next_dt: datetime = cron.get_next(datetime)
    if next_dt.tzinfo is None:
        next_dt = next_dt.replace(tzinfo=UTC)
    return next_dt


async def check_due_schedules(session: AsyncSession) -> list[TaskSchedule]:
    """Find all active schedules that are due to run.

    Args:
        session: Database session.

    Returns:
        List of due TaskSchedule records.
    """
    now = datetime.now(UTC)
    stmt = (
        select(TaskSchedule)
        .where(
            TaskSchedule.is_active.is_(True),
            TaskSchedule.next_run_at <= now,
        )
        .order_by(TaskSchedule.next_run_at)
    )

    result = await session.execute(stmt)
    return list(result.scalars().all())


async def execute_schedule(
    session: AsyncSession,
    schedule: TaskSchedule,
) -> str:
    """Execute a scheduled task: create task record and publish to Kafka.

    Args:
        session: Database session.
        schedule: The schedule to execute.

    Returns:
        The created task ID.
    """
    task_id = str(uuid4())
    trace_id = str(uuid4())

    # Create task record
    task = Task(
        id=task_id,
        trace_id=trace_id,
        instruction=schedule.instruction,
        status=TaskStatus.QUEUED.value,
        source="scheduled",
        workspace_id=schedule.workspace_id,
        schedule_id=str(schedule.id),
    )
    session.add(task)

    # Update schedule metadata
    next_run = calculate_next_run(schedule.cron_expression, schedule.timezone)
    stmt = (
        update(TaskSchedule)
        .where(TaskSchedule.id == schedule.id)
        .values(
            last_run_at=datetime.now(UTC),
            next_run_at=next_run,
            total_runs=TaskSchedule.total_runs + 1,
        )
    )
    await session.execute(stmt)

    # Check if max_runs reached
    if schedule.max_runs is not None and (schedule.total_runs + 1) >= schedule.max_runs:
        deactivate_stmt = (
            update(TaskSchedule).where(TaskSchedule.id == schedule.id).values(is_active=False)
        )
        await session.execute(deactivate_stmt)
        logger.info(
            "schedule_max_runs_reached",
            schedule_id=str(schedule.id),
            total_runs=schedule.total_runs + 1,
        )

    await session.flush()

    # Publish to Kafka
    msg = KafkaMessage(
        task_id=task_id,  # type: ignore[arg-type]
        trace_id=trace_id,  # type: ignore[arg-type]
        agent_id="scheduler",
        payload={
            "instruction": schedule.instruction,
            "target_role": schedule.target_role,
            "schedule_id": str(schedule.id),
            "schedule_name": schedule.name,
        },
    )
    await publish(Topics.TASK_QUEUE, msg, key=task_id)

    logger.info(
        "scheduled_task_created",
        task_id=task_id,
        schedule_id=str(schedule.id),
        schedule_name=schedule.name,
        next_run_at=next_run.isoformat(),
    )

    return task_id


async def run_scheduler_tick(session: AsyncSession) -> int:
    """Run one scheduler tick: check due schedules and execute them.

    Args:
        session: Database session.

    Returns:
        Number of tasks created.
    """
    due_schedules = await check_due_schedules(session)

    if not due_schedules:
        return 0

    tasks_created = 0
    for schedule in due_schedules:
        try:
            await execute_schedule(session, schedule)
            tasks_created += 1
        except Exception as exc:
            logger.error(
                "schedule_execution_failed",
                schedule_id=str(schedule.id),
                error=str(exc),
                exc_info=True,
            )

    if tasks_created > 0:
        await session.commit()
        logger.info("scheduler_tick_completed", tasks_created=tasks_created)

    return tasks_created


async def create_schedule(
    session: AsyncSession,
    *,
    workspace_id: str,
    name: str,
    cron_expression: str,
    instruction: str,
    target_role: str,
    timezone: str = "UTC",
    max_runs: int | None = None,
    metadata: dict[str, object] | None = None,
) -> TaskSchedule:
    """Create a new task schedule.

    Validates the cron expression and calculates the first next_run_at.

    Args:
        session: Database session.
        workspace_id: Owning workspace.
        name: Human-readable schedule name.
        cron_expression: Standard 5-field cron expression.
        instruction: Task instruction template.
        target_role: Agent role to assign.
        timezone: IANA timezone.
        max_runs: Optional max execution count.
        metadata: Optional metadata dict.

    Returns:
        The created TaskSchedule record.
    """
    # Validate cron expression
    if not croniter.is_valid(cron_expression):
        msg = f"Invalid cron expression: {cron_expression}"
        raise ValueError(msg)

    next_run = calculate_next_run(cron_expression, timezone)

    schedule = TaskSchedule(
        workspace_id=workspace_id,
        name=name,
        cron_expression=cron_expression,
        instruction=instruction,
        target_role=target_role,
        is_active=True,
        timezone=timezone,
        next_run_at=next_run,
        max_runs=max_runs,
        metadata_=metadata,
    )
    session.add(schedule)
    await session.flush()

    logger.info(
        "schedule_created",
        schedule_id=str(schedule.id),
        name=name,
        cron_expression=cron_expression,
        next_run_at=next_run.isoformat(),
    )

    return schedule

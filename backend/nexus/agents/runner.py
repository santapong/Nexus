"""Agent runner — starts all active agents as async tasks.

Run standalone with: python -m nexus.agents.runner
Or import start_all_agents() for Litestar startup integration.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from nexus.agents.factory import build_agent
from nexus.agents.health_monitor import run_health_monitor
from nexus.core.kafka.result_consumer import run_result_consumer
from nexus.core.scheduler import run_scheduler_tick
from nexus.db.models import Agent, AgentRole
from nexus.settings import settings

logger = structlog.get_logger()


async def start_all_agents(
    db_session_factory: async_sessionmaker[Any] | None = None,
) -> list[asyncio.Task[None]]:
    """Load agent configs from DB and start all active agents + result consumer.

    Args:
        db_session_factory: Optional session factory. If None, creates a new one.

    Returns:
        List of running asyncio tasks (agents + result consumer + health monitor).
    """
    if db_session_factory is None:
        engine = create_async_engine(settings.database_url)
        db_session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # Load active agents from database
    async with db_session_factory() as session:
        stmt = select(Agent).where(Agent.is_active.is_(True))
        result = await session.execute(stmt)
        agents_db = list(result.scalars().all())

    if not agents_db:
        logger.warning("no_active_agents_found")
        return []

    logger.info("starting_agents", count=len(agents_db))

    tasks: list[asyncio.Task[None]] = []

    # Start each agent
    for agent_db in agents_db:
        try:
            role = AgentRole(agent_db.role)
            agent = build_agent(
                role=role,
                agent_id=str(agent_db.id),
                system_prompt=agent_db.system_prompt,
                db_session_factory=db_session_factory,
            )
            task = asyncio.create_task(agent.run(), name=f"agent-{role.value}")
            tasks.append(task)
            logger.info(
                "agent_task_created",
                role=role.value,
                agent_id=str(agent_db.id),
            )
        except Exception as exc:
            logger.error(
                "agent_build_failed",
                role=agent_db.role,
                error=str(exc),
            )

    # Start the result consumer — closes the task lifecycle loop
    result_task = asyncio.create_task(
        run_result_consumer(db_session_factory),
        name="result-consumer",
    )
    tasks.append(result_task)
    logger.info("result_consumer_task_created")

    # Start the health monitor — auto-fails tasks on agent silence
    health_task = asyncio.create_task(
        run_health_monitor(db_session_factory),
        name="health-monitor",
    )
    tasks.append(health_task)
    logger.info("health_monitor_task_created")

    # Start the scheduler — checks for due scheduled tasks periodically
    scheduler_task = asyncio.create_task(
        _run_scheduler_loop(db_session_factory),
        name="scheduler",
    )
    tasks.append(scheduler_task)
    logger.info("scheduler_task_created")

    logger.info("all_agents_running", count=len(tasks))
    return tasks


async def _run_scheduler_loop(
    db_session_factory: async_sessionmaker[Any],
) -> None:
    """Background loop that checks for due scheduled tasks.

    Runs every `scheduler_check_interval_seconds` (default 60s).
    Creates tasks for schedules whose next_run_at has passed.
    """
    interval = settings.scheduler_check_interval_seconds
    logger.info("scheduler_loop_started", interval_seconds=interval)

    while True:
        try:
            async with db_session_factory() as session:
                created = await run_scheduler_tick(session)
                if created > 0:
                    logger.info("scheduler_tick_tasks_created", count=created)
        except Exception as exc:
            logger.error(
                "scheduler_tick_failed",
                error=str(exc),
                exc_info=True,
            )
        await asyncio.sleep(interval)


async def main() -> None:
    """Standalone entry point for running all agents."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level.upper(), logging.INFO)
        ),
    )

    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    tasks = await start_all_agents(session_factory)

    if not tasks:
        logger.error("no_agents_started")
        await engine.dispose()
        return

    try:
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        logger.info("shutting_down")
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

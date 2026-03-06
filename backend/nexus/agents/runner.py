"""Agent runner — starts all active agents as async tasks.

Run with: python -m nexus.agents.runner
"""
from __future__ import annotations

import asyncio

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from nexus.agents.factory import build_agent
from nexus.db.models import Agent, AgentRole
from nexus.settings import settings

logger = structlog.get_logger()


async def main() -> None:
    """Load agent configs from DB and start all active agents."""
    # Configure structlog
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            structlog.get_level_from_name(settings.log_level)
        ),
    )

    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # Load active agents from database
    async with session_factory() as session:
        stmt = select(Agent).where(Agent.is_active.is_(True))
        result = await session.execute(stmt)
        agents_db = list(result.scalars().all())

    if not agents_db:
        logger.warning("no_active_agents_found")
        await engine.dispose()
        return

    logger.info("starting_agents", count=len(agents_db))

    # Build and start each agent
    tasks: list[asyncio.Task[None]] = []
    for agent_db in agents_db:
        try:
            role = AgentRole(agent_db.role)
            agent = build_agent(
                role=role,
                agent_id=str(agent_db.id),
                system_prompt=agent_db.system_prompt,
                db_session_factory=session_factory,
            )
            task = asyncio.create_task(
                agent.run(), name=f"agent-{role.value}"
            )
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

    if not tasks:
        logger.error("no_agents_started")
        await engine.dispose()
        return

    logger.info("all_agents_running", count=len(tasks))

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

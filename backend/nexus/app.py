from __future__ import annotations

import asyncio
import logging

import structlog
from advanced_alchemy.extensions.litestar import SQLAlchemyPlugin
from litestar import Litestar
from litestar.config.cors import CORSConfig

from nexus.api.router import api_router, health_router
from nexus.db.session import sqlalchemy_config
from nexus.kafka.producer import close_producer
from nexus.settings import settings

logger = structlog.get_logger()

# Background agent tasks — kept alive for the app lifetime
_agent_tasks: list[asyncio.Task[None]] = []


async def _on_startup() -> None:
    """Start all agents and result consumer as background tasks."""
    try:
        from nexus.agents.runner import start_all_agents

        tasks = await start_all_agents()
        _agent_tasks.extend(tasks)
        logger.info("agents_started_on_startup", count=len(tasks))
    except Exception as exc:
        # Log but don't crash the API — agents may start later via runner
        logger.error("agent_startup_failed", error=str(exc), exc_info=True)


async def _on_shutdown() -> None:
    """Gracefully stop agents and Kafka producer on app shutdown."""
    for task in _agent_tasks:
        task.cancel()
    if _agent_tasks:
        await asyncio.gather(*_agent_tasks, return_exceptions=True)
    await close_producer()
    logger.info("app_shutdown_complete")


def create_app() -> Litestar:
    """Litestar application factory."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.ConsoleRenderer()
            if settings.is_development
            else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level.upper(), logging.INFO)
        ),
    )

    cors_config = CORSConfig(
        allow_origins=["http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app = Litestar(
        route_handlers=[api_router, health_router],
        plugins=[SQLAlchemyPlugin(config=sqlalchemy_config)],
        cors_config=cors_config,
        on_startup=[_on_startup],
        on_shutdown=[_on_shutdown],
        debug=settings.is_development,
    )

    return app


app = create_app()

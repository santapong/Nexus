from __future__ import annotations

import structlog
from advanced_alchemy.extensions.litestar import SQLAlchemyPlugin
from litestar import Litestar
from litestar.config.cors import CORSConfig

from nexus.api.router import api_router, health_router
from nexus.db.session import sqlalchemy_config
from nexus.kafka.producer import close_producer
from nexus.settings import settings


async def _on_shutdown() -> None:
    """Gracefully close Kafka producer on app shutdown."""
    await close_producer()


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
            structlog.get_level_from_name(settings.log_level)
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
        on_shutdown=[_on_shutdown],
        debug=settings.is_development,
    )

    return app


app = create_app()

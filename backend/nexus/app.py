from __future__ import annotations

import asyncio
import logging

import structlog
from advanced_alchemy.extensions.litestar import SQLAlchemyPlugin
from litestar import Litestar
from litestar.config.cors import CORSConfig

from nexus.api.middleware import RLSMiddleware
from nexus.api.router import a2a_router, api_router, health_router, stripe_router
from nexus.core.kafka.producer import close_producer
from nexus.db.session import sqlalchemy_config
from nexus.settings import settings

logger = structlog.get_logger()

# Background agent tasks — kept alive for the app lifetime
_agent_tasks: list[asyncio.Task[None]] = []


async def _security_checks() -> None:
    """Verify critical security settings on startup.

    Blocks startup in production if dangerous defaults are detected.
    """
    if not settings.is_development:
        if settings.jwt_secret_key == "nexus-dev-secret-change-in-production":
            raise RuntimeError(
                "FATAL: JWT_SECRET_KEY must be changed from default for production. "
                "Set a strong random secret via environment variable."
            )
        if not settings.anthropic_api_key and not settings.google_api_key:
            logger.warning(
                "no_llm_api_keys_configured",
                hint="Set ANTHROPIC_API_KEY or GOOGLE_API_KEY for LLM functionality",
            )
        if settings.stripe_api_key and not settings.stripe_webhook_secret:
            logger.warning(
                "stripe_webhook_secret_missing",
                hint="Set STRIPE_WEBHOOK_SECRET for secure webhook verification",
            )
    logger.info(
        "security_checks_passed",
        env=settings.app_env,
        jwt_default=settings.jwt_secret_key == "nexus-dev-secret-change-in-production",
        oauth_google=bool(settings.oauth_google_client_id),
        oauth_github=bool(settings.oauth_github_client_id),
        stripe=bool(settings.stripe_api_key),
        injection_classifier=settings.injection_classifier_enabled,
    )


async def _on_startup() -> None:
    """Run security checks and start all agents."""
    await _security_checks()

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

    # CORS: environment-driven origins
    cors_origins = (
        ["http://localhost:5173"]
        if settings.is_development
        else settings.cors_allowed_origins.split(",")
    )

    cors_config = CORSConfig(
        allow_origins=cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app = Litestar(
        route_handlers=[api_router, health_router, a2a_router, stripe_router],
        plugins=[SQLAlchemyPlugin(config=sqlalchemy_config)],
        cors_config=cors_config,
        middleware=[RLSMiddleware],
        on_startup=[_on_startup],
        on_shutdown=[_on_shutdown],
        debug=settings.is_development,
        request_max_body_size=1_048_576,  # 1MB — prevent oversized payloads
    )

    return app


app = create_app()

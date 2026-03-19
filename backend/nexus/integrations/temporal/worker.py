"""Temporal worker — connects to Temporal server and processes workflows.

Run standalone with: python -m nexus.workflows.worker
"""

from __future__ import annotations

import asyncio
import logging

import structlog

from nexus.settings import settings

logger = structlog.get_logger()


async def start_temporal_worker() -> None:
    """Start the Temporal worker that processes task workflows.

    Connects to the Temporal server and registers workflows and activities.
    The worker runs until interrupted.
    """
    try:
        from temporalio.client import Client
        from temporalio.worker import Worker

        from nexus.integrations.temporal.activities import (
            execute_subtask_activity,
            execute_task_activity,
        )
        from nexus.integrations.temporal.task_workflow import task_execution_workflow

        client = await Client.connect(settings.temporal_host)

        logger.info(
            "temporal_worker_connecting",
            host=settings.temporal_host,
            namespace=settings.temporal_namespace,
            task_queue=settings.temporal_task_queue,
        )

        worker = Worker(
            client,
            task_queue=settings.temporal_task_queue,
            workflows=[task_execution_workflow],  # type: ignore[list-item]
            activities=[execute_task_activity, execute_subtask_activity],
        )

        logger.info("temporal_worker_started")
        await worker.run()

    except ImportError:
        logger.warning(
            "temporal_not_installed",
            message="temporalio package not installed. Temporal workflows disabled. "
            "Install with: pip install temporalio",
        )
    except Exception as exc:
        logger.error(
            "temporal_worker_failed",
            error=str(exc),
            host=settings.temporal_host,
        )


async def main() -> None:
    """Standalone entry point for the Temporal worker."""
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

    await start_temporal_worker()


if __name__ == "__main__":
    asyncio.run(main())

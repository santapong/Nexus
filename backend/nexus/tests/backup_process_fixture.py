"""Actual task-owned worker handles target only the assigned source/restore database pair."""

import asyncio
import os
import sys
from pathlib import Path
from uuid import UUID

from nexus.tests.backup_postgres_fixture import local_url


async def spawn_backup_worker(
    root: Path,
    blobs: Path,
    database: str,
    workflow_id: str,
    worker_id: UUID,
    *,
    barrier: str | None = None,
) -> asyncio.subprocess.Process:
    args = [
        sys.executable,
        "-m",
        "nexus.tests.integration.backup_native_process",
        "--root",
        str(root),
        "--blob-root",
        str(blobs),
        "--workflow-id",
        workflow_id,
        "--worker-id",
        str(worker_id),
    ]
    if barrier:
        args.extend(("--barrier", barrier))
    return await asyncio.create_subprocess_exec(
        *args,
        cwd=Path(__file__).resolve().parents[2],
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={
            "PATH": os.defpath,
            "COMPANY_DATABASE_URL": local_url(database, "nexus_company_app").render_as_string(
                hide_password=False
            ),
        },
    )

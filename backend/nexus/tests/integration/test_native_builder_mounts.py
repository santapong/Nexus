"""Actual runtime mount facts qualify the complete writable workspace envelope."""

import base64
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.tests.builder_runtime_support import builder_factory as builder_factory
from nexus.tests.builder_runtime_support import scenario
from nexus.tests.integration.test_company_directory import ACTOR
from nexus.tests.integration.test_company_execution_store import identity


async def test_actual_writable_tmpfs_total_fits_job_envelope(
    builder_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    item = await scenario(
        builder_factory,
        tmp_path,
        argv=(
            "/bin/sh",
            "-c",
            'mkdir -p "$NEXUS_OUTPUT_DIR/checks"; '
            "test ! -s /etc/resolv.conf && "
            'cat /proc/mounts >"$NEXUS_OUTPUT_DIR/checks/mounts.txt"',
        ),
    )
    result = await item.runner.run(item.lease, identity(ACTOR), item.action, item.spec, item.guard)
    assert result is not None and result.outcome == "commands_succeeded"
    raw = base64.b64decode(result.artifacts[0].content_base64).decode()
    rows = []
    total = 0
    for line in raw.splitlines():
        fields = line.split()
        options = fields[3].split(",")
        if fields[2] == "tmpfs" and "rw" in options:
            sizes = [value[5:] for value in options if value.startswith("size=")]
            assert len(sizes) == 1, (fields[1], options)
            size = sizes[0]
            multiplier = 1024 if size.endswith("k") else 1
            amount = int(size.removesuffix("k")) * multiplier
            total += amount
            rows.append((fields[1], amount))
    (tmp_path / "actual-writable-mounts.txt").write_text(raw)
    assert total <= item.spec.job.limits.workspace_bytes, (
        total,
        item.spec.job.limits.workspace_bytes,
        rows,
    )

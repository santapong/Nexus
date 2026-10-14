"""Generated process inputs; no native action, scope or SDK execution evidence."""

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid5

from nexus.builder.contained_process_contracts import PreparedContainedLaunch, ProcessRunBinding
from nexus.builder.contained_spawn_window import SpawnWindow, capture_spawn_window
from nexus.tests.contained_observer_fixture import BOOT as BOOT
from nexus.tests.contained_observer_fixture import parent as parent


def binding() -> ProcessRunBinding:
    """Original issued fence is generated only for pure tests."""
    return ProcessRunBinding(
        company_id=BOOT,
        action_id=BOOT,
        task_id=BOOT,
        trace_id=BOOT,
        run_id=BOOT,
        original_intent_fence=1,
        image_id="a" * 64,
        spec_sha256="b" * 64,
        proposal_sha256="c" * 64,
        execution_method_sha256="d" * 64,
        container_name="nexus-builder-" + uuid5(BOOT, str(BOOT)).hex,
    )


def launch() -> PreparedContainedLaunch:
    """Root compiler will produce actual argv; this descriptor alone is not authority."""
    value = binding()
    argv = (
        "/usr/bin/podman",
        "--remote=false",
        "--cgroup-manager=cgroupfs",
        "run",
        "--cgroups=split",
        "--name",
        value.container_name,
        "--label",
        f"nexus.builder.company={BOOT}",
        "--label",
        f"nexus.builder.action={BOOT}",
        "--pull=never",
        "--network=none",
        "--read-only",
        value.image_id,
        "/fixture",
    )
    return PreparedContainedLaunch(
        binding=value,
        argv=argv,
        argv_sha256=hashlib.sha256(json.dumps(argv, separators=(",", ":")).encode()).hexdigest(),
        memory_bytes=4294967296,
        cpu_quota_us=200000,
        cpu_period_us=100000,
        pids=256,
    )


def window() -> SpawnWindow:
    """Root committed1s offset/continuity model is reused exactly."""
    now = datetime(2026, 10, 15, tzinfo=UTC)
    return capture_spawn_window(
        database_now=now,
        monotonic_before_query_us=12_000_000,
        utc_after_query=now,
        deadlines=(now + timedelta(seconds=1),),
        operation_end_us=13_000_000,
    )


class Process:
    """Fake owned OS child with real asyncio pipes; no actual process launched."""

    def __init__(self, *, stopped: bool = True) -> None:
        self.pid = 777
        self.returncode = 0 if stopped else None
        self.stdout = asyncio.StreamReader()
        self.stdout.feed_data(b"short original output")
        self.stdout.feed_eof()
        self.stderr = asyncio.StreamReader()
        self.stderr.feed_eof()
        self.done = asyncio.Event()
        self.killed = False
        self.wait_count = 0
        if stopped:
            self.done.set()

    async def wait(self) -> int:
        self.wait_count += 1
        await self.done.wait()
        assert self.returncode is not None
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9
        self.done.set()

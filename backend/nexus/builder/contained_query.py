"""One fixed read-only busctl subprocess, bounded and reaped under an absolute IO deadline."""

from __future__ import annotations

import asyncio
import re
from time import monotonic_ns

from nexus.builder.contained_contracts import ObservationBounds
from nexus.builder.process import engine_environment, limited_stream

PREFIX = (
    "/usr/bin/busctl",
    "--user",
    "--json=short",
    "--auto-start=no",
    "--allow-interactive-authorization=no",
    "--timeout=3s",
)
SERVICE = "org.freedesktop.systemd1"
UNIT_PROPERTIES = (
    "Id",
    "LoadState",
    "ActiveState",
    "InvocationID",
    "ActiveEnterTimestampMonotonic",
)
SCOPE_PROPERTIES = (
    "ControlGroup",
    "RuntimeMaxUSec",
    "RuntimeRandomizedExtraUSec",
    "Delegate",
    "MemoryMax",
    "CPUQuotaPerSecUSec",
    "CPUQuotaPeriodUSec",
    "TasksMax",
    "KillMode",
    "SendSIGKILL",
    "TimeoutStopUSec",
)


def clock_us() -> int:
    """Systemd scope timing and local monotonic samples use the same boot clock."""
    return monotonic_ns() // 1000


class BusctlReader:
    """Internal fixed query transport; it never starts scopes or invokes sandbox code."""

    async def query(self, argv: tuple[str, ...], deadline_us: int) -> bytes:
        """Bound spawn, capture and reaping to the shared absolute deadline."""
        _require_argv(argv)
        process: asyncio.subprocess.Process | None = None
        tasks: list[asyncio.Task[bytes] | asyncio.Task[int]] = []
        bounds = ObservationBounds()
        try:
            async with asyncio.timeout(_remaining(deadline_us - 100_000)):
                process = await asyncio.create_subprocess_exec(
                    *argv,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=engine_environment(),
                )
                assert process.stdout is not None and process.stderr is not None
                out = asyncio.create_task(limited_stream(process.stdout, bounds.stdout_bytes))
                err = asyncio.create_task(limited_stream(process.stderr, bounds.stderr_bytes))
                wait = asyncio.create_task(process.wait())
                tasks = [out, err, wait]
                result = await asyncio.gather(*tasks)
                if process.returncode != 0:
                    raise ValueError("Read-only systemd query is unavailable")
                assert isinstance(result[0], bytes)
                return result[0]
        finally:
            await _reap(process, tasks, deadline_us)


def _remaining(deadline_us: int) -> float:
    remaining = (deadline_us - clock_us()) / 1_000_000
    if remaining <= 0:
        raise TimeoutError("Scope query total IO deadline reached")
    return remaining


async def _reap(
    process: asyncio.subprocess.Process | None,
    tasks: list[asyncio.Task[bytes] | asyncio.Task[int]],
    deadline_us: int,
) -> None:
    if process is None:
        return
    if process.returncode is None:
        process.kill()
    for task in tasks:
        if not task.done():
            task.cancel()
    # Query IO reserves100ms for exact child reaping within the original total deadline.
    async with asyncio.timeout(_remaining(deadline_us)):
        await asyncio.gather(*tasks, return_exceptions=True)
        await process.wait()


def _require_argv(argv: tuple[str, ...]) -> None:
    if argv[:6] != PREFIX:
        raise ValueError("Scope query program/options differ")
    tail = argv[6:]
    call = ("call", SERVICE, "/org/freedesktop/systemd1", SERVICE + ".Manager", "GetUnit", "s")
    if (
        tail[:6] == call
        and len(tail) == 7
        and re.fullmatch(r"nexus-[a-z0-9-]{1,90}\.scope", tail[6])
    ):
        return
    if (
        len(tail) >= 5
        and tail[:2] == ("get-property", SERVICE)
        and re.fullmatch(r"/org/freedesktop/systemd1/unit/[a-zA-Z0-9_]+", tail[2])
        and (
            (tail[3:] == (SERVICE + ".Unit", *UNIT_PROPERTIES))
            or (tail[3:] == (SERVICE + ".Scope", *SCOPE_PROPERTIES))
        )
    ):
        return
    raise ValueError("Scope query is outside the exact read-only method/property ABI")

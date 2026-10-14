"""Fixed cgroupfs inspection child; bounded capture and reaping share an absolute deadline."""

from __future__ import annotations

import asyncio
import re

from nexus.builder.contained_query import clock_us
from nexus.builder.process import engine_environment, limited_stream

INSPECT_PREFIX = (
    "/usr/bin/podman",
    "--remote=false",
    "--cgroup-manager=cgroupfs",
    "inspect",
    "--format",
)
INSPECT_FORMAT = (
    '{"container_id":{{json .ID}},"image_id":{{json .Image}},'
    '"company_id":{{json (index .Config.Labels "nexus.builder.company")}},'
    '"action_id":{{json (index .Config.Labels "nexus.builder.action")}},'
    '"running":{{json .State.Running}},"payload_pid":{{json .State.Pid}},'
    '"conmon_pid":{{json .State.ConmonPid}}}'
)


class ContainedEngineReader:
    """Trusted inspection implementation; it never launches, kills or removes a container."""

    async def query(self, argv: tuple[str, ...], deadline_us: int, limit: int) -> bytes:
        """Reject arbitrary commands before spawn and retain uncertain reaping as failure."""
        _require_inspection(argv, deadline_us, limit)
        process: asyncio.subprocess.Process | None = None
        tasks: list[asyncio.Task[bytes] | asyncio.Task[int]] = []
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
                out = asyncio.create_task(limited_stream(process.stdout, limit))
                err = asyncio.create_task(limited_stream(process.stderr, 4_096))
                wait = asyncio.create_task(process.wait())
                tasks = [out, err, wait]
                result = await asyncio.gather(*tasks)
                if process.returncode != 0:
                    raise ValueError("Contained engine inspection is unavailable")
                assert isinstance(result[0], bytes)
                return result[0]
        finally:
            await _reap(process, tasks, deadline_us)


def _require_inspection(argv: tuple[str, ...], deadline_us: int, limit: int) -> None:
    if (
        len(argv) != 7
        or argv[:5] != INSPECT_PREFIX
        or argv[5] != INSPECT_FORMAT
        or re.fullmatch(r"[0-9a-f]{64}", argv[6]) is None
        or type(limit) is not int
        or limit != 65_536
        or type(deadline_us) is not int
        or deadline_us <= 0
    ):
        raise ValueError("Contained engine query is outside the fixed inspection ABI")
    _remaining(deadline_us - 100_000)


def _remaining(deadline_us: int) -> float:
    remaining = (deadline_us - clock_us()) / 1_000_000
    if remaining <= 0:
        raise TimeoutError("Contained engine shared deadline expired")
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
    async with asyncio.timeout(_remaining(deadline_us)):
        await asyncio.gather(*tasks, return_exceptions=True)
        await process.wait()

"""Bound one owned Podman process and container; failure never falls back to host execution."""

from __future__ import annotations

import asyncio
import os
import pwd
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import monotonic


def engine_environment() -> dict[str, str]:
    account = pwd.getpwuid(os.geteuid())
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": account.pw_dir,
        "XDG_RUNTIME_DIR": f"/run/user/{os.geteuid()}",
        "LANG": "C",
    }


@dataclass(frozen=True)
class ProcessCapture:
    stdout: bytes
    stderr: bytes
    exit_code: int
    elapsed_millis: int
    interruption: str | None


async def limited_stream(stream: asyncio.StreamReader, limit: int) -> bytes:
    body = bytearray()
    while part := await stream.read(min(65536, limit - len(body) + 1)):
        body.extend(part)
        if len(body) > limit:
            raise ValueError("Builder process output limit reached")
    return bytes(body)


async def owned_engine(argv: tuple[str, ...], limit: int = 16384) -> bytes:
    process = await asyncio.create_subprocess_exec(
        "/usr/bin/podman",
        "--remote=false",
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env=engine_environment(),
    )
    assert process.stdout is not None
    try:
        async with asyncio.timeout(5):
            raw = await limited_stream(process.stdout, limit)
            if await process.wait() != 0:
                raise ValueError("Owned builder container operation is unavailable")
            return raw
    finally:
        if process.returncode is None:
            process.kill()
        await asyncio.wait_for(process.communicate(), timeout=2)


async def kill_owned(name: str, action_id: str, company_id: str) -> None:
    if not re.fullmatch(r"nexus-builder-[0-9a-f]{32}", name):
        raise ValueError("Builder owned container name is unavailable")
    raw = await owned_engine(
        (
            "inspect",
            "--format",
            '{{index .Config.Labels "nexus.builder.action"}} '
            '{{index .Config.Labels "nexus.builder.company"}}',
            name,
        )
    )
    if raw.decode().strip() != f"{action_id} {company_id}":
        raise ValueError("Builder container identity differs")
    await owned_engine(("kill", "--signal=KILL", name))


async def remove_known_owned(name: str, action_id: str, company_id: str) -> None:
    if not re.fullmatch(r"nexus-builder-[0-9a-f]{32}", name):
        raise ValueError("Builder owned container name is unavailable")
    raw = await owned_engine(
        (
            "inspect",
            "--format",
            '{{index .Config.Labels "nexus.builder.action"}} '
            '{{index .Config.Labels "nexus.builder.company"}} {{.State.Running}}',
            name,
        )
    )
    if raw.decode().strip() != f"{action_id} {company_id} false":
        raise ValueError("Builder cleanup needs its exact stopped owned container")
    await owned_engine(("rm", name))


async def _finish_capture(
    process: asyncio.subprocess.Process,
    out: asyncio.Task[bytes],
    err: asyncio.Task[bytes],
    wait: asyncio.Task[int],
) -> tuple[bytes, bytes]:
    try:
        async with asyncio.timeout(2):
            values = await asyncio.gather(out, err, wait, return_exceptions=True)
    except TimeoutError:
        if process.returncode is None:
            process.kill()
        for task in (out, err, wait):
            if not task.done():
                task.cancel()
        values = await asyncio.gather(out, err, wait, return_exceptions=True)
    return (
        values[0] if isinstance(values[0], bytes) else b"",
        values[1] if isinstance(values[1], bytes) else b"",
    )


async def _watch(
    wait: asyncio.Task[int],
    out: asyncio.Task[bytes],
    err: asyncio.Task[bytes],
    started: float,
    seconds: int,
    watchdog: Callable[[], Awaitable[None]],
) -> None:
    while not wait.done():
        if monotonic() - started > seconds:
            raise TimeoutError("Builder wall time reached")
        if (out.done() and out.exception()) or (err.done() and err.exception()):
            raise ValueError("Builder output limit reached")
        await watchdog()
        await asyncio.wait((wait,), timeout=0.2)


async def bounded_call(
    argv: tuple[str, ...],
    *,
    name: str,
    action_id: str,
    company_id: str,
    seconds: int,
    stdout_limit: int,
    stderr_limit: int,
    watchdog: Callable[[], Awaitable[None]],
) -> ProcessCapture:
    started = monotonic()
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        stdin=asyncio.subprocess.DEVNULL,
        env=engine_environment(),
        start_new_session=True,
    )
    assert process.stdout is not None and process.stderr is not None
    out = asyncio.create_task(limited_stream(process.stdout, stdout_limit))
    err = asyncio.create_task(limited_stream(process.stderr, stderr_limit))
    wait = asyncio.create_task(process.wait())
    interruption = None
    try:
        async with asyncio.timeout(seconds):
            await _watch(wait, out, err, started, seconds, watchdog)
    except (Exception, asyncio.CancelledError) as exc:
        interruption = type(exc).__name__
        try:
            await kill_owned(name, action_id, company_id)
        except (ValueError, TimeoutError):
            interruption = "owned_container_unconfirmed"
        if process.returncode is None:
            process.kill()
    finally:
        stdout, stderr = await _finish_capture(process, out, err, wait)
    return ProcessCapture(
        stdout,
        stderr,
        process.returncode if process.returncode is not None else -1,
        int((monotonic() - started) * 1000),
        interruption,
    )

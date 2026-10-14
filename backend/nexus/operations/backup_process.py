"""One tracked bounded child process; output is private and failures never reflect argv/stderr."""

import asyncio
import os
import signal
from contextlib import suppress


class BackupProcessError(ValueError):
    """Safe fixed subprocess outcome; no private command, archive or environment reflection."""


async def bounded_read(stream: asyncio.StreamReader | None, limit: int) -> bytes:
    if stream is None:
        raise BackupProcessError("Backup process stream is unavailable")
    chunks = bytearray()
    while raw := await stream.read(65536):
        chunks.extend(raw)
        if len(chunks) > limit:
            raise BackupProcessError("Backup process output exceeds its bound")
    return bytes(chunks)


async def feed_input(process: asyncio.subprocess.Process, raw: bytes | None) -> None:
    if raw is None:
        return
    assert process.stdin is not None
    for offset in range(0, len(raw), 65536):
        process.stdin.write(raw[offset : offset + 65536])
        await process.stdin.drain()
    process.stdin.close()
    await process.stdin.wait_closed()


async def terminate_owned(process: asyncio.subprocess.Process) -> None:
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    if process.returncode is None:
        try:
            await asyncio.wait_for(process.wait(), timeout=1)
        except TimeoutError:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            await process.wait()
    # A dead leader does not prove its registered group has no live descendants.
    # The group ID is the child session's pinned PID, never a caller-supplied PID.
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)


async def run_bounded(
    command: tuple[str, ...],
    *,
    input_bytes: bytes | None = None,
    output_limit: int,
    timeout_seconds: int,
) -> bytes:
    require_bounds(input_bytes, output_limit, timeout_seconds)
    env = {
        "PATH": os.defpath,
        "LC_ALL": "C",
        "PGPASSFILE": "/dev/null",
        "PGSERVICEFILE": "/dev/null",
        "PGCONNECT_TIMEOUT": "5",
    }
    process = await start_process(command, input_bytes is not None, env)
    tasks = (
        asyncio.create_task(bounded_read(process.stdout, output_limit)),
        asyncio.create_task(bounded_read(process.stderr, 65536)),
        asyncio.create_task(feed_input(process, input_bytes)),
        asyncio.create_task(process.wait()),
    )
    try:
        async with asyncio.timeout(timeout_seconds):
            result, _, _, code = await asyncio.gather(*tasks)
        if code != 0:
            raise BackupProcessError("Backup process failed")
        return result
    except (OSError, TimeoutError):
        raise BackupProcessError("Backup process is unavailable") from None
    finally:
        await terminate_owned(process)
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def require_bounds(raw: bytes | None, output_limit: int, timeout_seconds: int) -> None:
    if (
        type(output_limit) is not int
        or not 1 <= output_limit <= 268_435_456
        or type(timeout_seconds) is not int
        or not 1 <= timeout_seconds <= 180
        or (raw is not None and (type(raw) is not bytes or len(raw) > 268_435_456))
    ):
        raise BackupProcessError("Backup process bounds are unavailable")


async def start_process(
    command: tuple[str, ...], has_input: bool, env: dict[str, str]
) -> asyncio.subprocess.Process:
    try:
        return await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE if has_input else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            start_new_session=True,
        )
    except OSError:
        raise BackupProcessError("Backup process is unavailable") from None

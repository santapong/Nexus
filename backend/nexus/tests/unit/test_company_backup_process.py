"""Synthetic process output/timeout boundaries, no database or backup keys."""

import asyncio
import os
import signal
import sys
from contextlib import suppress
from pathlib import Path

import pytest

from nexus.operations.backup_process import BackupProcessError, run_bounded


async def test_private_process_failure_does_not_reflect_stderr_or_command() -> None:
    with pytest.raises(BackupProcessError) as error:
        await run_bounded(
            (sys.executable, "-c", "import sys;sys.stderr.write('synthetic-private');sys.exit(1)"),
            output_limit=100,
            timeout_seconds=5,
        )
    assert str(error.value) == "Backup process failed"


async def test_stdout_expansion_is_bounded_and_child_terminated() -> None:
    with pytest.raises(BackupProcessError, match="output exceeds"):
        await run_bounded(
            (
                sys.executable,
                "-c",
                "import sys,time;sys.stdout.write('x'*1000);sys.stdout.flush();time.sleep(5)",
            ),
            output_limit=10,
            timeout_seconds=5,
        )


async def test_timeout_is_safe_and_finite() -> None:
    with pytest.raises(BackupProcessError, match="unavailable"):
        await run_bounded(
            (sys.executable, "-c", "import time;time.sleep(5)"),
            output_limit=10,
            timeout_seconds=1,
        )


async def test_exact_binary_input_roundtrip_with_ambient_credentials_suppressed() -> None:
    result = await run_bounded(
        (
            sys.executable,
            "-c",
            "import os,sys;assert os.environ['PGPASSFILE']=='/dev/null';"
            "sys.stdout.buffer.write(sys.stdin.buffer.read())",
        ),
        input_bytes=b"synthetic bytes",
        output_limit=100,
        timeout_seconds=5,
    )
    assert result == b"synthetic bytes"


async def test_exited_leader_cannot_leave_live_owned_process_group(tmp_path: Path) -> None:
    """A child holding no streams must still terminate when its parent exits first."""
    marker = tmp_path / "owned-child-pid"
    code = (
        "import subprocess,sys;from pathlib import Path;"
        "child=subprocess.Popen([sys.executable,'-c',"
        "'import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)'],"
        "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);"
        "Path(sys.argv[1]).write_text(str(child.pid));import time;time.sleep(0.2);"
        "sys.stdout.write('done')"
    )
    pid = None
    try:
        assert (
            await run_bounded(
                (sys.executable, "-c", code, str(marker)), output_limit=10, timeout_seconds=5
            )
            == b"done"
        )
        pid = int(marker.read_text())
        for _ in range(100):
            state = Path(f"/proc/{pid}/stat")
            if not state.exists() or state.read_text().split()[2] == "Z":
                break
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("Owned descendant remains live after exited process leader")
    finally:
        if pid is not None:
            with suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)

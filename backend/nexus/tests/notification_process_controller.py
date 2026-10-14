"""TEST-only finite owned-PID crash/restart controller; no external effect or record rewriting."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import stat
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import SecretStr, TypeAdapter
from sqlalchemy.engine import make_url

from nexus.company.management.canonical import canonical_sha256
from nexus.company.notifications.worker_identity import (
    NotificationWorkerIdentities,
)
from nexus.execution.notification_worker_contracts import NotificationSegmentResult
from nexus.settings import settings
from nexus.tests.integration.notification_process import FixedPipeCredential
from nexus.tests.notification_process_config import (
    PROCESS_ROOTS,
    NotificationProcessConfig,
    NotificationProcessDatabase,
    require_notification_process_root,
)
from nexus.tests.notification_process_prepare import prepare_notification_process_case
from nexus.tests.notification_process_services import native_state, process_app_backends
from nexus.tests.notification_worker_credential_fixture import TEST_KEY

_PYTHON = Path("/home/santapong/.codex/nexus-local-runtime-20261014/bin/python")
_SOURCE = Path(
    "/home/santapong/.codex/nexus-local-release-fixtures-20261014-continued/notification-os-source-20261015-2/backend"
)
_OWNED: list[tuple[subprocess.Popen[bytes], str | None]] = []
_TASK_ROOT: Path | None = None


def process_start(pid: int) -> str:
    raw = Path(f"/proc/{pid}/stat").read_text()
    return raw[raw.rfind(")") + 2 :].split()[19]


def start_worker(
    config: NotificationProcessConfig, token: SecretStr, worker_id: str, *, barrier: bool
) -> tuple[subprocess.Popen[bytes], str]:
    """One inherited pipe/token; no credential argv/environment/log or unmanaged process group."""
    # Cohesive spawn boundary: exact source/root/UUID and pipe lifetime must
    # remain together so failure cannot start an unrecorded or foreign worker.
    if (
        Path(sys.executable).resolve() != _PYTHON.resolve()
        or Path(__file__).resolve().parents[2] != _SOURCE
    ):
        raise ValueError("Notification controller source/runtime differs")
    require_notification_process_root(config.database, config.root, existing=True)
    if str(UUID(worker_id)) != worker_id:
        raise ValueError("Notification worker UUID differs")
    if len(_OWNED) >= 2:
        raise ValueError("Notification controller cannot create a third worker")
    url = make_url(settings.company_test_database_url).set(username="nexus_company_app")
    env = {
        "PATH": f"{_PYTHON.parent}:/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "COMPANY_DATABASE_URL": url.render_as_string(hide_password=False),
    }
    output = (config.root / f"worker-{worker_id}.log").open("wb")
    read_fd = write_fd = -1
    try:
        os.chmod(output.fileno(), 0o600)
        read_fd, write_fd = os.pipe()
        arguments = [
            str(_PYTHON),
            "-m",
            "nexus.tests.integration.notification_process",
            "--root",
            str(config.root),
            "--worker-id",
            worker_id,
            "--workflow-id",
            config.command.workflow_id,
            "--credential-fd",
            str(read_fd),
        ]
        if barrier:
            arguments.extend(["--barrier", config.barrier])
        child = subprocess.Popen(
            arguments,
            cwd=_SOURCE,
            env=env,
            pass_fds=(read_fd,),
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        _OWNED.append((child, None))
        start = process_start(child.pid)
        _OWNED[-1] = (child, start)
        os.close(read_fd)
        read_fd = -1
        raw = token.get_secret_value().encode("ascii")
        if not 1 <= len(raw) <= 4096 or os.write(write_fd, raw) != len(raw):
            raise ValueError("Notification controller credential envelope differs")
        return child, start
    finally:
        if read_fd >= 0:
            os.close(read_fd)
        if write_fd >= 0:
            os.close(write_fd)
        output.close()


def records(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    info = path.stat(follow_symlinks=False)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o600
    ):
        raise ValueError("Notification marker ownership differs")
    if info.st_size > 1048576:
        raise ValueError("Notification marker exceeds controller bound")
    values = [json.loads(line) for line in path.read_text().splitlines()]
    if not all(isinstance(x, dict) for x in values):
        raise ValueError("Notification marker type differs")
    return values


async def run_case() -> None:
    """One freshly prepared case, exact owned kill/wait and immediate same-command SDK restart."""
    # Cohesive finite scenario: no controller wait for lease expiry, no third
    # worker/retry; preserve every DB/tree on a mismatch and record owned identities.
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    args = parser.parse_args()
    database: NotificationProcessDatabase = TypeAdapter(
        NotificationProcessDatabase
    ).validate_python(args.database, strict=True)
    root = PROCESS_ROOTS[database]
    global _TASK_ROOT
    _TASK_ROOT = root
    config, token = await prepare_notification_process_case(database, root)
    identity = NotificationWorkerIdentities(
        FixedPipeCredential(token), SecretStr(TEST_KEY), enabled=True
    )
    witness = await identity.current(expected_binding=config.registration.value.registration.sender)
    original_id, restarted_id = str(uuid4()), str(uuid4())
    first, start = start_worker(config, token, original_id, barrier=True)
    history: dict[str, object] = {
        "original_pid": first.pid,
        "original_start": start,
        "original_worker": original_id,
        "restart_worker": restarted_id,
        "command": config.command.model_dump(mode="json"),
        "command_sha256": canonical_sha256(config.command),
    }
    limit = time.monotonic() + 60
    while True:
        matching = [
            r
            for r in records(root / "barrier-events.jsonl")
            if r.get("pid") == first.pid and r.get("event") == config.barrier
        ]
        if matching:
            break
        if first.poll() is not None or time.monotonic() >= limit:
            raise ValueError("Original notification worker did not reach its exact barrier")
        await asyncio.sleep(0.1)
    before = await native_state(config, witness)
    assert (
        before["lease_until"] is not None
        and process_start(first.pid) == start
        and first.poll() is None
    )
    assert isinstance(before["lease_until"], str) and isinstance(before["db_now"], str)
    assert datetime.fromisoformat(before["lease_until"]) > datetime.fromisoformat(before["db_now"])
    assert before["worker_id"] == original_id
    assert before["sdk_status"] == "PENDING"
    history["before_kill"] = before
    os.kill(first.pid, signal.SIGKILL)
    history["original_exit"] = await asyncio.to_thread(first.wait, timeout=10)
    assert history["original_exit"] == -signal.SIGKILL
    assert await process_app_backends(config.database) == 0
    second, second_start = start_worker(config, token, restarted_id, barrier=False)
    history.update({"restart_pid": second.pid, "restart_start": second_start})
    (root / "controller-identities.json").write_text(json.dumps(history, indent=2) + "\n")
    (root / "controller-identities.json").chmod(0o600)
    exit_code = await asyncio.to_thread(second.wait, timeout=120)
    assert exit_code == 0
    observed = records(root / "acquisition-observations.jsonl")
    live = [
        r
        for r in observed
        if r.get("pid") == second.pid
        and r.get("event") == "live_prior_observed"
        and r.get("still_live") is True
    ]
    waited = [
        r for r in observed if r.get("pid") == second.pid and r.get("event") == "acquisition_wait"
    ]
    assert (
        live
        and waited
        and all(r.get("command") == config.command.model_dump(mode="json") for r in live)
    )
    assert all(
        r.get("new_worker_id") == restarted_id
        and r.get("prior_worker_id") == original_id
        and r.get("prior_fence") == 1
        for r in live
    )
    result = NotificationSegmentResult.model_validate_json(
        (root / f"worker-result-{restarted_id}.json").read_text()
    )
    after = await native_state(config, witness)
    assert after["sdk_status"] == "SUCCESS"
    assert (
        after["source_heads"] == before["source_heads"]
        and after["approval_sha256"] == before["approval_sha256"]
    )
    assert after["intent_fence"] == before["intent_fence"] == 1 and after["attempts"] == 1
    assert (
        after["model"] == 0
        and after["tool"] == 1
        and after["hold"] == ["0.010000", None, "unknown"]
    )
    assert (
        after["worker_id"] is None
        and after["lease_until"] is None
        and after["slot_sha256"] == before["slot_sha256"]
    )
    calls = records(root / "http-transcript.jsonl")
    assert len(calls) == (0 if config.barrier == "intent" else 1)
    assert all(r.get("pid") == first.pid for r in calls)
    if config.barrier in ("intent", "response"):
        assert (
            result.status == "outcome_unknown"
            and result.receipt_id is None
            and result.observation_id is None
        )
        assert after["receipt_json"] is None and after["observation_hashes"] == []
    else:
        assert result.status == "submitted" and after["receipt_json"] == before["receipt_json"]
        assert after["observation_hashes"] == before["observation_hashes"]
        if config.barrier == "receipt":
            assert (
                result.observation_id is None
                and "submission_observation_missing" in result.limitations
            )
    shutdown = json.loads((root / f"worker-shutdown-{restarted_id}.json").read_text())
    assert shutdown["http_calls"] == [] and shutdown["blob_reads"] == 0
    assert shutdown["draft_getter_reads"] == 0 and shutdown["body_sql_attempts"] == 0
    history.update(
        {
            "restart_exit": exit_code,
            "after": after,
            "live_helper": live,
            "waits": waited,
            "result": result.model_dump(mode="json"),
            "shutdown": shutdown,
            "http_calls": calls,
        }
    )
    path = root / "notification-process-proof.json"
    path.write_text(json.dumps(history, indent=2) + "\n")
    path.chmod(0o600)


async def main() -> None:
    """Always stop/wait only the two recorded owned workers; never leave an orphan on failure."""
    try:
        await run_case()
    finally:
        await stop_owned_workers(_TASK_ROOT)


async def stop_owned_workers(root: Path | None) -> None:
    """Strong unreaped Popen ownership survives a failed PID-start observation."""
    exits = []
    for child, start in _OWNED:
        record: dict[str, object] = {
            "pid": child.pid,
            "start": start,
            "start_observed": start is not None,
            "exit": None,
            "cleanup_kill": False,
        }
        try:
            status = child.poll()
            if status is None:
                if start is not None:
                    try:
                        actual = process_start(child.pid)
                    except FileNotFoundError:
                        record["metadata_error"] = "pid_start_unavailable"
                        status = await asyncio.to_thread(child.wait, timeout=10)
                    else:
                        if actual != start:
                            raise ValueError("Owned PID-start metadata mismatched; no kill")
                if status is None:
                    child.kill()
                    record["cleanup_kill"] = True
                    status = await asyncio.to_thread(child.wait, timeout=10)
            record["exit"] = status
        except Exception as exc:
            record["cleanup_error"] = type(exc).__name__
        exits.append(record)
    if root is not None and root.exists():
        path = root / "controller-process-exits.json"
        path.write_text(json.dumps({"owned": exits}, indent=2) + "\n")
        path.chmod(0o600)
    if any(
        row.get("cleanup_error") or row.get("metadata_error") or row["exit"] is None
        for row in exits
    ):
        raise ValueError("Notification owned worker cleanup is incomplete")


if __name__ == "__main__":
    asyncio.run(main())

"""Controller spawn envelopes contain no credential and reject a third or malformed worker."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from pydantic import SecretStr

from nexus.settings import settings
from nexus.tests import notification_process_controller as module
from nexus.tests.unit.test_notification_process_config import config


@pytest.fixture(autouse=True)
def controller_test_location(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mocked spawn tests use their actually imported tree; runtime closed pins stay unchanged."""
    monkeypatch.setattr(module, "_SOURCE", Path(module.__file__).resolve().parents[2])
    monkeypatch.setattr(module, "_PYTHON", Path(sys.executable))


async def test_spawn_uses_closed_args_and_one_inherited_pipe_then_closes_parent_ends(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    described = (await config(tmp_path, monkeypatch)).model_copy(update={"root": tmp_path})
    monkeypatch.setattr(module, "require_notification_process_root", MagicMock())
    monkeypatch.setattr(module, "_OWNED", [])
    monkeypatch.setattr(
        settings,
        "company_test_database_url",
        "postgresql+asyncpg://santapong@/nexus_company_test_notification_process_intent?host=/tmp/nexus-release-tests-2026-10-13/socket&port=55438",
    )
    monkeypatch.setattr(module, "process_start", lambda pid: "observed-start")
    captured: dict[str, object] = {}
    held: list[int] = []
    child = MagicMock()
    child.pid = 12345

    def spawn(arguments: list[str], **kwargs: object) -> MagicMock:
        passed = kwargs["pass_fds"]
        assert isinstance(passed, tuple) and len(passed) == 1
        assert isinstance(passed[0], int)
        held.append(os.dup(passed[0]))
        captured.update(kwargs)
        captured["arguments"] = arguments
        return child

    monkeypatch.setattr(subprocess, "Popen", spawn)
    try:
        value, start = module.start_worker(
            described, SecretStr("header.payload.signature"), str(UUID(int=981)), barrier=True
        )
        assert value is child and start == "observed-start"
        assert os.read(held[0], 4096) == b"header.payload.signature"
        assert os.read(held[0], 1) == b""
        assert "header.payload.signature" not in str(captured)
        assert captured["start_new_session"] is True
        assert [(child, "observed-start")] == module._OWNED
        passed = captured["pass_fds"]
        assert isinstance(passed, tuple)
        with pytest.raises(OSError):
            os.fstat(passed[0])
    finally:
        for fd in held:
            os.close(fd)


@pytest.mark.parametrize("invalid", ["third", "bad_uuid"])
async def test_no_third_worker_or_path_like_worker_id_can_spawn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid: str,
) -> None:
    described = await config(tmp_path, monkeypatch)
    monkeypatch.setattr(module, "require_notification_process_root", MagicMock())
    monkeypatch.setattr(
        module, "_OWNED", [(MagicMock(), "s"), (MagicMock(), "s")] if invalid == "third" else []
    )
    spawn = MagicMock()
    monkeypatch.setattr(subprocess, "Popen", spawn)
    with pytest.raises(ValueError):
        module.start_worker(
            described,
            SecretStr("not-output"),
            str(UUID(int=981)) if invalid == "third" else "../wrong",
            barrier=False,
        )
    spawn.assert_not_called()


async def test_failed_postspawn_pid_start_read_keeps_strong_handle_for_bounded_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    described = (await config(tmp_path, monkeypatch)).model_copy(update={"root": tmp_path})
    monkeypatch.setattr(module, "require_notification_process_root", MagicMock())
    monkeypatch.setattr(module, "_OWNED", [])
    monkeypatch.setattr(
        settings,
        "company_test_database_url",
        "postgresql+asyncpg://santapong@/nexus_company_test_notification_process_intent?host=/tmp/nexus-release-tests-2026-10-13/socket&port=55438",
    )
    child = MagicMock()
    child.pid = 12345
    child.poll.return_value = None
    child.wait.return_value = -9
    monkeypatch.setattr(subprocess, "Popen", MagicMock(return_value=child))
    monkeypatch.setattr(
        module, "process_start", MagicMock(side_effect=OSError("nominated postspawn stat failure"))
    )
    with pytest.raises(OSError, match="nominated postspawn"):
        module.start_worker(described, SecretStr("not-exposed"), str(UUID(int=982)), barrier=True)
    assert [(child, None)] == module._OWNED
    await module.stop_owned_workers(tmp_path)
    child.kill.assert_called_once()
    child.wait.assert_called_once_with(timeout=10)
    recorded = json.loads((tmp_path / "controller-process-exits.json").read_text())["owned"][0]
    assert recorded["start"] is None and not recorded["start_observed"]
    assert recorded["cleanup_kill"] and recorded["exit"] == -9


@pytest.mark.parametrize("metadata", ["mismatch", "absent"])
async def test_cleanup_records_metadata_error_and_still_stops_second_owned_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    metadata: str,
) -> None:
    first, second = MagicMock(), MagicMock()
    first.pid, second.pid = 123, 456
    first.poll.return_value = second.poll.return_value = None
    first.wait.return_value = 0
    second.wait.return_value = -9
    monkeypatch.setattr(module, "_OWNED", [(first, "original1"), (second, "original2")])
    monkeypatch.setattr(
        module,
        "process_start",
        MagicMock(
            side_effect=[
                "foreign"
                if metadata == "mismatch"
                else FileNotFoundError("nominated vanished proc"),
                "original2",
            ]
        ),
    )
    with pytest.raises(ValueError, match="cleanup is incomplete"):
        await module.stop_owned_workers(tmp_path)
    first.kill.assert_not_called()
    second.kill.assert_called_once()
    rows = json.loads((tmp_path / "controller-process-exits.json").read_text())["owned"]
    assert len(rows) == 2
    if metadata == "mismatch":
        assert rows[0]["cleanup_error"] == "ValueError"
    else:
        assert rows[0]["metadata_error"] == "pid_start_unavailable" and rows[0]["exit"] == 0
    assert rows[1]["exit"] == -9 and rows[1]["cleanup_kill"]


@pytest.mark.parametrize("mismatch", ["source", "runtime"])
async def test_explicit_source_or_runtime_mismatch_still_denies_before_spawn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mismatch: str,
) -> None:
    described = await config(tmp_path, monkeypatch)
    monkeypatch.setattr(
        module, "_SOURCE" if mismatch == "source" else "_PYTHON", tmp_path / "wrong"
    )
    spawn = MagicMock()
    monkeypatch.setattr(subprocess, "Popen", spawn)
    with pytest.raises(ValueError, match="source/runtime differs"):
        module.start_worker(described, SecretStr("not-output"), str(UUID(int=983)), barrier=True)
    spawn.assert_not_called()

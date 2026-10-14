"""Actual parser semantics with a fake engine boundary; no engine invocation."""

import json
import os
from pathlib import Path

import pytest

import nexus.builder.contained_observer_io as observed_io
from nexus.builder.contained_contracts import ParentObservation
from nexus.builder.contained_evidence_types import ObservationDeadline
from nexus.builder.contained_kernel import open_directory
from nexus.builder.contained_observer_io import (
    OwnedObservationIO,
    decode_engine_object,
    inspect_argv,
)
from nexus.tests.contained_observer_fixture import BOOT, GROUP, container, parent


def engine_body() -> bytes:
    expected = container()
    return json.dumps(
        {
            "container_id": expected.container_id,
            "image_id": expected.image_id,
            "company_id": str(expected.company_id),
            "action_id": str(expected.action_id),
            "running": True,
            "payload_pid": 101,
            "conmon_pid": 102,
        }
    ).encode()


def test_fixed_inspect_binds_immutable_identity() -> None:
    value = decode_engine_object(engine_body(), container())
    assert value.payload_pid == 101 and value.conmon_pid == 102
    argv = inspect_argv(container())
    assert argv[:3] == ("/usr/bin/podman", "--remote=false", "--cgroup-manager=cgroupfs")
    assert argv[-1] == container().container_id


@pytest.mark.parametrize(
    "field,value",
    [
        ("container_id", "f" * 64),
        ("image_id", "f" * 64),
        ("payload_pid", True),
        ("running", False),
        ("conmon_pid", None),
        ("extra", "pass"),
    ],
)
def test_wrong_engine_fields_deny(field: str, value: object) -> None:
    row = json.loads(engine_body())
    row[field] = value
    with pytest.raises(ValueError):
        decode_engine_object(json.dumps(row).encode(), container())


def test_duplicate_or_oversized_engine_json_denies() -> None:
    for raw in (b'{"running":true,"running":true}', b"x" * 65537):
        with pytest.raises(ValueError):
            decode_engine_object(raw, container())


def generated_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ParentObservation:
    """Generated ordinary FD/proc files; these facts are synthetic, never native proof."""
    root = tmp_path / "cgroup"
    proc = tmp_path / "proc"
    root.mkdir()
    proc.mkdir()
    main = root / GROUP.removeprefix("/")
    main.mkdir(parents=True)
    for name, pid in (("", 103), ("payload", 101), ("conmon", 102), ("worker", 104)):
        group = main / name
        group.mkdir(exist_ok=True)
        for file, raw in {
            "memory.max": b"4294967296\n",
            "cpu.max": b"200000 100000\n",
            "pids.max": b"256\n",
            "cgroup.procs": f"{pid}\n".encode(),
        }.items():
            (group / file).write_bytes(raw)
        pid_root = proc / str(pid)
        pid_root.mkdir()
        fields = ["R", *(["0"] * 18), str(pid * 10)]
        (pid_root / "stat").write_text(f"{pid} (worker ) name) " + " ".join(fields))
        (pid_root / "cgroup").write_text("0::" + GROUP + ("/" + name if name else "") + "\n")
    monkeypatch.setattr(observed_io, "CGROUP_ROOT", root)
    monkeypatch.setattr(observed_io, "PROC_ROOT", proc)
    monkeypatch.setattr(observed_io, "_boot", lambda: BOOT)
    monkeypatch.setattr(observed_io, "clock_us", lambda: 12_020_000)
    value = parent().model_dump()
    for key in ("expectation", "kernel"):
        value[key]["mount_device"] = root.stat().st_dev
        value[key]["mount_inode"] = root.stat().st_ino
        value[key]["cgroup_inode"] = main.stat().st_ino
        with open_directory(root, ()) as fd:
            value[key]["mount_id"] = observed_io._fd_mount_id(fd)
    value["kernel"]["uid"] = os.geteuid()
    value["kernel"]["directory_uid"] = os.geteuid()
    return ParentObservation.model_validate(value)


class Engine:
    """Only fixed engine boundary is faked; subtree/proc parsing/reads are actual."""

    async def query(self, argv: tuple[str, ...], deadline_us: int, limit: int) -> bytes:
        assert argv == inspect_argv(container()) and deadline_us == 13_000_000 and limit == 65536
        return engine_body()


@pytest.mark.asyncio
async def test_actual_generated_subtree_and_proc_identity_are_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_parent = generated_tree(tmp_path, monkeypatch)
    io = OwnedObservationIO(Engine())
    row = await io.observe(expected_parent, container(), ObservationDeadline(end_us=13_000_000), ())
    assert row.tree_complete and row.subtree_count == 4
    assert {p.pid for p in row.processes} == {101, 102, 103, 104}
    assert row.memory_bytes == 4294967296 and row.cpu_quota_us == 200000
    assert row.status == "observed_contained"


@pytest.mark.asyncio
async def test_gone_exact_pid_is_retired_but_reused_or_unreadable_pid_is_not(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_parent = generated_tree(tmp_path, monkeypatch)
    io = OwnedObservationIO(Engine())
    deadline = ObservationDeadline(end_us=13_000_000)
    first = await io.observe(expected_parent, container(), deadline, ())
    worker = next(p for p in first.processes if p.pid == 104)
    (observed_io.CGROUP_ROOT / GROUP.removeprefix("/") / "worker" / "cgroup.procs").write_bytes(b"")
    # Existing PID outside the complete inventory cannot count as gone.
    with pytest.raises(ValueError):
        await io.observe(expected_parent, container(), deadline, (worker,))
    (observed_io.PROC_ROOT / "104" / "stat").unlink()
    with pytest.raises(ValueError):
        await io.observe(expected_parent, container(), deadline, (worker,))
    (observed_io.PROC_ROOT / "104" / "cgroup").unlink()
    (observed_io.PROC_ROOT / "104").rmdir()
    retired = await io.observe(expected_parent, container(), deadline, (worker,))
    assert retired.retired_processes == (worker,)
    (observed_io.PROC_ROOT / "104").mkdir()
    (observed_io.PROC_ROOT / "104" / "stat").write_text("104 (reused) R " + "0 " * 18 + "9999")
    (observed_io.PROC_ROOT / "104" / "cgroup").write_text("0::" + GROUP + "\n")
    with pytest.raises(ValueError, match="reused"):
        await io.observe(expected_parent, container(), deadline, (worker,))


@pytest.mark.asyncio
async def test_process_or_directory_overflow_never_shortens_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_parent = generated_tree(tmp_path, monkeypatch)
    main = observed_io.CGROUP_ROOT / GROUP.removeprefix("/")
    (main / "cgroup.procs").write_text("\n".join(str(i) for i in range(1000, 1257)))
    with pytest.raises(ValueError, match="cap"):
        await OwnedObservationIO(Engine()).observe(
            expected_parent, container(), ObservationDeadline(end_us=13_000_000), ()
        )


@pytest.mark.asyncio
async def test_sibling_proc_path_or_changed_start_cannot_qualify(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_parent = generated_tree(tmp_path, monkeypatch)
    (observed_io.PROC_ROOT / "101" / "cgroup").write_text("0::" + GROUP + "-sibling/payload\n")
    with pytest.raises(ValueError):
        await OwnedObservationIO(Engine()).observe(
            expected_parent, container(), ObservationDeadline(end_us=13_000_000), ()
        )


@pytest.mark.asyncio
async def test_actual_mount_id_or_root_inode_change_denies_same_device(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_parent = generated_tree(tmp_path, monkeypatch)
    io = OwnedObservationIO(Engine())
    deadline = ObservationDeadline(end_us=13_000_000)
    with monkeypatch.context() as patch:
        patch.setattr(observed_io, "_fd_mount_id", lambda _: expected_parent.kernel.mount_id + 1)
        with pytest.raises(ValueError, match="mount"):
            await io.observe(expected_parent, container(), deadline, ())
    root = observed_io.CGROUP_ROOT
    root.rename(tmp_path / "historical-cgroup")
    root.mkdir()
    with pytest.raises(ValueError, match="mount root"):
        await io.observe(expected_parent, container(), deadline, ())

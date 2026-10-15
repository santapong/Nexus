"""Ordinary fake proc/mount descriptors only; never read native host proc or cgroups."""

from __future__ import annotations

import hashlib
import os
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, dataclass
from pathlib import Path
from uuid import UUID

import pytest

import nexus.builder.contained_kernel as module
from nexus.builder import contained_observer_io

ROW = b"35 26 0:29 / /sys/fs/cgroup rw,nodev - cgroup2 cgroup2 rw\n"


def metadata(error: BaseException) -> module.KernelRead:
    record = error.__dict__["_nexus_mount_read"]
    assert type(record) is module.KernelRead
    return record


def body(size: int) -> bytes:
    assert size >= len(ROW)
    return ROW + b"\n" * (size - len(ROW))


@dataclass
class Context:
    proc: Path
    mount: Path
    namespace: Path


@pytest.fixture
def context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Context:
    proc, mount = tmp_path / "proc", tmp_path / "mount"
    proc.mkdir()
    mount.mkdir()
    (proc / "ns").mkdir()
    namespace = tmp_path / "namespace"
    namespace.write_bytes(b"fixture namespace handle")
    (proc / "ns/mnt").symlink_to(namespace)
    (proc / "mountinfo").write_bytes(ROW)
    original = module.open_directory

    @contextmanager
    def redirected(root: Path, parts: tuple[str, ...]) -> Iterator[int]:
        if root == Path(f"/proc/{os.getpid()}"):
            root = proc
        elif root == Path("/sys/fs/cgroup"):
            root = mount
        else:
            raise AssertionError("Unexpected native descriptor path")
        with original(root, parts) as fd:
            yield fd

    monkeypatch.setattr(module, "open_directory", redirected)
    monkeypatch.setattr(module, "_boot", lambda: UUID(int=1))
    monkeypatch.setattr(module, "_self_path", lambda: "/fixture.scope")
    monkeypatch.setattr(contained_observer_io, "_fd_mount_id", lambda fd: 35)
    return Context(proc, mount, namespace)


def test_actual_5142_byte_mount_table_exceeds_old_generic_cap_but_is_valid(
    context: Context,
) -> None:
    (context.proc / "mountinfo").write_bytes(body(5142))
    assert module._mount_id() == 35


@pytest.mark.parametrize("size", [4096, 5142, 65536])
def test_fixed_mount_reader_accepts_complete_finite_bytes_and_same_call_metadata(
    context: Context, size: int
) -> None:
    raw = body(size)
    (context.proc / "mountinfo").write_bytes(raw)
    value = module._mount_observation()
    assert (value.mount_id, value.observed_length, value.observed_sha256) == (
        35,
        size,
        hashlib.sha256(raw).hexdigest(),
    )
    assert (value.namespace_dev, value.namespace_inode) == (
        context.namespace.stat().st_dev,
        context.namespace.stat().st_ino,
    )
    with pytest.raises(FrozenInstanceError):
        value.mount_id = 9  # type: ignore[misc]  # Deliberate frozen-data mutation.


@pytest.mark.parametrize("size", [65537, 70000])
def test_overflow_reports_actual_capped_prefix_not_total_file_size(
    context: Context, size: int
) -> None:
    raw = body(size)
    (context.proc / "mountinfo").write_bytes(raw)
    with pytest.raises(ValueError) as caught:
        module._mount_observation()
    record = metadata(caught.value)
    assert type(record) is module.KernelRead
    assert (record.file, record.status, record.observed_length, record.observed_sha256) == (
        "mountinfo",
        "overflow",
        65537,
        hashlib.sha256(raw[:65537]).hexdigest(),
    )
    assert record.observed_length == min(len(raw), 65537)
    with pytest.raises(FrozenInstanceError):
        record.status = "complete"  # type: ignore[misc]  # Deliberate frozen-data mutation.


def test_generic_reader_stays_4096_and_mount_filename_is_not_selectable(context: Context) -> None:
    (context.proc / "mountinfo").write_bytes(body(4097))
    with module.open_directory(Path(f"/proc/{os.getpid()}"), ()) as fd:
        with pytest.raises(ValueError):
            module.read_bounded(fd, "mountinfo")
        with pytest.raises(TypeError):
            module.read_mountinfo(fd, "other")  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"\xff",
        b"35 - cgroup2 \n",
        ROW + ROW,
        ROW.replace(b" - cgroup2 ", b" - cgroup "),
        ROW.replace(b"/sys/fs/cgroup", b"/other"),
        ROW.replace(b" / /sys", b" /wrong /sys"),
        ROW.replace(b" rw,nodev ", b" ro,nodev "),
        ROW.replace(b"35 ", b"035 ", 1),
        ROW.replace(b"35 ", b"0 ", 1),
    ],
)
def test_malformed_or_ambiguous_complete_table_denies_with_read_metadata(
    context: Context, raw: bytes
) -> None:
    (context.proc / "mountinfo").write_bytes(raw)
    with pytest.raises(ValueError) as caught:
        module._mount_observation()
    record = metadata(caught.value)
    assert record.status == "complete" and record.observed_length == len(raw)
    assert record.observed_sha256 == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize(
    "fault", ["namespace", "proc", "mount", "boot", "membership", "uid", "fd_mount"]
)
def test_changed_identity_after_same_read_denies_without_reopening_mountinfo(
    context: Context, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    actual = module.read_mountinfo
    calls = []
    mount_id = [35]
    monkeypatch.setattr(contained_observer_io, "_fd_mount_id", lambda fd: mount_id[0])

    def changed(fd: int) -> bytes:
        raw = actual(fd)
        calls.append(fd)
        if fault == "namespace":
            other = context.namespace.with_name("other")
            other.write_bytes(b"different namespace")
            (context.proc / "ns/mnt").unlink()
            (context.proc / "ns/mnt").symlink_to(other)
        elif fault == "proc":
            old = context.proc.with_name("old-proc")
            context.proc.rename(old)
            shutil.copytree(old, context.proc, symlinks=True)
        elif fault == "mount":
            context.mount.rename(context.mount.with_name("old-mount"))
            context.mount.mkdir()
        elif fault == "boot":
            monkeypatch.setattr(module, "_boot", lambda: UUID(int=2))
        elif fault == "membership":
            monkeypatch.setattr(module, "_self_path", lambda: "/other")
        elif fault == "uid":
            monkeypatch.setattr(os, "geteuid", lambda: 1001)
        else:
            mount_id[0] = 36
        return raw

    monkeypatch.setattr(module, "read_mountinfo", changed)
    with pytest.raises(ValueError) as caught:
        module._mount_observation()
    assert len(calls) == 1
    assert metadata(caught.value).status == "complete"


@pytest.mark.parametrize("fault", ["read", "symlink"])
def test_failed_mount_read_preserves_original_error_and_closes_owned_fd(
    context: Context, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    opened: list[int] = []
    actual_open, actual_read = os.open, os.read
    original_error = OSError("finite supplied read error")

    def track(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        fd = actual_open(path, flags, mode, dir_fd=dir_fd)
        opened.append(fd)
        return fd

    def read(fd: int, size: int) -> bytes:
        if fd in opened:
            raise original_error
        return actual_read(fd, size)

    if fault == "symlink":
        (context.proc / "mountinfo").unlink()
        (context.proc / "mountinfo").symlink_to(context.namespace)
    else:
        monkeypatch.setattr(os, "read", read)
    monkeypatch.setattr(os, "open", track)
    with pytest.raises(OSError) as caught:
        module._mount_observation()
    if fault == "read":
        assert caught.value is original_error
    record = metadata(caught.value)
    assert (record.status, record.observed_length, record.observed_sha256) == (
        "unavailable",
        None,
        None,
    )
    for fd in opened:
        with pytest.raises(OSError):
            os.fstat(fd)


def test_reader_honors_short_reads_until_actual_eof(
    context: Context, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = body(65536)
    (context.proc / "mountinfo").write_bytes(raw)
    actual = os.read

    def short(fd: int, size: int) -> bytes:
        return actual(fd, min(size, 97))

    monkeypatch.setattr(os, "read", short)
    assert module._mount_observation().observed_length == len(raw)

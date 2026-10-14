"""Owned read descriptors reject traversal, links, replacement and oversized kernel bytes."""

import os
from contextlib import AbstractContextManager
from pathlib import Path

import pytest

import nexus.builder.contained_kernel as kernel_module
from nexus.builder.contained_contracts import UserManagerObservation
from nexus.builder.contained_kernel import collect_kernel, open_directory, read_bounded, read_uint
from nexus.tests.unit.test_contained_scope import BOOT, GROUP, expectation, user_manager


def test_no_follow_component_walk_and_limit_reads(tmp_path: Path) -> None:
    child = tmp_path / "scope"
    child.mkdir()
    (child / "memory.max").write_bytes(b"4294967296\n")
    with open_directory(tmp_path, ("scope",)) as fd:
        assert read_uint(read_bounded(fd, "memory.max")) == 4_294_967_296


@pytest.mark.parametrize("parts", [("..",), (".",), ("/scope",), ("scope/other",)])
def test_directory_traversal_denies(tmp_path: Path, parts: tuple[str, ...]) -> None:
    with pytest.raises(ValueError), open_directory(tmp_path, parts):
        pytest.fail("Traversal unexpectedly opened")


def test_symlink_directory_and_file_denies(tmp_path: Path) -> None:
    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "real", target_is_directory=True)
    with pytest.raises(OSError), open_directory(tmp_path, ("link",)):
        pytest.fail("Symlink unexpectedly opened")
    (tmp_path / "fake").symlink_to("/proc/self/stat")
    with open_directory(tmp_path, ()) as fd, pytest.raises(OSError):
        read_bounded(fd, "fake")


def test_overflow_denies_and_fd_closes(tmp_path: Path) -> None:
    (tmp_path / "large").write_bytes(b"1" * 4097)
    with open_directory(tmp_path, ()) as fd, pytest.raises(ValueError):
        read_bounded(fd, "large")
    with pytest.raises(OSError):
        os.fstat(fd)


@pytest.mark.parametrize("raw", [b"max", b"-1", b"1.0", b"true", b"1 2", b"01", b""])
def test_kernel_integer_parser_rejects_unlimited_or_noncanonical_values(raw: bytes) -> None:
    with pytest.raises(ValueError):
        read_uint(raw)


def setup_kernel_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Generated ordinary files exercise collector FD identity and real bounded reads."""
    group = tmp_path / GROUP.removeprefix("/")
    group.mkdir(parents=True)
    for name, raw in {
        "cpu.max": b"200000 100000\n",
        "memory.max": b"4294967296\n",
        "pids.max": b"256\n",
        "cgroup.controllers": b"cpu memory pids\n",
    }.items():
        (group / name).write_bytes(raw)
    os.setxattr(group, "user.delegate", b"1")
    original = open_directory

    def redirected(root: Path, parts: tuple[str, ...]) -> AbstractContextManager[int]:
        return original(tmp_path if root == Path("/sys/fs/cgroup") else root, parts)

    monkeypatch.setattr(kernel_module, "open_directory", redirected)
    monkeypatch.setattr(kernel_module, "_self_path", lambda: GROUP)
    monkeypatch.setattr(kernel_module, "_mount_id", lambda: 32)
    monkeypatch.setattr(kernel_module, "_boot", lambda: BOOT)
    return group


def test_complete_kernel_collector_reads_actual_owned_tree_without_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group = setup_kernel_tree(tmp_path, monkeypatch)
    row = collect_kernel(expectation(), user_manager())
    assert row.cgroup_inode == group.stat().st_ino
    assert row.mount_inode == tmp_path.stat().st_ino
    assert row.controllers == frozenset({"cpu", "memory", "pids"})
    assert row.cpu_quota_us == 200_000 and row.cpu_period_us == 100_000


def test_collector_rejects_replaced_directory_while_original_fd_remains_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group = setup_kernel_tree(tmp_path, monkeypatch)
    original = kernel_module._group_values

    def replaced(fd: int, context: UserManagerObservation) -> dict[str, object]:
        values = original(fd, context)
        group.rename(group.with_name("historical"))
        group.mkdir()
        return values

    monkeypatch.setattr(kernel_module, "_group_values", replaced)
    with pytest.raises(ValueError, match="replaced"):
        collect_kernel(expectation(), user_manager())


def test_collector_records_actual_absence_under_supported_user_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group = setup_kernel_tree(tmp_path, monkeypatch)
    os.removexattr(group, "user.delegate")
    assert collect_kernel(expectation(), user_manager()).delegation_marker == "absent_user_manager"

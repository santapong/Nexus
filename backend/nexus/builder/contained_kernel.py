"""Bounded read-only no-follow kernel collection; no host cgroup writes or scope creation."""

from __future__ import annotations

import errno
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

from nexus.builder.contained_contracts import (
    KernelScopeFacts,
    ScopeExpectation,
    UserManagerObservation,
    cgroup_components,
    require_user_manager,
)


@contextmanager
def open_directory(root: Path, parts: tuple[str, ...]) -> Iterator[int]:
    """Hold component-wise no-follow descriptors and close them even on failure."""
    if any(part in {"", ".", ".."} or "/" in part for part in parts):
        raise ValueError("Unsafe scope directory component")
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        for part in parts:
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd
            )
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def read_bounded(fd: int, name: str) -> bytes:
    """Read one owned no-follow file with a fixed4096byte cap and exact fd cleanup."""
    if not re.fullmatch(r"[a-z0-9._-]+", name):
        raise ValueError("Unsafe scope kernel filename")
    child = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=fd)
    try:
        body = bytearray()
        while chunk := os.read(child, min(4097 - len(body), 4096)):
            body.extend(chunk)
            if len(body) > 4096:
                raise ValueError("Scope kernel file exceeds the fixed byte cap")
        return bytes(body)
    finally:
        os.close(child)


def read_uint(raw: bytes) -> int:
    """Unlimited/negative/fractional/noncanonical values are not numeric bounds."""
    value = raw.removesuffix(b"\n")
    if not re.fullmatch(rb"0|[1-9][0-9]{0,19}", value) or int(value) >= 2**64 - 1:
        raise ValueError("Scope numeric kernel limit is unavailable")
    return int(value)


def _self_path() -> str:
    with open_directory(Path(f"/proc/{os.getpid()}"), ()) as fd:
        rows = read_bounded(fd, "cgroup").decode("ascii").splitlines()
    if len(rows) != 1 or not rows[0].startswith("0::"):
        raise ValueError("Scope unified cgroup membership is unavailable")
    value = rows[0][3:]
    cgroup_components(value)
    return value


def _mount_id() -> int:
    with open_directory(Path(f"/proc/{os.getpid()}"), ()) as fd:
        rows = read_bounded(fd, "mountinfo").decode("ascii").splitlines()
    matches = [row.split() for row in rows if " - cgroup2 " in row]
    if (
        len(matches) != 1
        or matches[0][3:5] != ["/", "/sys/fs/cgroup"]
        or "rw" not in matches[0][5].split(",")
    ):
        raise ValueError("Scope cgroup2 mount identity is unavailable")
    return read_uint(matches[0][0].encode())


def _boot() -> UUID:
    with open_directory(Path("/proc/sys/kernel/random"), ()) as fd:
        raw = read_bounded(fd, "boot_id")
    return UUID(raw.decode("ascii").strip())


def collect_kernel(expected: ScopeExpectation, manager: UserManagerObservation) -> KernelScopeFacts:
    """Collect/recheck held identities; a to_thread timeout cannot kill a blocked read thread."""
    self_path = _self_path()
    mount_id, boot, uid = _mount_id(), _boot(), os.geteuid()
    require_user_manager(manager, uid)
    with open_directory(Path("/sys/fs/cgroup"), ()) as mount_fd:
        mount = os.fstat(mount_fd)
    with open_directory(Path("/sys/fs/cgroup"), cgroup_components(expected.cgroup_path)) as fd:
        group = os.fstat(fd)
        if group.st_uid != uid or expected.uid != uid:
            raise ValueError("Scope kernel directory is not owned by the current user")
        values = _group_values(fd, manager)
        held = os.fstat(fd)
        if (
            (held.st_dev, held.st_ino, held.st_uid) != (group.st_dev, group.st_ino, group.st_uid)
            or group.st_dev != mount.st_dev
            or _self_path() != self_path
            or _boot() != boot
        ):
            raise ValueError("Scope kernel identity changed during collection")
        with open_directory(
            Path("/sys/fs/cgroup"), cgroup_components(expected.cgroup_path)
        ) as fresh:
            current = os.fstat(fresh)
            if (current.st_dev, current.st_ino) != (group.st_dev, group.st_ino):
                raise ValueError("Scope directory was replaced during collection")
    with open_directory(Path("/sys/fs/cgroup"), ()) as fresh_mount:
        current_mount = os.fstat(fresh_mount)
        if (current_mount.st_dev, current_mount.st_ino) != (
            mount.st_dev,
            mount.st_ino,
        ) or _mount_id() != mount_id:
            raise ValueError("Scope mount was replaced during collection")
    return KernelScopeFacts.model_validate(
        {
            "user_manager": manager,
            "uid": uid,
            "boot_id": boot,
            "self_cgroup_path": self_path,
            "mount_id": mount_id,
            "mount_device": mount.st_dev,
            "mount_inode": mount.st_ino,
            "cgroup_path": expected.cgroup_path,
            "cgroup_inode": group.st_ino,
            "directory_uid": group.st_uid,
            **values,
        }
    )


def _group_values(fd: int, manager: UserManagerObservation) -> dict[str, object]:
    cpu = read_bounded(fd, "cpu.max").strip().split(b" ")
    if len(cpu) != 2:
        raise ValueError("Scope CPU kernel limit shape differs")
    return {
        "delegation_marker": _marker(fd, manager),
        "controllers": frozenset(read_bounded(fd, "cgroup.controllers").decode("ascii").split()),
        "memory_bytes": read_uint(read_bounded(fd, "memory.max")),
        "cpu_quota_us": read_uint(cpu[0]),
        "cpu_period_us": read_uint(cpu[1]),
        "pids": read_uint(read_bounded(fd, "pids.max")),
    }


def _marker(fd: int, manager: UserManagerObservation) -> str:
    require_user_manager(manager, os.geteuid())
    try:
        value = os.getxattr(fd, "user.delegate")
    except OSError as error:
        if error.errno != errno.ENODATA:
            raise
        # v261.2 user manager does not apply delegate xattrs; absence stays explicit.
        return "absent_user_manager"
    if value != b"1":
        raise ValueError("Scope actual delegation marker is malformed or false")
    return "present_1"

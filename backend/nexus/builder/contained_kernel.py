"""Bounded read-only no-follow kernel collection; no host cgroup writes or scope creation."""

from __future__ import annotations

import errno
import hashlib
import os
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
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


@dataclass(frozen=True, slots=True)
class KernelRead:
    file: Literal["mountinfo"]
    observed_length: int | None
    observed_sha256: str | None
    status: Literal["complete", "overflow", "unavailable"]


@dataclass(frozen=True, slots=True)
class MountObservation:
    mount_id: int
    observed_length: int
    observed_sha256: str
    namespace_dev: int
    namespace_inode: int


@contextmanager
def _owned_fd(fd: int) -> Iterator[int]:
    try:
        yield fd
    finally:
        primary = sys.exception()
        try:
            os.close(fd)
        except OSError as error:
            if primary is None:
                raise
            primary.__dict__["_nexus_mount_close_error"] = type(error).__name__


def read_mountinfo(fd: int) -> bytes:
    """Only mountinfo has64KiB; overflow metadata describes the actual capped prefix."""
    record = KernelRead("mountinfo", None, None, "unavailable")
    try:
        child = os.open(
            "mountinfo", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=fd
        )
        with _owned_fd(child):
            body = bytearray()
            while chunk := os.read(child, min(65537 - len(body), 65536)):
                body.extend(chunk)
                if len(body) > 65536:
                    record = KernelRead(
                        "mountinfo", len(body), hashlib.sha256(body).hexdigest(), "overflow"
                    )
                    raise ValueError("Scope mountinfo exceeds the fixed64KiB byte cap")
            record = KernelRead(
                "mountinfo", len(body), hashlib.sha256(body).hexdigest(), "complete"
            )
            return bytes(body)
    except BaseException as error:
        error.__dict__["_nexus_mount_read"] = record
        raise


def _parse_mountinfo(raw: bytes) -> int:
    rows = raw.decode("ascii").splitlines()
    matches = [row.split() for row in rows if " - cgroup2 " in row]
    if (
        len(matches) != 1
        or len(matches[0]) < 10
        or matches[0][3:5] != ["/", "/sys/fs/cgroup"]
        or "rw" not in matches[0][5].split(",")
        or "ro" in matches[0][5].split(",")
    ):
        raise ValueError("Scope cgroup2 mount identity is unavailable")
    identity = read_uint(matches[0][0].encode())
    if identity == 0:
        raise ValueError("Scope cgroup2 mount identity is not positive")
    return identity


def _signature(fd: int) -> tuple[int, int, int]:
    value = os.fstat(fd)
    return value.st_dev, value.st_ino, value.st_uid


def _mount_observation() -> MountObservation:
    """One read binds actual mount metadata to held/current namespace and mount FDs."""
    # Deferred reuse avoids the observer's import of this module without another fdinfo parser.
    from nexus.builder.contained_observer_io import _fd_mount_id

    record = KernelRead("mountinfo", None, None, "unavailable")
    attempted = False
    try:
        uid, boot, self_path = os.geteuid(), _boot(), _self_path()
        proc = Path(f"/proc/{os.getpid()}")
        with open_directory(proc, ()) as source:
            original_proc = _signature(source)
            if original_proc[2] != uid:
                raise ValueError("Actual own proc directory UID differs")
            flags = os.O_RDONLY | os.O_CLOEXEC
            # Only this fixed own-proc namespace link is intentionally resolved.
            with (
                _owned_fd(
                    os.open("ns", flags | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=source)
                ) as ns,
                _owned_fd(os.open("mnt", flags, dir_fd=ns)) as namespace,
            ):
                original_ns = _signature(namespace)[:2]
                with open_directory(Path("/sys/fs/cgroup"), ()) as root:
                    original_root = _signature(root)
                    attempted = True
                    raw = read_mountinfo(source)
                    record = KernelRead(
                        "mountinfo", len(raw), hashlib.sha256(raw).hexdigest(), "complete"
                    )
                    identity = _parse_mountinfo(raw)
                    if _fd_mount_id(root) != identity:
                        raise ValueError("Held cgroup mount ID differs from actual mount table")
                    with open_directory(proc, ()) as again:
                        if _signature(again) != original_proc:
                            raise ValueError("Actual own proc directory was replaced")
                        with _owned_fd(
                            os.open("ns", flags | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=again)
                        ) as current_ns:
                            visible = os.stat("mnt", dir_fd=current_ns)
                    if (
                        _signature(namespace)[:2] != original_ns
                        or (visible.st_dev, visible.st_ino) != original_ns
                    ):
                        raise ValueError("Actual mount namespace identity changed")
                    with open_directory(Path("/sys/fs/cgroup"), ()) as again:
                        if _signature(again) != original_root or _fd_mount_id(again) != identity:
                            raise ValueError("Visible cgroup mount root was replaced")
                    if _signature(root) != original_root or _fd_mount_id(root) != identity:
                        raise ValueError("Held cgroup mount root changed")
                    if (os.geteuid(), _boot(), _self_path()) != (uid, boot, self_path):
                        raise ValueError("Actual UID/boot/self membership changed")
        return MountObservation(identity, len(raw), hashlib.sha256(raw).hexdigest(), *original_ns)
    except BaseException as error:
        inner = getattr(error, "_nexus_mount_read", None)
        if attempted and record.status == "unavailable" and type(inner) is KernelRead:
            record = inner
        error.__dict__["_nexus_mount_read"] = record
        raise


def _mount_id() -> int:
    return _mount_observation().mount_id


def _boot() -> UUID:
    with open_directory(Path("/proc/sys/kernel/random"), ()) as fd:
        raw = read_bounded(fd, "boot_id")
    return UUID(raw.decode("ascii").strip())


def collect_kernel(expected: ScopeExpectation, manager: UserManagerObservation) -> KernelScopeFacts:
    """Collect/recheck held identities; a to_thread timeout cannot kill a blocked read thread."""
    self_path = _self_path()
    observed, boot, uid = _mount_observation(), _boot(), os.geteuid()
    mount_id = observed.mount_id
    require_user_manager(manager, uid)
    # Hold root through group IO; same-device namespace/path splices must still deny.
    with (
        open_directory(Path("/sys/fs/cgroup"), ()) as mount_fd,
        open_directory(Path("/sys/fs/cgroup"), cgroup_components(expected.cgroup_path)) as fd,
    ):
        from nexus.builder.contained_observer_io import _fd_mount_id

        mount = os.fstat(mount_fd)
        group = os.fstat(fd)
        if (
            group.st_uid != uid
            or expected.uid != uid
            or _fd_mount_id(fd) != mount_id
            or _fd_mount_id(mount_fd) != mount_id
        ):
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
            if (current.st_dev, current.st_ino, current.st_uid, _fd_mount_id(fresh)) != (
                group.st_dev,
                group.st_ino,
                uid,
                mount_id,
            ):
                raise ValueError("Scope directory was replaced during collection")
        with open_directory(Path("/sys/fs/cgroup"), ()) as fresh_mount:
            current_mount = os.fstat(fresh_mount)
            after = _mount_observation()
            if (
                (current_mount.st_dev, current_mount.st_ino) != (mount.st_dev, mount.st_ino)
                or _signature(mount_fd) != (mount.st_dev, mount.st_ino, mount.st_uid)
                or _fd_mount_id(fresh_mount) != mount_id
                or _fd_mount_id(mount_fd) != mount_id
                or (after.mount_id, after.namespace_dev, after.namespace_inode)
                != (mount_id, observed.namespace_dev, observed.namespace_inode)
                or (os.geteuid(), _boot(), _self_path()) != (uid, boot, self_path)
                or _signature(fd) != (group.st_dev, group.st_ino, uid)
                or _fd_mount_id(fd) != mount_id
            ):
                raise ValueError("Scope mount was replaced during collection")
        with open_directory(
            Path("/sys/fs/cgroup"), cgroup_components(expected.cgroup_path)
        ) as visible_group:
            if (_signature(visible_group), _fd_mount_id(visible_group)) != (
                (group.st_dev, group.st_ino, uid),
                mount_id,
            ):
                raise ValueError("Scope directory was replaced after final mount observation")
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
        # Checked exact 261.2-1/262-1 user contexts can lack the marker; preserve actual ENODATA.
        return "absent_user_manager"
    if value != b"1":
        raise ValueError("Scope actual delegation marker is malformed or false")
    return "present_1"

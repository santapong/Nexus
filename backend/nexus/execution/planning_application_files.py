"""Bounded private operator configuration acquisition, separate from authority or credentials."""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from nexus.company.management.planning_native_facts import require_time
from nexus.execution.planning_application_config import (
    MAX_PLANNING_CONFIG,
    PlanningApplicationConfig,
    parse_planning_config,
)


def _signature(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_uid,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _parent_signature(value: os.stat_result) -> tuple[int, ...]:
    return value.st_dev, value.st_ino, value.st_uid, value.st_mode


@dataclass(frozen=True, slots=True)
class PlanningConfigSnapshot:
    """Descriptive original file identity; it cannot provide native read/effect permission."""

    value: PlanningApplicationConfig
    path: Path
    sha256: str
    signature: tuple[int, ...]
    parent_signature: tuple[int, ...]

    def require_current(self, *, end_us: int) -> None:
        """Startup may reject a changed file; it never refreshes the accepted configuration."""
        if load_planning_config(self.path, self.sha256, end_us=end_us) != self:
            raise ValueError("Planning original configuration changed")


@contextmanager
def _owned_descriptor(descriptor: int) -> Iterator[int]:
    """Retain an original read failure when closing the actual owned FD also fails."""
    try:
        yield descriptor
    except BaseException as first:
        try:
            os.close(descriptor)
        except BaseException as secondary:
            first.__dict__["_nexus_planning_secondary"] = type(secondary).__name__
        raise
    else:
        os.close(descriptor)


def _read_owned(
    path: Path,
    *,
    end_us: int,
    directory_fd: int | None = None,
) -> tuple[bytes, tuple[int, ...]]:
    descriptor = os.open(
        path.name if directory_fd is not None else path,
        os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
        dir_fd=directory_fd,
    )
    with _owned_descriptor(descriptor):
        require_time(end_us)
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_uid != os.geteuid()
            or before.st_nlink != 1
            or not 0 < before.st_size <= MAX_PLANNING_CONFIG
        ):
            raise ValueError("Planning private ordinary configuration is unavailable")
        chunks: list[bytes] = []
        size = 0
        while True:
            require_time(end_us)
            raw = os.read(descriptor, min(4096, MAX_PLANNING_CONFIG + 1 - size))
            if not raw:
                break
            chunks.append(raw)
            size += len(raw)
            if size > MAX_PLANNING_CONFIG:
                raise ValueError("Planning configuration exceeds its bound")
        if size != before.st_size or _signature(os.fstat(descriptor)) != _signature(before):
            raise ValueError("Planning configuration changed during acquisition")
        require_time(end_us)
        result = b"".join(chunks), _signature(before)
    require_time(end_us)
    return result


def load_planning_config(
    path: Path, expected_sha256: str, *, end_us: int
) -> PlanningConfigSnapshot:
    """Synchronous bounded operator startup only; serving requests does not reread this file."""
    require_time(end_us)
    if not path.is_absolute() or path.resolve() != path or len(str(path)) > 4096:
        raise ValueError("Planning exact configuration path is unavailable")
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    with _owned_descriptor(directory):
        parent = os.fstat(directory)
        if (
            not stat.S_ISDIR(parent.st_mode)
            or stat.S_IMODE(parent.st_mode) != 0o700
            or parent.st_uid != os.geteuid()
        ):
            raise ValueError("Planning private configuration directory is unavailable")
        raw, signature = _read_owned(path, end_us=end_us, directory_fd=directory)
        value = parse_planning_config(raw, expected_sha256)
        if (
            _signature(os.stat(path.name, dir_fd=directory, follow_symlinks=False)) != signature
            or _signature(path.stat(follow_symlinks=False)) != signature
            or _parent_signature(os.fstat(directory)) != _parent_signature(parent)
            or _parent_signature(path.parent.stat(follow_symlinks=False))
            != _parent_signature(parent)
        ):
            raise ValueError("Planning configuration namespace changed")
    require_time(end_us)
    return PlanningConfigSnapshot(
        value, path, expected_sha256, signature, _parent_signature(parent)
    )

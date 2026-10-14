"""Bounded nofollow operator file reads and synchronous immutable namespace/content pin checks."""

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from nexus.company.notifications.worker_contracts import NotificationWorkerRegistrationFile

MAX_WORKER_CONFIG_BYTES = 65_536
_UNAVAILABLE = "Notification worker configuration is unavailable"


class WorkerConfigurationError(ValueError):
    """Constant safe configuration failure; no path, registration data or private text."""


@dataclass(frozen=True, slots=True)
class WorkerRegistrationSnapshot:
    """Process-only file identity observation; no permission follows from decoded pins."""

    value: NotificationWorkerRegistrationFile
    sha256: str
    device: int
    inode: int
    modified_ns: int
    changed_ns: int
    byte_length: int


def _unique_members(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise WorkerConfigurationError(_UNAVAILABLE)
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise WorkerConfigurationError(_UNAVAILABLE)


def _stamp(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _require_regular(info: os.stat_result) -> None:
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_uid != os.geteuid()
        or info.st_nlink != 1
        or not 1 <= info.st_size <= MAX_WORKER_CONFIG_BYTES
    ):
        raise WorkerConfigurationError(_UNAVAILABLE)


def _read_owned_file(path: Path) -> tuple[bytes, os.stat_result]:
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        _require_regular(info)
        raw = os.read(fd, MAX_WORKER_CONFIG_BYTES + 1)
        after = os.fstat(fd)
    finally:
        os.close(fd)
    visible = os.stat(path, follow_symlinks=False)
    _require_regular(after)
    _require_regular(visible)
    if len(raw) != info.st_size or _stamp(info) != _stamp(after) or _stamp(info) != _stamp(visible):
        raise WorkerConfigurationError(_UNAVAILABLE)
    return raw, info


class FileNotificationWorkerRegistration:
    """An explicit operator path; construction performs no filesystem read or setup."""

    def __init__(self, path: Path) -> None:
        if not path.is_absolute():
            raise WorkerConfigurationError(_UNAVAILABLE)
        self._path = path

    def snapshot(self) -> WorkerRegistrationSnapshot:
        """Decode the complete ordinary owned0600 file after exact bounds/namespace checks."""
        try:
            raw, info = _read_owned_file(self._path)
            json.loads(raw, object_pairs_hook=_unique_members, parse_constant=_reject_constant)
            value = NotificationWorkerRegistrationFile.model_validate_json(raw)
            return WorkerRegistrationSnapshot(
                value,
                hashlib.sha256(raw).hexdigest(),
                info.st_dev,
                info.st_ino,
                info.st_mtime_ns,
                info.st_ctime_ns,
                len(raw),
            )
        except (OSError, ValueError, RecursionError):
            raise WorkerConfigurationError(_UNAVAILABLE) from None

    def require_current(self, snapshot: WorkerRegistrationSnapshot) -> None:
        """Final synchronous exact file/declaration check; never refresh registration dates."""
        if not isinstance(snapshot, WorkerRegistrationSnapshot) or self.snapshot() != snapshot:
            raise WorkerConfigurationError(_UNAVAILABLE)

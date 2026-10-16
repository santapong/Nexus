"""Private C configuration bytes through the existing qualified original FD/namespace checks."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from nexus.company.management.planning_native_facts import require_time
from nexus.execution.coding_application_config import CodingApplicationConfig, parse_coding_config
from nexus.execution.planning_application_files import (
    _owned_descriptor,
    _parent_signature,
    _read_owned,
    _signature,
)


@dataclass(frozen=True, slots=True)
class CodingConfigSnapshot:
    value: CodingApplicationConfig
    path: Path
    sha256: str
    signature: tuple[int, ...]
    parent_signature: tuple[int, ...]

    def require_current(self, *, end_us: int) -> None:
        if load_coding_config(self.path, self.sha256, end_us=end_us) != self:
            raise ValueError("Original coding configuration changed")


def load_coding_config(path: Path, expected_sha256: str, *, end_us: int) -> CodingConfigSnapshot:
    """Synchronous bounded operator startup only; serving requests does not reread this file."""
    require_time(end_us)
    if not path.is_absolute() or path.resolve() != path or len(str(path)) > 4096:
        raise ValueError("Coding exact configuration path is unavailable")
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    with _owned_descriptor(directory):
        parent = os.fstat(directory)
        if (
            not stat.S_ISDIR(parent.st_mode)
            or stat.S_IMODE(parent.st_mode) != 0o700
            or parent.st_uid != os.geteuid()
        ):
            raise ValueError("Coding private configuration directory is unavailable")
        raw, signature = _read_owned(path, end_us=end_us, directory_fd=directory)
        value = parse_coding_config(raw, expected_sha256)
        if (
            _signature(os.stat(path.name, dir_fd=directory, follow_symlinks=False)) != signature
            or _signature(path.stat(follow_symlinks=False)) != signature
            or _parent_signature(os.fstat(directory)) != _parent_signature(parent)
            or _parent_signature(path.parent.stat(follow_symlinks=False))
            != _parent_signature(parent)
        ):
            raise ValueError("Coding configuration namespace changed")
    require_time(end_us)
    return CodingConfigSnapshot(value, path, expected_sha256, signature, _parent_signature(parent))

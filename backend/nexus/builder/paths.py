"""Anchored ordinary-file access never follows job-controlled symlinks or special files."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path, PurePosixPath


def relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        not value
        or len(value) > 512
        or path.is_absolute()
        or str(path) != value
        or any(part in {".", "..", ".git", ".ssh"} for part in path.parts)
        or "\\" in value
        or any(ord(char) < 32 for char in value)
    ):
        raise ValueError("Builder path must be an exact ordinary relative path")
    return path


def permitted_path(value: str, prefixes: tuple[str, ...]) -> bool:
    selected = relative_path(value)
    return any(
        selected == relative_path(prefix) or relative_path(prefix) in selected.parents
        for prefix in prefixes
    )


def open_regular(root: Path, value: str) -> int:
    """Caller owns root. Every traversal is relative to an opened no-follow directory FD."""
    path = relative_path(value)
    if not root.is_absolute() or root.resolve(strict=True) != root:
        raise ValueError("Builder artifact root is not an ordinary managed directory")
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    parent = os.open(root, flags | os.O_DIRECTORY)
    try:
        for part in path.parts[:-1]:
            child = os.open(part, flags | os.O_DIRECTORY, dir_fd=parent)
            os.close(parent)
            parent = child
        result = os.open(path.name, flags | os.O_NONBLOCK, dir_fd=parent)
        metadata = os.fstat(result)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            os.close(result)
            raise ValueError("Builder artifact must be one ordinary single-link file")
        return result
    finally:
        os.close(parent)


def bounded_digest(root: Path, value: str, max_bytes: int) -> tuple[str, int]:
    """Bound reads even if a hostile producer grows the file after fstat."""
    if max_bytes < 0:
        raise ValueError("Artifact bound is invalid")
    descriptor = open_regular(root, value)
    digest, size = hashlib.sha256(), 0
    try:
        while raw := os.read(descriptor, min(65536, max_bytes - size + 1)):
            size += len(raw)
            if size > max_bytes:
                raise ValueError("Builder artifact exceeds its byte bound")
            digest.update(raw)
        return digest.hexdigest(), size
    finally:
        os.close(descriptor)

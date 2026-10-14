"""Exact bounded protected text patches modify only an ordinary private post snapshot."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from nexus.builder.patch_text import MAX_PATCH_BYTES, MAX_PATCHED_FILE, TextPatch, apply_text
from nexus.builder.patch_text import parse_patch as parse_patch
from nexus.builder.snapshot import parent_descriptor, source_path
from nexus.builder.source_guard import BuilderSourceGuard


async def load_protected_patch(guard: BuilderSourceGuard) -> bytes | None:
    reference = guard.spec.protected_patch
    if reference is None:
        return None
    raw = bytearray()
    while len(raw) < reference.byte_length:
        row = await guard.artifacts.bounded_artifact(
            guard.scope(),
            guard.identity,
            reference.artifact_revision_id,
            start_byte=len(raw),
            max_bytes=16384,
            include_history=False,
        )
        if (
            row.artifact != reference
            or row.source_state != "current"
            or row.span.start_byte != len(raw)
        ):
            raise ValueError("Builder patch artifact changed during bounded read")
        raw.extend(row.text.encode())
        if len(raw) > MAX_PATCH_BYTES:
            raise ValueError("Builder protected patch exceeds its complete bound")
    if len(raw) != reference.byte_length or hashlib.sha256(raw).hexdigest() != reference.sha256:
        raise ValueError("Builder exact protected patch bytes differ")
    return bytes(raw)


def apply_patch(root: Path, patches: tuple[TextPatch, ...]) -> None:
    for patch in patches:
        path = source_path(patch.path)
        base = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            parent = (
                parent_descriptor(base, path.parts[:-1])
                if patch.operation == "create"
                else _existing_parent(base, path.parts[:-1])
            )
        finally:
            os.close(base)
        try:
            if patch.operation == "create":
                updated = apply_text(b"", patch)
                fd = os.open(
                    path.name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=parent,
                )
                with os.fdopen(fd, "wb") as stream:
                    stream.write(updated)
                    stream.flush()
                    os.fsync(stream.fileno())
                continue
            fd = os.open(path.name, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            with os.fdopen(fd, "r+b") as stream:
                metadata = os.fstat(stream.fileno())
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                    raise ValueError("Builder patch target is not one ordinary file")
                original = stream.read(MAX_PATCHED_FILE + 1)
                if len(original) > MAX_PATCHED_FILE:
                    raise ValueError("Builder patch input exceeds its bound")
                updated = apply_text(original, patch)
                if patch.operation == "delete":
                    if updated:
                        raise ValueError("Builder delete patch does not remove the complete file")
                    os.unlink(path.name, dir_fd=parent)
                    continue
                stream.seek(0)
                stream.write(updated)
                stream.truncate()
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            os.close(parent)


def _existing_parent(root: int, parts: tuple[str, ...]) -> int:
    parent = os.dup(root)
    try:
        for part in parts:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = child
        return parent
    except BaseException:
        os.close(parent)
        raise

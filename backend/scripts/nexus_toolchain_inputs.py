"""Explicit metadata-only Nexus toolchain inspection; no package/image/runtime activation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from pathlib import Path

from nexus.builder.nexus_public_inputs import offline_preparation_commands, validate_public_inputs
from nexus.builder.nexus_recipe import (
    REQUIRED_SOURCE_PATHS,
    NexusToolchainManifest,
    manifest_sha256,
)


def _signature(value: os.stat_result) -> tuple[int, ...]:
    """Stable physical identity; an ordinary read may legitimately advance access time."""
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_gid,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def bounded_read(path: Path, limit: int) -> bytes:
    """Read only explicitly selected ordinary metadata with unchanged visible/FD identity."""
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise ValueError("Nexus metadata requires an ordinary absolute selected path")
    first = path.lstat()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or not 0 < opened.st_size <= limit
        ):
            raise ValueError("Nexus selected metadata exceeds its ordinary byte bound")
        original = _signature(first)
        if _signature(opened) != original:
            raise ValueError("Nexus selected metadata identity changed before read")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(limit + 1)
        if (
            _signature(os.fstat(fd)) != original
            or _signature(path.lstat()) != original
            or len(raw) != first.st_size
        ):
            raise ValueError("Nexus selected metadata identity changed")
        return raw
    finally:
        os.close(fd)


def inspect_inputs(manifest: Path, expected_sha256: str, source: Path, output: Path) -> None:
    """Save a descriptive preparation plan; even complete metadata never enables execution."""
    raw = bounded_read(manifest, 262144)
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("Nexus operator manifest bytes differ from the explicit hash")
    value = NexusToolchainManifest.model_validate_json(raw)
    if manifest_sha256(value) != expected_sha256:
        raise ValueError("Nexus operator manifest requires exact canonical wire bytes")
    files = tuple(bounded_read(source / path, 2_097_152) for path in REQUIRED_SOURCE_PATHS)
    validate_public_inputs(value.inputs, *files[:4])
    for row, content in zip(value.source_files, files, strict=True):
        if (row.sha256, row.byte_length) != (hashlib.sha256(content).hexdigest(), len(content)):
            raise ValueError("Nexus operator source differs from frozen critical inputs")
    if (
        output.parent.resolve(strict=True) != output.parent
        or stat.S_IMODE(output.parent.stat().st_mode) != 0o700
    ):
        raise ValueError("Nexus metadata output needs a private ordinary parent")
    payload = json.dumps(
        {
            "schema_version": "nexus.builder.input-description.v1",
            "manifest_sha256": expected_sha256,
            "execution_permitted": False,
            "qualification": "not_executed",
            "offline_preparation_argv": offline_preparation_commands(value.inputs),
        },
        sort_keys=True,
    ).encode()
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(payload)


def main() -> None:
    """Only explicit source/hash/metadata output options; there is no executable subcommand."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    inspect_inputs(args.manifest, args.manifest_sha256, args.source, args.output)


if __name__ == "__main__":
    main()

"""Bounded ordinary public input reads are independent from private source authority."""

from __future__ import annotations

import base64
import hashlib
import os
import stat
from pathlib import Path

from nexus.builder.node_contracts import NodeRuntimeInputs
from nexus.builder.public_package_contracts import PublicPackageManifest


def managed_path(path: Path) -> None:
    if (
        not path.is_absolute()
        or path.resolve(strict=True) != path
        or str(path).startswith(("/home/", "/root/"))
        or any(char in str(path) for char in ":,\n\r\x00")
    ):
        raise ValueError("Native Node inputs need ordinary server paths outside owner homes")
    info = path.lstat()
    if info.st_uid != os.getuid() or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
        raise ValueError("Native Node server input ownership/type differs")


def file_digests(path: Path, maximum: int) -> tuple[str, str]:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    first, second = hashlib.sha256(), hashlib.sha512()
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= maximum:
            raise ValueError("Native Node public archive/manifest exceeds ordinary byte bounds")
        remaining = maximum
        while raw := stream.read(min(65536, remaining + 1)):
            remaining -= len(raw)
            if remaining < 0:
                raise ValueError("Native Node public input grew beyond its byte bound")
            first.update(raw)
            second.update(raw)
    return first.hexdigest(), "sha512-" + base64.b64encode(second.digest()).decode()


def require_input_files(pins: NodeRuntimeInputs, pnpm: Path, cache: Path, manifest: Path) -> None:
    tool_sha, tool_sri = file_digests(pnpm, 33_554_432)
    cache_sha, _ = file_digests(cache, 2_147_483_648)
    manifest_sha, _ = file_digests(manifest, 2_097_152)
    if (
        tool_sha != pins.pnpm_archive_sha256
        or tool_sri != pins.pnpm_integrity
        or cache_sha != pins.cache_archive_sha256
        or manifest_sha != pins.cache_manifest_sha256
    ):
        raise ValueError("Native Node input archive/manifest bytes changed")
    descriptor = os.open(manifest, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        raw = stream.read(2_097_153)
    if len(raw) > 2_097_152 or hashlib.sha256(raw).hexdigest() != pins.cache_manifest_sha256:
        raise ValueError("Native Node manifest changed during bounded qualification")
    value = PublicPackageManifest.model_validate_json(raw)
    if value.lock_sha256 != pins.lock_sha256:
        raise ValueError("Native Node manifest differs from the exact committed lock")

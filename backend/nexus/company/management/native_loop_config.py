"""Bounded immutable operator files restore selectors, never signed identity or permissions."""

import asyncio
import os
import stat
from pathlib import Path

from nexus.company.management.native_loop_contracts import NativeOperatingRegistration

MAX_CONFIGURATION_BYTES = 65536


def _read(path: Path) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_CONFIGURATION_BYTES:
            raise ValueError("Native operating configuration is unavailable or oversized")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(MAX_CONFIGURATION_BYTES + 1)
        if len(raw) > MAX_CONFIGURATION_BYTES:
            raise ValueError("Native operating configuration is oversized")
        return raw
    finally:
        os.close(descriptor)


def _save(path: Path, raw: bytes) -> None:
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        if _read(path) != raw:
            raise ValueError("Native operating configuration is immutable") from None
        return
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(descriptor)
    finally:
        os.close(descriptor)


async def save_native_operating_registration(
    path: Path, registration: NativeOperatingRegistration
) -> None:
    """Save one exact server registration; existing changed bytes are never overwritten."""
    value = NativeOperatingRegistration.model_validate_json(registration.model_dump_json())
    raw = (value.model_dump_json() + "\n").encode("utf-8")
    if len(raw) > MAX_CONFIGURATION_BYTES:
        raise ValueError("Native operating configuration is oversized")
    try:
        await asyncio.to_thread(_save, path, raw)
    except OSError as exc:
        raise ValueError("Native operating configuration file is unavailable") from exc


async def load_native_operating_registration(path: Path) -> NativeOperatingRegistration:
    """Restore strict operator selectors; constructor/native authentication still applies."""
    try:
        raw = await asyncio.to_thread(_read, path)
    except OSError as exc:
        raise ValueError("Native operating configuration file is unavailable") from exc
    return NativeOperatingRegistration.model_validate_json(raw)

"""Private write-once host sidecars reject pending, conflicting and replaced evidence."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import stat
from pathlib import Path

from nexus.builder.contained_contracts import ContainedEvidenceIdentity
from nexus.builder.contained_evidence_types import ContainedObservation, ContainmentRef
from nexus.builder.snapshot import private_directory


class ContainmentEvidenceStore:
    """No sandbox mount or caller-selected filename; original issuance derives the private name."""

    def __init__(self, private_root: Path) -> None:
        if not private_root.is_absolute():
            raise ValueError("Containment store root must be an owned absolute directory")
        private_root.mkdir(mode=0o700, parents=False, exist_ok=True)
        fd = _directory(private_root)
        original = os.fstat(fd)
        self._root_identity = (original.st_dev, original.st_ino)
        os.close(fd)
        self.root = private_root

    @staticmethod
    def filename(identity: ContainedEvidenceIdentity) -> str:
        """Current replay lease fence is not an input to this deterministic original identity."""
        value = ContainedEvidenceIdentity.model_validate(identity.model_dump())
        raw = json.dumps(
            value.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()
        return (
            f"{value.company_id.hex}-{value.action_id.hex}-{hashlib.sha256(raw).hexdigest()}.json"
        )

    async def save_once(self, observation: ContainedObservation) -> ContainmentRef:
        """Exclusive pending inode and no-replace link preserve conflicting original evidence."""
        value = ContainedObservation.model_validate(observation.model_dump())
        raw = value.model_dump_json().encode()
        if len(raw) > 65536:
            raise ValueError("Containment sidecar exceeds65536bytes")
        reference = ContainmentRef(
            identity=value.identity, sha256=hashlib.sha256(raw).hexdigest(), byte_length=len(raw)
        )
        await asyncio.to_thread(self._save, raw, reference)
        return reference

    async def load_exact(
        self,
        reference: ContainmentRef,
        expected_identity: ContainedEvidenceIdentity,
    ) -> ContainedObservation:
        """Caller hash/DTO alone does not prove actual bytes or original issuance binding."""
        reference = ContainmentRef.model_validate(reference.model_dump())
        if reference.identity != expected_identity:
            raise ValueError("Containment reference binds another original issuance")
        raw = await asyncio.to_thread(self._read, self.filename(expected_identity))
        if len(raw) != reference.byte_length or hashlib.sha256(raw).hexdigest() != reference.sha256:
            raise ValueError("Containment actual sidecar bytes differ from the protected reference")
        json.loads(raw, object_pairs_hook=_unique_pairs)
        value = ContainedObservation.model_validate_json(raw)
        if value.identity != expected_identity:
            raise ValueError("Stored sidecar original identity differs")
        return value

    def _read(self, name: str) -> bytes:
        directory = _directory(self.root, self._root_identity)
        try:
            return _read_file(directory, name)
        finally:
            os.close(directory)

    def _save(self, raw: bytes, reference: ContainmentRef) -> None:
        directory = _directory(self.root, self._root_identity)
        name, pending = (
            self.filename(reference.identity),
            self.filename(reference.identity) + ".pending",
        )
        try:
            if _exists(directory, pending):
                raise FileExistsError("Containment pending evidence requires explicit recovery")
            if _exists(directory, name):
                if _read_file(directory, name) != raw:
                    raise ValueError("Containment original sidecar is immutable")
                return
            _publish(directory, pending, name, raw)
        finally:
            os.close(directory)


def _directory(root: Path, expected: tuple[int, int] | None = None) -> int:
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        private_directory(fd)
        current = os.fstat(fd)
        if expected is not None and (current.st_dev, current.st_ino) != expected:
            raise ValueError("Containment store root inode was replaced")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _exists(directory: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


def _read_file(directory: int, name: str) -> bytes:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=directory)
    try:
        original = os.fstat(fd)
        _require_file(original)
        raw = bytearray()
        while part := os.read(fd, min(4096, 65537 - len(raw))):
            raw.extend(part)
            if len(raw) > 65536:
                raise ValueError("Containment sidecar exceeds complete byte cap")
        current = os.stat(name, dir_fd=directory, follow_symlinks=False)
        if (current.st_dev, current.st_ino, current.st_size) != (
            original.st_dev,
            original.st_ino,
            len(raw),
        ) or os.fstat(fd).st_nlink != 1:
            raise ValueError("Containment sidecar was replaced or linked during read")
        return bytes(raw)
    finally:
        os.close(fd)


def _require_file(value: os.stat_result) -> None:
    if (
        not stat.S_ISREG(value.st_mode)
        or value.st_uid != os.geteuid()
        or stat.S_IMODE(value.st_mode) != 0o600
        or value.st_nlink != 1
    ):
        raise ValueError("Containment sidecar is not an owned private single-link regular file")


def _publish(directory: int, pending: str, name: str, raw: bytes) -> None:
    fd = os.open(
        pending,
        os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600,
        dir_fd=directory,
    )
    try:
        original = os.fstat(fd)
        _require_file(original)
        body = memoryview(raw)
        while body:
            written = os.write(fd, body)
            if written <= 0:
                raise OSError("Containment sidecar write made no progress")
            body = body[written:]
        os.fsync(fd)
        _require_file(os.fstat(fd))
        os.lseek(fd, 0, os.SEEK_SET)
        observed = bytearray()
        while part := os.read(fd, min(4096, 65537 - len(observed))):
            observed.extend(part)
            if len(observed) > 65536:
                raise ValueError("Containment pending bytes exceed the fixed cap")
        if (
            len(observed) != len(raw)
            or hashlib.sha256(observed).digest() != hashlib.sha256(raw).digest()
        ):
            raise ValueError("Containment pending actual written bytes differ")
        current = os.stat(pending, dir_fd=directory, follow_symlinks=False)
        if (current.st_dev, current.st_ino) != (original.st_dev, original.st_ino):
            raise ValueError("Containment pending inode replaced before publication")
        os.link(pending, name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
        final = os.stat(name, dir_fd=directory, follow_symlinks=False)
        if (final.st_dev, final.st_ino) != (original.st_dev, original.st_ino):
            raise ValueError("Containment final inode differs from the owned pending inode")
        os.unlink(pending, dir_fd=directory)
        os.fsync(directory)
    finally:
        os.close(fd)


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    values: dict[str, object] = {}
    for key, value in pairs:
        if key in values:
            raise ValueError("Containment sidecar JSON repeats a field")
        values[key] = value
    return values

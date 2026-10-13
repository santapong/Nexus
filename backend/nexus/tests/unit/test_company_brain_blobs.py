"""Protected company-scoped raw bytes precede committed Brain artifact references."""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import UUID

import pytest

from nexus.company.brain.blob_store import BlobConflictError, ProtectedBlobStore
from nexus.company.brain.sources import ArtifactRevisionRef

COMPANY = UUID(int=1)


def reference(data: bytes, *, company: UUID = COMPANY) -> ArtifactRevisionRef:
    return ArtifactRevisionRef(
        company_id=company,
        artifact_id=UUID(int=2),
        artifact_revision_id=UUID(int=3),
        revision="r1",
        sha256=hashlib.sha256(data).hexdigest(),
        byte_length=len(data),
    )


async def test_raw_blob_roundtrip_is_idempotent_without_global_hash_lookup(tmp_path: Path) -> None:
    store = ProtectedBlobStore(tmp_path, storage_symbol="fixture.blobs.v1")
    raw = "exact\r\nไทย 🚀\n".encode()
    artifact = reference(raw)
    await store.save(artifact, raw)
    await store.save(artifact, raw)
    assert await store.read(artifact) == raw
    other = reference(raw, company=UUID(int=4))
    with pytest.raises(FileNotFoundError):
        await store.read(other)
    await store.save(other, raw)
    assert await store.read(other) == raw


async def test_changed_same_revision_bytes_conflict_and_leave_original_intact(
    tmp_path: Path,
) -> None:
    store = ProtectedBlobStore(tmp_path, storage_symbol="fixture.blobs.v1")
    original, changed = b"initial", b"changed"
    await store.save(reference(original), original)
    with pytest.raises(BlobConflictError):
        await store.save(reference(changed), changed)
    assert await store.read(reference(original)) == original


async def test_hash_or_length_mismatch_cannot_create_an_artifact_blob(tmp_path: Path) -> None:
    store = ProtectedBlobStore(tmp_path, storage_symbol="fixture.blobs.v1")
    with pytest.raises(ValueError):
        await store.save(reference(b"safe"), b"unsafe")
    with pytest.raises(FileNotFoundError):
        await store.read(reference(b"safe"))


async def test_corrupted_stored_bytes_and_symlink_roots_fail_closed(tmp_path: Path) -> None:
    store = ProtectedBlobStore(tmp_path, storage_symbol="fixture.blobs.v1")
    artifact = reference(b"safe")
    await store.save(artifact, b"safe")
    file = next(tmp_path.rglob("*.blob"))
    file.chmod(0o600)
    file.write_bytes(b"tampered")
    with pytest.raises(ValueError):
        await store.read(artifact)
    link = tmp_path / "escape"
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        ProtectedBlobStore(link, storage_symbol="fixture.blobs.v1")

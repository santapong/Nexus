"""Protected byte preparation is not metadata success, a receipt or an execution permit."""

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest

from nexus.company.brain.blob_store import BlobConflictError, ProtectedBlobStore
from nexus.company.management.generated_artifact_blob import prepare_generated_blob
from nexus.tests.unit.test_company_generated_artifact_contracts import payload


async def test_pending_protected_blob_exact_replay_preserves_bytes_and_rejects_changed_output(
    tmp_path: Path,
) -> None:
    prepared = payload()
    action_id = uuid4()
    blobs = ProtectedBlobStore(tmp_path, storage_symbol="test.pending.generated.v1")
    pending = await prepare_generated_blob(blobs, prepared, action_id)
    assert await blobs.read(pending) == prepared.raw_bytes
    assert await prepare_generated_blob(blobs, prepared, action_id) == pending
    changed = prepared.model_copy(
        update={
            "raw_bytes": b"changed output",
            "output_sha256": hashlib.sha256(b"changed output").hexdigest(),
        }
    )
    with pytest.raises(BlobConflictError):
        await prepare_generated_blob(blobs, changed, action_id)
    assert await blobs.read(pending) == prepared.raw_bytes
    # No native DB/receipt/cost/acceptance object was created by preparation.
    assert not hasattr(pending, "permit_external_call") and not hasattr(pending, "verdict")

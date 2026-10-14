"""Read exact registered immutable namespaces; no caller paths or native reference rewrite."""

import hashlib
from collections.abc import Mapping
from pathlib import Path

from nexus.company.brain.blob_store import BlobReader
from nexus.operations.backup_contracts import BackupArtifact
from nexus.operations.backup_inventory import ArtifactLocation


def namespace_directory(symbol: str) -> str:
    return "namespace-" + hashlib.sha256(symbol.encode()).hexdigest()


def location_path(location: ArtifactLocation) -> str:
    reference = location.reference
    return "/".join(
        (
            namespace_directory(location.storage_symbol),
            str(reference.company_id),
            str(reference.artifact_id),
            f"{reference.artifact_revision_id}.blob",
        )
    )


async def collect_artifacts(
    locations: tuple[ArtifactLocation, ...], readers: Mapping[str, BlobReader], *, limit: int
) -> tuple[BackupArtifact, ...]:
    result, total = [], 0
    for location in locations:
        reader = readers.get(location.storage_symbol)
        if reader is None:
            raise ValueError("Backup registered artifact namespace is unavailable")
        raw = await reader.read(location.reference)
        total += len(raw)
        if (
            total > limit
            or len(raw) != location.reference.byte_length
            or hashlib.sha256(raw).hexdigest() != location.reference.sha256
        ):
            raise ValueError("Backup artifact bytes differ from native inventory")
        result.append(BackupArtifact(relative_path=location_path(location), data=raw))
    return tuple(result)


def restored_namespace(root: Path, symbol: str) -> Path:
    """Operator config maps the same native symbol to verified new files, never new DB refs."""
    return root / "artifacts" / namespace_directory(symbol)

"""Protected byte preparation outside CompanyControl; a pending blob is never native success."""

from uuid import UUID

from nexus.company.brain.blob_store import BrainBlobStore
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.generated_artifact_contracts import GeneratedArtifactPayload
from nexus.company.management.generated_artifact_identity import generated_reference


async def prepare_generated_blob(
    blobs: BrainBlobStore, prepared: GeneratedArtifactPayload, action_id: UUID
) -> ArtifactRevisionRef:
    """Save only exact protected bytes; caller separately proves fresh native publication gates.

    Returning a ref proves neither committed metadata nor a receipt/accepted work.
    An interruption here leaves pending bytes whose existence grants no replay or
    external effect permission. The publisher owns task/trace logging and scope.
    """
    prepared = GeneratedArtifactPayload.model_validate_json(prepared.model_dump_json())
    reference = generated_reference(prepared, action_id)
    await blobs.save(reference, prepared.raw_bytes)
    return reference

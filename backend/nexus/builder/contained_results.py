"""Immutable result/ref bindings require actual sidecar bytes; descriptions confer no authority."""

from nexus.builder.contained_contracts import ContainedEvidenceIdentity
from nexus.builder.contained_evidence_store import ContainmentEvidenceStore
from nexus.builder.contained_evidence_types import ContainedObservation
from nexus.builder.execution_contracts import BuilderRunResult
from nexus.builder.runtime_identity import RUNTIME_V2, RUNTIME_V2_METHOD_SHA256
from nexus.company.management.canonical import canonical_sha256


def base_result_sha256(result: BuilderRunResult) -> str:
    """Exclude only the optional reference, avoiding a hash cycle with immutable sidecar bytes."""
    return canonical_sha256(result.model_copy(update={"containment": None}))


def result_evidence_identity(
    result: BuilderRunResult, method_sha256: str
) -> ContainedEvidenceIdentity:
    """Use the original intent fence; a replacement recovery lease never changes evidence name."""
    return ContainedEvidenceIdentity(
        company_id=result.spec.job.company_id,
        action_id=result.spec.job.action_id,
        original_intent_fence=result.intent_fence,
        result_base_sha256=base_result_sha256(result),
        execution_method_sha256=method_sha256,
    )


async def require_contained_result(
    result: BuilderRunResult,
    store: ContainmentEvidenceStore,
    method_sha256: str,
) -> ContainedObservation:
    """Read actual complete original sidecar before allowing any v2 evidence interpretation."""
    result = BuilderRunResult.model_validate(result.model_dump())
    if result.spec.runtime_recipe != RUNTIME_V2 or result.containment is None:
        raise ValueError("Contained result requires explicit runtime v2 evidence")
    expected = result_evidence_identity(result, method_sha256)
    observation = await store.load_exact(result.containment, expected)
    if (
        observation.spec_sha256 != canonical_sha256(result.spec)
        or observation.proposal_sha256 != result.proposal_sha256
        or observation.selector_sha256 != RUNTIME_V2_METHOD_SHA256
        or observation.container.image_id != result.image_id
        or observation.container.container_name != result.container_name
        or (result.outcome != "outcome_unknown" and observation.status != "observed_contained")
    ):
        raise ValueError("Actual contained sidecar differs from protected result bindings")
    return observation

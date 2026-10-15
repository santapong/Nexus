"""Fresh publisher state consistency; unknown effects require separate reviewed recovery."""

from uuid import UUID

from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.execution.runtime_models import EffectIntent


def require_fresh_strategy_publication_state(
    effect: EffectIntent, *, exists: bool, output: ArtifactRevisionRef, action_id: UUID
) -> None:
    """Present artifact bytes cannot change a failed/unknown issued action into fresh success."""
    require_acceptance(effect.action_id == action_id and effect.company_id == output.company_id)
    if effect.state == "intent":
        require_acceptance(effect.receipt_json is None)
        return
    require_acceptance(exists and effect.state == "succeeded" and effect.receipt_json is not None)
    assert effect.receipt_json is not None
    receipt = ActionReceipt.model_validate_json(effect.receipt_json)
    require_acceptance(
        receipt.company_id == output.company_id
        and receipt.action_id == action_id
        and receipt.task_id == effect.task_id
        and receipt.trace_id == effect.trace_id
        and receipt.proposal_hash == effect.proposal_hash
        and receipt.outcome == "succeeded"
        and len(receipt.artifacts) == 1
        and (
            receipt.artifacts[0].company_id,
            receipt.artifacts[0].artifact_id,
            receipt.artifacts[0].revision,
            receipt.artifacts[0].sha256,
        )
        == (output.company_id, output.artifact_id, output.revision, output.sha256)
    )

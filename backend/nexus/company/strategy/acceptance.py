"""Recomputed acceptance descriptions; only a current native store may persist them."""

import hashlib
import json
from datetime import datetime
from uuid import uuid5

from nexus.company.management.acceptance import ProtectedCheckProof, WorkAcceptance
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.generated_artifact_contracts import GeneratedArtifactInputs
from nexus.company.strategy.artifact_contracts import StrategyCheckParameters
from nexus.company.strategy.artifact_identity import strategy_artifact_id
from nexus.company.strategy.check_output import (
    require_strategy_check_bytes,
    strategy_check_production_snapshot,
)
from nexus.company.strategy.contracts import StrategyCheckInput
from nexus.company.strategy.verifier_receipt import StrategyVerifierReceipt
from nexus.harness.canonical import action_hash


def build_strategy_acceptance(
    command: StrategyCheckInput,
    inputs: GeneratedArtifactInputs,
    verifier: StrategyVerifierReceipt,
    protected_bytes: bytes,
    recorded_at: datetime,
) -> WorkAcceptance:
    """Compare receipt pins with recomputed material; descriptions confer no native authority."""
    # This >50-line construction keeps the exact target/receipt/pins and resulting proof together.
    production = strategy_check_production_snapshot(command, inputs)
    pins, action, receipt = verifier.parameters, verifier.action, verifier.receipt
    require_acceptance(
        pins == StrategyCheckParameters.model_validate_json(json.dumps(action.parameters))
        and pins.author_action_id == command.target.action_id
        and pins.verification_target_sha256 == canonical_sha256(command.target)
        and pins.input_snapshot_sha256 == canonical_sha256(production)
        and pins.output_sha256 == hashlib.sha256(protected_bytes).hexdigest()
        and (action.company_id, action.actor_id, action.task_id, action.trace_id)
        == (
            command.company_id,
            command.target.verifier.actor_id,
            command.target.verifier.task_id,
            command.target.verifier.trace_id,
        )
        and receipt.action_id == action.action_id
        and receipt.company_id == action.company_id
        and receipt.task_id == action.task_id
        and receipt.trace_id == action.trace_id
        and receipt.proposal_hash == action_hash(action)
        and receipt.outcome == "succeeded"
        and action.tool == "company.cycle-artifact.check.v1"
        and action.tool_version == "v1"
        and verifier.protected_result.artifact_id
        == strategy_artifact_id(command.company_id, action.action_id)
        and len(receipt.artifacts) == 1
        and (
            receipt.artifacts[0].artifact_id,
            receipt.artifacts[0].revision,
            receipt.artifacts[0].sha256,
        )
        == (
            verifier.protected_result.artifact_id,
            verifier.protected_result.revision,
            verifier.protected_result.sha256,
        )
        and receipt.recorded_at <= recorded_at
    )
    result = require_strategy_check_bytes(
        command, inputs, verifier.protected_result, protected_bytes
    )
    target_hash = canonical_sha256(command.target)
    acceptance_id = uuid5(command.company_id, f"management.strategy-acceptance:{target_hash}")
    return WorkAcceptance(
        company_id=command.company_id,
        acceptance_id=acceptance_id,
        target=command.target,
        verdict=result.verdict,
        limitations=result.limitations,
        recorded_at=recorded_at,
        proofs=(
            ProtectedCheckProof(
                company_id=command.company_id,
                proof_id=uuid5(acceptance_id, verifier.protected_result.artifact_revision_id.hex),
                recipe=command.target.check_recipe,
                result_artifact=verifier.protected_result,
                target_sha256=target_hash,
            ),
        ),
    )

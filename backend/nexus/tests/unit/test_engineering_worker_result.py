"""Descriptive worker results cannot manufacture receipt/proof/phase completion bindings."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

import pytest

from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.engineering_worker_contracts import EngineeringSegmentResult


def result_values() -> dict[str, object]:
    """Synthetic exact IDs exercise wire shape only, never store authority."""
    command = SegmentCommand(
        company_id=UUID(int=1),
        task_id=UUID(int=2),
        trace_id=UUID(int=3),
        actor_id=UUID(int=4),
        workspace_id=UUID(int=5),
        run_id=UUID(int=6),
        action_id=UUID(int=7),
        segment_id=UUID(int=8),
    )
    return {
        "company_id": command.company_id,
        "command": command,
        "phase": "verifier",
        "workflow_name": "engineering.verify",
        "workflow_version": "v1",
        "status": "accepted",
        "receipt_id": UUID(int=10),
        "acceptance_id": UUID(int=11),
        "protected_proof": ArtifactRevisionRef(
            company_id=command.company_id,
            artifact_id=UUID(int=12),
            artifact_revision_id=UUID(int=13),
            revision="native-engineering-change-v1",
            sha256="a" * 64,
            byte_length=100,
        ),
        "billing": "unconfirmed",
        "observed_at": datetime.now(UTC),
    }


def test_accepted_describes_actual_ids_without_refunding_unknown_billing() -> None:
    value = EngineeringSegmentResult.model_validate(result_values())
    assert value.status == "accepted" and value.billing == "unconfirmed"
    assert value.command.workflow_id == str(value.workflow_id)
    assert "business_readiness_unproven" in value.limitations


@pytest.mark.parametrize("field", ["receipt_id", "acceptance_id", "protected_proof"])
def test_known_acceptance_requires_every_actual_evidence_identity(field: str) -> None:
    with pytest.raises(ValueError):
        EngineeringSegmentResult.model_validate({**result_values(), field: None})


@pytest.mark.parametrize(
    "change", ["author", "workflow", "company", "proof_company", "proof_recipe"]
)
def test_phase_workflow_company_and_recipe_splice_denied(change: str) -> None:
    values = result_values()
    if change == "author":
        values.update(phase="author", workflow_name="engineering.change")
    elif change == "workflow":
        values["workflow_name"] = "internal.report"
    elif change == "company":
        values["company_id"] = UUID(int=99)
    else:
        proof = values["protected_proof"]
        assert isinstance(proof, ArtifactRevisionRef)
        values["protected_proof"] = proof.model_copy(
            update={
                "company_id": UUID(int=99) if change == "proof_company" else UUID(int=1),
                "revision": "unsupported" if change == "proof_recipe" else proof.revision,
            }
        )
    with pytest.raises(ValueError):
        EngineeringSegmentResult.model_validate(values)


@pytest.mark.parametrize("status", ["outcome_unknown", "blocked"])
def test_unknown_or_blocked_cannot_carry_accepted_proof(status: str) -> None:
    with pytest.raises(ValueError):
        EngineeringSegmentResult.model_validate({**result_values(), "status": status})


def test_published_author_requires_receipt_and_carries_no_acceptance() -> None:
    values = {
        **result_values(),
        "phase": "author",
        "workflow_name": "engineering.change",
        "status": "published",
        "acceptance_id": None,
        "protected_proof": None,
    }
    assert EngineeringSegmentResult.model_validate(values).status == "published"
    with pytest.raises(ValueError):
        EngineeringSegmentResult.model_validate({**values, "receipt_id": None})


@pytest.mark.parametrize("status", ["accepted", "reject", "inconclusive"])
def test_verifier_verdict_always_carries_native_acceptance(status: str) -> None:
    assert (
        EngineeringSegmentResult.model_validate({**result_values(), "status": status}).status
        == status
    )


def test_resolved_factory_derives_status_from_actual_acceptance() -> None:
    # Keep this >50-line typed receipt/proof/target fixture and verdict/splice
    # assertions together so each result derives from the same synthetic records.
    from nexus.company.management.acceptance import ProtectedCheckProof, WorkAcceptance
    from nexus.company.management.canonical import canonical_sha256
    from nexus.execution.engineering_worker_contracts import accepted_segment_result
    from nexus.tests.engineering_check_support import check_input

    value = check_input()
    verifier = value.target.verifier
    command = SegmentCommand(
        company_id=value.company_id,
        task_id=verifier.task_id,
        trace_id=verifier.trace_id,
        actor_id=verifier.actor_id,
        workspace_id=verifier.workspace_id,
        run_id=verifier.run_id,
        action_id=value.verifier_receipt.action_id,
        segment_id=UUID(int=77),
    )
    proof = value.verifier_output.model_copy(update={"revision": "native-engineering-change-v1"})
    cases: tuple[tuple[Literal["pass", "reject", "inconclusive"], str], ...] = (
        ("pass", "accepted"),
        ("reject", "reject"),
        ("inconclusive", "inconclusive"),
    )
    for verdict, status in cases:
        acceptance = WorkAcceptance(
            company_id=value.company_id,
            acceptance_id=UUID(int=78),
            target=value.target,
            verdict=verdict,
            recorded_at=datetime.now(UTC),
            proofs=(
                ProtectedCheckProof(
                    company_id=value.company_id,
                    proof_id=UUID(int=79),
                    recipe=value.target.check_recipe,
                    result_artifact=proof,
                    target_sha256=canonical_sha256(value.target),
                ),
            ),
        )
        result = accepted_segment_result(
            command,
            value.verifier_receipt,
            acceptance,
            billing="unconfirmed",
            observed_at=datetime.now(UTC),
        )
        assert result.status == status and result.billing == "unconfirmed"
        with pytest.raises(ValueError):
            accepted_segment_result(
                command.model_copy(update={"run_id": UUID(int=99)}),
                value.verifier_receipt,
                acceptance,
                billing="unconfirmed",
                observed_at=datetime.now(UTC),
            )
        with pytest.raises(ValueError):
            accepted_segment_result(
                command,
                value.verifier_receipt.model_copy(update={"outcome": "failed"}),
                acceptance,
                billing="unconfirmed",
                observed_at=datetime.now(UTC),
            )

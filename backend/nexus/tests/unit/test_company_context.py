"""Source access and frozen fixture integrity; retrieval execution remains an M2 gate."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from nexus.company.contracts.knowledge import ArtifactRef, Claim, ContextBundle, Evidence
from nexus.company.contracts.results import VerificationResult
from nexus.tests.unit.test_company_foundation import ACTOR, COMPANY, NOW, TASK, TRACE


def context() -> ContextBundle:
    """Create authorized attachment/workspace evidence and one cited claim."""
    artifact = ArtifactRef(
        company_id=COMPANY,
        artifact_id=UUID(int=30),
        reference="fixture:R1",
        sha256="a" * 64,
        revision="1",
        allowed_principals=(ACTOR,),
    )
    evidence = Evidence(
        company_id=COMPANY,
        evidence_id=UUID(int=31),
        source=artifact,
        event_at=NOW,
        ingested_at=NOW,
        summary="Synthetic acceptance source",
    )
    claim = Claim(
        company_id=COMPANY,
        claim_id=UUID(int=32),
        kind="observation",
        text="Fixture fact",
        evidence_ids=(evidence.evidence_id,),
        allowed_principals=(ACTOR,),
    )
    return ContextBundle(
        company_id=COMPANY,
        task_id=TASK,
        trace_id=TRACE,
        principal_id=ACTOR,
        mandate_version="1",
        policy_version="1",
        budget_version="1",
        acceptance=("Cited evidence",),
        claims=(claim,),
        evidence=(evidence,),
        attachments=(artifact,),
        workspace_files=(artifact,),
        token_limit=1024,
    )


def test_context_keeps_both_attachment_and_workspace_references() -> None:
    bundle = context()
    assert bundle.attachments and bundle.workspace_files


@pytest.mark.parametrize("failure", ["foreign", "artifact_access", "claim_access", "citation"])
def test_context_rejects_foreign_inaccessible_or_uncited_material(failure: str) -> None:
    bundle = context()
    data = bundle.model_dump()
    if failure == "foreign":
        data["claims"][0]["company_id"] = UUID(int=99)
    elif failure == "artifact_access":
        data["attachments"][0]["allowed_principals"] = ()
    elif failure == "claim_access":
        data["claims"][0]["allowed_principals"] = ()
    else:
        data["claims"][0]["evidence_ids"] = (UUID(int=99),)
    with pytest.raises(ValidationError):
        ContextBundle.model_validate(data)


def test_hypothesis_is_allowed_but_cannot_claim_verified_outcome_without_proof() -> None:
    hypothesis = Claim(
        company_id=COMPANY, claim_id=UUID(int=40), kind="hypothesis", text="Candidate"
    )
    assert hypothesis.kind == "hypothesis"
    with pytest.raises(ValidationError):
        Claim(company_id=COMPANY, claim_id=UUID(int=40), kind="verified_outcome", text="Candidate")


def test_passing_verifier_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        VerificationResult(
            company_id=COMPANY,
            verification_id=UUID(int=41),
            action_id=UUID(int=42),
            verifier_id=ACTOR,
            verdict="pass",
            criterion_ids=("criterion-1",),
        )


def test_frozen_brain_pack_has_thirty_unique_cases_and_critical_permission_checks() -> None:
    path = Path(__file__).resolve().parents[1] / "fixtures/company_v1/brain_cases.json"
    pack = json.loads(path.read_text())
    assert len(pack["cases"]) == len({case["id"] for case in pack["cases"]}) == 30
    assert pack["threshold"]["minimum_passes"] == 27
    assert all(case["critical"] for case in pack["cases"] if case["category"] == "permissions")
    assert "Not run" in pack["evaluation_status"]


def test_pilot_checklist_preserves_internal_scope_and_candidate_commands() -> None:
    path = Path(__file__).resolve().parents[1] / "fixtures/company_v1/stockflow_readiness.json"
    pilot = json.loads(path.read_text())
    assert len({check["id"] for check in pilot["checks"]}) == 10
    assert pilot["exclude_uncommitted_changes"]
    assert not pilot["authority"]["customer_send"]
    assert not pilot["authority"]["production_deployment"]

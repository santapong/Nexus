"""Exact independent pass declaration for unit tests; never stored native acceptance."""

from uuid import UUID

from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.acceptance import (
    ProtectedCheckProof,
    VerificationSpec,
    WorkAcceptance,
)
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.plans import RunBinding
from nexus.company.notifications.contracts import CurrentWorkAcceptance
from nexus.tests.notification_rule_fixtures import COMPANY, NOW, OWNER, WORKSPACE


def binding(task: int, actor: UUID) -> RunBinding:
    return RunBinding(
        company_id=COMPANY,
        workspace_id=WORKSPACE,
        actor_id=actor,
        task_id=UUID(int=task),
        trace_id=UUID(int=task + 1),
        run_id=UUID(int=task + 2),
        workflow_name="fixture-report",
        workflow_version="fixture.v1",
        model_profile="offline-none",
        model_registry_version="none.v1",
    )


def declared_acceptance() -> CurrentWorkAcceptance:
    artifact = ArtifactRevisionRef(
        company_id=COMPANY,
        artifact_id=UUID(int=200),
        artifact_revision_id=UUID(int=201),
        revision="fixture-r1",
        sha256="d" * 64,
        byte_length=123,
    )
    target = VerificationSpec(
        company_id=COMPANY,
        author=binding(20, OWNER),
        verifier=binding(30, UUID(int=90)),
        action_id=UUID(int=40),
        proposal_sha256="a" * 64,
        receipt_id=UUID(int=41),
        receipt_sha256="b" * 64,
        work_snapshot_sha256="c" * 64,
        criterion_ids=("source-consistency",),
        artifacts=(artifact,),
        check_recipe="fixture-check.v1",
    )
    proof = ProtectedCheckProof(
        company_id=COMPANY,
        proof_id=UUID(int=202),
        recipe=target.check_recipe,
        result_artifact=artifact,
        target_sha256=canonical_sha256(target),
    )
    accepted = WorkAcceptance(
        company_id=COMPANY,
        acceptance_id=UUID(int=203),
        target=target,
        verdict="pass",
        proofs=(proof,),
        recorded_at=NOW,
    )
    return CurrentWorkAcceptance(company_id=COMPANY, acceptance=accepted)

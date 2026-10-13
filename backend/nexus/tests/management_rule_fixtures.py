"""Shared typed rule fixtures; no DB, authority, scheduler or business execution."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.acceptance import (
    ProtectedCheckProof,
    VerificationSpec,
    WorkAcceptance,
)
from nexus.company.management.base import RevisionRef
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.eligibility_rules import (
    AcceptedWork,
    CurrentReadGrant,
    EligibilityFacts,
    ManagementVersions,
    PublishedAcceptance,
)
from nexus.company.management.goals import GoalRevisionRef
from nexus.company.management.governance import CharterRevisionRef
from nexus.company.management.lifecycle import PlanRevisionRef
from nexus.company.management.plans import RunBinding
from nexus.execution.runtime_contracts import AttemptQuota

NOW = datetime(2026, 10, 14, 5, tzinfo=UTC)
COMPANY, WORKSPACE = UUID(int=1), UUID(int=2)


def binding(number: int = 10) -> RunBinding:
    return RunBinding(
        company_id=COMPANY,
        workspace_id=WORKSPACE,
        actor_id=UUID(int=number + 100),
        task_id=UUID(int=number),
        trace_id=UUID(int=number + 200),
        run_id=UUID(int=number + 300),
        workflow_name="internal.check",
        workflow_version="v1",
        model_profile="offline.v1",
        model_registry_version="registry.v1",
    )


def versions() -> ManagementVersions:
    shared = {
        "company_id": COMPANY,
        "revision_id": UUID(int=3),
        "version": "v1",
        "sha256": "a" * 64,
    }
    return ManagementVersions(
        company_id=COMPANY,
        mandate=RevisionRef.model_validate(shared),
        goal=GoalRevisionRef.model_validate(shared | {"goal_id": UUID(int=4)}),
        plan=PlanRevisionRef(
            company_id=COMPANY,
            plan_id=UUID(int=5),
            plan_revision_id=UUID(int=6),
            revision=1,
            sha256="b" * 64,
        ),
        charter=CharterRevisionRef.model_validate(shared | {"department_id": UUID(int=7)}),
        work_snapshot_sha256="c" * 64,
    )


def receipt(work: RunBinding) -> ActionReceipt:
    return ActionReceipt(
        company_id=COMPANY,
        receipt_id=UUID(int=400),
        action_id=UUID(int=401),
        task_id=work.task_id,
        trace_id=work.trace_id,
        proposal_hash="d" * 64,
        outcome="succeeded",
        recorded_at=NOW,
        artifacts=(
            ArtifactRef(
                company_id=COMPANY,
                artifact_id=UUID(int=410),
                revision="1",
                reference="protected:artifact",
                sha256="e" * 64,
            ),
        ),
    )


def target(work: RunBinding, verifier: RunBinding | None = None) -> VerificationSpec:
    recorded = receipt(work)
    return VerificationSpec(
        company_id=COMPANY,
        author=work,
        verifier=verifier or binding(20),
        action_id=recorded.action_id,
        proposal_sha256=recorded.proposal_hash,
        receipt_id=recorded.receipt_id,
        receipt_sha256=canonical_sha256(recorded),
        work_snapshot_sha256="c" * 64,
        criterion_ids=("behavior",),
        check_recipe="mechanical.v1",
        artifacts=(
            ArtifactRevisionRef(
                company_id=COMPANY,
                artifact_id=UUID(int=410),
                artifact_revision_id=UUID(int=411),
                revision="1",
                sha256="e" * 64,
                byte_length=12,
            ),
        ),
    )


def accepted(work: RunBinding, *, valid: bool = True) -> AcceptedWork:
    spec = target(work, binding(work.task_id.int + 50))
    acceptance = WorkAcceptance(
        company_id=COMPANY,
        acceptance_id=UUID(int=work.task_id.int + 500),
        target=spec,
        verdict="pass",
        recorded_at=NOW,
        proofs=(
            ProtectedCheckProof(
                company_id=COMPANY,
                proof_id=UUID(int=work.task_id.int + 600),
                recipe=spec.check_recipe,
                result_artifact=spec.artifacts[0],
                target_sha256=canonical_sha256(spec),
            ),
        ),
    )
    return AcceptedWork(
        company_id=COMPANY,
        work=work,
        work_snapshot_sha256="c" * 64,
        criterion_ids=("behavior",),
        publication=PublishedAcceptance(
            company_id=COMPANY,
            acceptance=acceptance,
            trusted_proofs_resolved=valid,
            invalidated=False,
        ),
    )


def facts(number: int = 10) -> EligibilityFacts:
    work = binding(number)
    pending = AcceptedWork(
        company_id=COMPANY,
        work=work,
        work_snapshot_sha256="c" * 64,
        criterion_ids=("behavior",),
        publication=PublishedAcceptance(
            company_id=COMPANY, acceptance=None, trusted_proofs_resolved=False, invalidated=False
        ),
    )
    return EligibilityFacts(
        company_id=COMPANY,
        work=work,
        current_work=work,
        expected=versions(),
        current=versions(),
        execution_state="eligible",
        plan_approved=True,
        mandate_active=True,
        scope_available=True,
        registered_active=True,
        ancestors_active=True,
        company_paused=False,
        cancelled=False,
        approval_satisfied=True,
        billing_known=True,
        already_scheduled=False,
        available_usd=Decimal("0.50"),
        required_usd=Decimal("0.10"),
        remaining_attempts=AttemptQuota(),
        required_attempts=AttemptQuota(
            model_requests=1, tool_attempts=0, rework_rounds=0, plan_revisions=0
        ),
        own_acceptance=pending,
        grants=(
            CurrentReadGrant(
                company_id=COMPANY,
                resource_id=UUID(int=800),
                expected_generation=1,
                current_generation=1,
                grant_active=True,
                resource_active=True,
                source_current=True,
                expires_at=None,
            ),
        ),
    )


def changed(original: EligibilityFacts, **values: object) -> EligibilityFacts:
    return EligibilityFacts.model_validate_json(
        original.model_copy(update=values).model_dump_json()
    )

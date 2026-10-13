"""M3 declarations preserve knownness, bounded roots and exact verification without activation."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from nexus.company.brain.base import SourceTime
from nexus.company.brain.sources import ArtifactRevisionRef, EvidenceRef
from nexus.company.management.acceptance import (
    ProtectedCheckProof,
    VerificationSpec,
    WorkAcceptance,
)
from nexus.company.management.goals import DueIntent, GoalMetric, KnownBaseline, UnknownBaseline
from nexus.company.management.governance import CharterRevisionRef
from nexus.company.management.plans import ChildAllocation, ProcedureRoot, RunBinding
from nexus.execution.runtime_contracts import AttemptQuota

COMPANY = UUID(int=1)


def binding(**changes: object) -> RunBinding:
    return RunBinding.model_validate(
        {
            "company_id": COMPANY,
            "workspace_id": UUID(int=2),
            "actor_id": UUID(int=3),
            "task_id": UUID(int=4),
            "trace_id": UUID(int=5),
            "run_id": UUID(int=6),
            "workflow_name": "internal.report.v1",
            "workflow_version": "v1",
            "model_profile": "routine",
            "model_registry_version": "catalog-v1",
        }
        | changes
    )


def artifact() -> ArtifactRevisionRef:
    return ArtifactRevisionRef(
        company_id=COMPANY,
        artifact_id=UUID(int=20),
        artifact_revision_id=UUID(int=21),
        revision="r1",
        sha256="a" * 64,
        byte_length=100,
    )


@pytest.mark.parametrize(
    "bad", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity"), 1.0, True]
)
def test_goal_target_is_finite_exact_decimal_not_coerced(bad: object) -> None:
    with pytest.raises(ValidationError):
        GoalMetric.model_validate(
            {
                "company_id": COMPANY,
                "metric_id": "citation.coverage",
                "unit": "ratio",
                "comparator": "ge",
                "target": bad,
                "baseline": UnknownBaseline(reason="No observed baseline"),
            }
        )


def test_known_baseline_requires_evidence_and_unknown_does_not_fabricate_zero() -> None:
    with pytest.raises(ValidationError):
        KnownBaseline(
            value=Decimal(0),
            observed_at=SourceTime(precision="unknown", value=None, basis="missing"),
            evidence=(),
        )
    metric = GoalMetric(
        company_id=COMPANY,
        metric_id="citation.coverage",
        unit="ratio",
        comparator="ge",
        target=Decimal(1),
        baseline=UnknownBaseline(reason="No measured observation"),
    )
    assert metric.baseline.kind == "unknown" and not hasattr(metric.baseline, "value")
    with pytest.raises(ValidationError):
        GoalMetric(
            metric_id="citation.coverage",
            unit="ratio",
            comparator="ge",
            target=Decimal(1),
            baseline=KnownBaseline(
                value=Decimal(0),
                observed_at=SourceTime(precision="day", value="2026-10-14", basis="report"),
                evidence=(EvidenceRef(company_id=UUID(int=99), evidence_id=UUID(int=22)),),
            ),
            company_id=COMPANY,
        )


def test_due_intent_preserves_source_precision_without_invented_midnight() -> None:
    date = SourceTime(precision="day", value="2026-10-15", basis="operator source date")
    due = DueIntent(source_time=date)
    assert due.source_time == date and due.actionable_at is None
    with pytest.raises(ValidationError):
        DueIntent(source_time=date, actionable_at=datetime(2026, 10, 15, tzinfo=UTC))
    explicit = DueIntent(
        source_time=date,
        actionable_at=datetime(2026, 10, 15, 2, tzinfo=UTC),
        actionable_basis="operator_explicit",
    )
    assert explicit.actionable_at == datetime(2026, 10, 15, 2, tzinfo=UTC)
    with pytest.raises(ValidationError):
        DueIntent(
            source_time=date,
            actionable_at=datetime(2026, 10, 15),
            actionable_basis="operator_explicit",
        )


def test_procedure_root_is_nonexecuting_and_exact_money_cannot_create_allowance() -> None:
    root = ProcedureRoot(
        company_id=COMPANY,
        procedure_id=UUID(int=10),
        goal_id=UUID(int=11),
        binding=binding(),
        allocation_usd=Decimal("1.00"),
        quota=AttemptQuota(),
    )
    assert root.non_executing is True
    with pytest.raises(ValidationError):
        ProcedureRoot(
            company_id=COMPANY,
            procedure_id=UUID(int=10),
            goal_id=UUID(int=11),
            binding=binding(),
            allocation_usd=Decimal("1.0000001"),
            quota=AttemptQuota(),
        )
    with pytest.raises(ValidationError):
        ChildAllocation.model_validate(
            {
                "company_id": COMPANY,
                "binding": binding(),
                "allocation_usd": 0.5,
                "quota": AttemptQuota(),
                "charter": CharterRevisionRef(
                    company_id=COMPANY,
                    department_id=UUID(int=60),
                    revision_id=UUID(int=61),
                    version="v1",
                    sha256="f" * 64,
                ),
            }
        )


def spec() -> VerificationSpec:
    return VerificationSpec(
        company_id=COMPANY,
        author=binding(),
        verifier=binding(actor_id=UUID(int=30), task_id=UUID(int=31), run_id=UUID(int=32)),
        action_id=UUID(int=40),
        proposal_sha256="b" * 64,
        receipt_id=UUID(int=41),
        receipt_sha256="c" * 64,
        work_snapshot_sha256="d" * 64,
        criterion_ids=("citation.coverage",),
        artifacts=(artifact(),),
        check_recipe="report.check.v1",
    )


def test_runtime_verification_is_exact_and_author_cannot_verify_self() -> None:
    exact = spec()
    assert exact.receipt_id is not None and exact.artifacts
    with pytest.raises(ValidationError):
        VerificationSpec.model_validate(exact.model_dump() | {"receipt_id": None})
    with pytest.raises(ValidationError):
        VerificationSpec.model_validate(
            exact.model_dump() | {"verifier": binding(task_id=UUID(int=31))}
        )


def test_pass_acceptance_needs_registered_protected_proof_not_candidate_uuid() -> None:
    exact = spec()
    with pytest.raises(ValidationError):
        WorkAcceptance(
            company_id=COMPANY,
            acceptance_id=UUID(int=50),
            target=exact,
            verdict="pass",
            proofs=(),
            recorded_at=datetime.now(UTC),
        )
    with pytest.raises(ValidationError):
        ProtectedCheckProof.model_validate(
            {
                "company_id": COMPANY,
                "proof_id": UUID(int=51),
                "recipe": "report.check.v1",
                "result_artifact": artifact(),
                "target_sha256": "e" * 64,
                "verified": True,
            }
        )

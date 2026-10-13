"""Auditable authority changes retain exact typed heads; financial/report values remain truthful."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from nexus.company.management.base import RevisionRef
from nexus.company.management.canonical import canonical_json
from nexus.company.management.control_events import (
    GoalSubject,
    ManagementControlEvent,
    MandateSubject,
)
from nexus.company.management.goals import GoalRevisionRef
from nexus.company.management.operations import LedgerSnapshot, WorkProjection
from nexus.company.management.plans import ProcedureRoot
from nexus.execution.runtime_contracts import AttemptQuota
from nexus.tests.unit.test_company_management_contracts import COMPANY, binding


def test_revoke_reactivate_audit_retains_exact_current_revision_and_scope() -> None:
    ref = RevisionRef(company_id=COMPANY, revision_id=UUID(int=60), version="v1", sha256="a" * 64)
    data = {
        "company_id": COMPANY,
        "event_id": UUID(int=61),
        "sequence": 1,
        "kind": "revoke",
        "subject": MandateSubject(current=ref, previous=ref),
        "owner_id": UUID(int=3),
        "operation_id": UUID(int=62),
        "trace_id": UUID(int=63),
        "deduplication_key": "mandate.revoke.v1",
        "recorded_at": datetime.now(UTC),
    }
    event = ManagementControlEvent.model_validate(data)
    assert event.subject.current == event.subject.previous
    with pytest.raises(ValidationError):
        ManagementControlEvent.model_validate(data | {"subject": MandateSubject(current=ref)})
    with pytest.raises(ValidationError):
        ManagementControlEvent.model_validate(
            data
            | {
                "subject": MandateSubject(
                    current=ref.model_copy(update={"company_id": UUID(int=99)}), previous=ref
                )
            }
        )


def test_goal_audit_cannot_splice_another_logical_goal() -> None:
    ref = GoalRevisionRef(
        company_id=COMPANY,
        revision_id=UUID(int=60),
        version="v1",
        sha256="a" * 64,
        goal_id=UUID(int=11),
    )
    with pytest.raises(ValidationError):
        GoalSubject(current=ref, previous=ref.model_copy(update={"goal_id": UUID(int=99)}))


def test_negative_zero_usd_has_one_canonical_snapshot_identity() -> None:
    root = ProcedureRoot(
        company_id=COMPANY,
        procedure_id=UUID(int=10),
        goal_id=UUID(int=11),
        binding=binding(),
        allocation_usd=Decimal("-0"),
        quota=AttemptQuota(),
    )
    assert '"allocation_usd":"0.000000"' in canonical_json(root)


def test_reports_do_not_clamp_truthful_overbill_or_infer_missing_acceptance() -> None:
    ledger = LedgerSnapshot(
        held_usd=Decimal("0.50"),
        spent_usd=Decimal("7.00"),
        source_sha256="b" * 64,
        observed_at=datetime.now(UTC),
    )
    assert ledger.spent_usd == Decimal(7)
    with pytest.raises(ValidationError):
        WorkProjection(
            company_id=COMPANY,
            work=binding(),
            execution_state="verifying",
            registered_active=True,
            acceptance="accepted",
            billing="unconfirmed",
        )
    unknown = WorkProjection(
        company_id=COMPANY,
        work=binding(),
        execution_state="outcome_unknown",
        registered_active=False,
        acceptance="pending",
        billing="unconfirmed",
    )
    assert unknown.billing == "unconfirmed" and unknown.acceptance_id is None

"""Report scopes and actual charge totals keep uncertain/candidate/cancelled work truthful."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from nexus.company.access import PrincipalAccess
from nexus.company.contracts.results import VerificationResult
from nexus.company.management.report_rules import (
    ChargeProjection,
    ReportInput,
    ReportScope,
    WorkLineage,
    WorkReportFacts,
    project_report,
)
from nexus.tests.management_rule_fixtures import (
    COMPANY,
    NOW,
    WORKSPACE,
    accepted,
    binding,
    facts,
    receipt,
)

OWNER = UUID(int=900)


def report_work() -> WorkReportFacts:
    source = facts()
    return WorkReportFacts(
        company_id=COMPANY,
        work=source.work,
        execution_state="verifying",
        registered_active=True,
        cancelled=False,
        acceptance=source.own_acceptance,
        receipt=receipt(source.work),
        verification_candidate=VerificationResult(
            company_id=COMPANY,
            verification_id=UUID(int=50),
            action_id=UUID(int=401),
            verifier_id=UUID(int=51),
            verdict="pass",
            criterion_ids=("behavior",),
            evidence_ids=(UUID(int=52),),
        ),
        required_resources=(UUID(int=800),),
    )


def report() -> ReportInput:
    source, work = facts(), report_work()
    root = binding(1)
    return ReportInput(
        company_id=COMPANY,
        report_id=UUID(int=901),
        scope=ReportScope(
            company_id=COMPANY,
            company_report=True,
            access=PrincipalAccess(
                company_id=COMPANY,
                workspace_id=WORKSPACE,
                principal_id=OWNER,
                owner_id=OWNER,
                membership_role="owner",
                company_active=True,
                workspace_active=True,
                principal_active=True,
                membership_active=True,
            ),
            grants=source.grants,
        ),
        period_start=NOW - timedelta(hours=1),
        period_end=NOW + timedelta(hours=1),
        observed_at=NOW,
        ledger_source_sha256="f" * 64,
        lineage=(
            WorkLineage(
                company_id=COMPANY, work=root, parent_task_id=None, root_task_id=root.task_id
            ),
            WorkLineage(
                company_id=COMPANY,
                work=work.work,
                parent_task_id=root.task_id,
                root_task_id=root.task_id,
            ),
        ),
        work=(work,),
        charges=(),
        owner_decision_ids=(UUID(int=902),),
    )


def charge(**values: object) -> ChargeProjection:
    return ChargeProjection.model_validate(
        {
            "company_id": COMPANY,
            "charge_id": UUID(int=401),
            "task_id": binding().task_id,
            "root_task_id": binding(1).task_id,
            "amount_usd": Decimal("0.40"),
            "actual_usd": Decimal("0.25"),
            "state": "reconciled",
            "issued": True,
            "required_resources": (UUID(int=800),),
        }
        | values
    )


def changed(source: ReportInput, **values: object) -> ReportInput:
    return ReportInput.model_validate_json(source.model_copy(update=values).model_dump_json())


def test_known_success_and_candidate_pass_remain_unaccepted() -> None:
    result = project_report(report())
    assert result.accepted_task_ids == () and result.receipt_task_ids == (binding().task_id,)
    assert result.snapshot.work[0].execution_state == "verifying"
    assert result.snapshot.work[0].acceptance == "pending"
    assert result.snapshot.ledger.spent_usd == 0 and result.actual_total_usd is None
    assert result.unknown_charge_ids == (UUID(int=401),)


def test_exact_charge_replay_and_ancestor_duplicates_are_counted_once() -> None:
    actual = charge()
    source = changed(report(), charges=(actual, actual, actual))
    first, replay = project_report(source), project_report(source)
    assert first == replay and first.snapshot.ledger.spent_usd == Decimal("0.25")
    assert first.actual_total_usd == Decimal("0.25") and first.snapshot.ledger.held_usd == 0


def test_inconsistent_duplicate_charge_is_rejected_without_clamping() -> None:
    with pytest.raises(ValueError, match="Conflicting replay"):
        project_report(changed(report(), charges=(charge(), charge(actual_usd=Decimal("0.50")))))


def test_unconfirmed_billing_retains_hold_and_never_becomes_zero_actual_total() -> None:
    unknown = charge(state="unknown", actual_usd=None)
    result = project_report(changed(report(), charges=(unknown,)))
    assert result.snapshot.ledger.held_usd == Decimal("0.40")
    assert result.snapshot.ledger.spent_usd == 0 and result.actual_total_usd is None
    assert result.unknown_charge_ids == (unknown.charge_id,)
    assert result.snapshot.work[0].billing == "unconfirmed"
    unissued = charge(state="held", actual_usd=None, issued=False)
    source = report()
    no_receipt = source.work[0].model_copy(update={"receipt": None})
    held = project_report(changed(source, work=(no_receipt,), charges=(unissued,)))
    assert held.snapshot.ledger.held_usd == Decimal("0.40") and held.unknown_charge_ids == ()
    contradicted = project_report(changed(source, charges=(unissued,)))
    assert (
        contradicted.actual_total_usd is None
        and contradicted.snapshot.work[0].billing == "unconfirmed"
    )


def test_overrun_actual_cost_is_truthful_not_clamped_to_reserved_amount() -> None:
    result = project_report(changed(report(), charges=(charge(actual_usd=Decimal("8.50")),)))
    assert result.actual_total_usd == Decimal(
        "8.50"
    ) and result.snapshot.ledger.spent_usd == Decimal("8.50")


def test_only_current_trusted_independent_acceptance_marks_accepted_work() -> None:
    source = report()
    row = source.work[0].model_copy(update={"acceptance": accepted(source.work[0].work)})
    result = project_report(changed(source, work=(row,)))
    assert (
        result.accepted_task_ids == (row.work.task_id,)
        and result.snapshot.work[0].acceptance == "accepted"
    )
    invalidated = row.acceptance.model_copy(
        update={"publication": row.acceptance.publication.model_copy(update={"invalidated": True})}
    )
    invalid = project_report(
        changed(source, work=(row.model_copy(update={"acceptance": invalidated}),))
    )
    assert invalid.accepted_task_ids == () and invalid.snapshot.work[0].acceptance == "invalidated"


def test_inactive_cancelled_blocked_and_unknown_work_are_retained_in_owner_report() -> None:
    source = report()
    row = source.work[0].model_copy(
        update={
            "registered_active": False,
            "cancelled": True,
            "execution_state": "outcome_unknown",
            "blockers": ("owner reconciliation required",),
        }
    )
    result = project_report(changed(source, work=(row,)))
    assert result.cancelled_task_ids == (row.work.task_id,)
    assert result.snapshot.work[0].registered_active is False
    assert result.snapshot.work[0].execution_state == "outcome_unknown"
    assert result.snapshot.blockers == ("owner reconciliation required",)


def test_private_resource_denial_happens_before_totals_statuses_or_owner_decisions() -> None:
    source = report()
    expired = source.scope.grants[0].model_copy(update={"expires_at": NOW})
    result = project_report(
        changed(
            source,
            charges=(charge(),),
            scope=source.scope.model_copy(update={"grants": (expired,)}),
        )
    )
    assert result.snapshot.work == () and result.snapshot.ledger.spent_usd == 0
    assert result.receipt_task_ids == () and result.accepted_task_ids == ()


def test_work_actor_cannot_claim_company_totals_or_another_actor_scope() -> None:
    source = report()
    access = source.scope.access.model_copy(
        update={"principal_id": binding().actor_id, "membership_role": "member"}
    )
    with pytest.raises(ValueError, match="Company totals"):
        project_report(changed(source, scope=source.scope.model_copy(update={"access": access})))
    actor = source.scope.model_copy(
        update={"access": access, "company_report": False, "allowed_task_ids": (binding().task_id,)}
    )
    visible = project_report(changed(source, scope=actor, charges=(charge(),)))
    assert (
        visible.snapshot.ledger.spent_usd == Decimal("0.25")
        and visible.snapshot.owner_decision_ids == ()
    )
    other = actor.model_copy(
        update={"access": access.model_copy(update={"principal_id": UUID(int=777)})}
    )
    assert project_report(changed(source, scope=other, charges=(charge(),))).snapshot.work == ()


def test_charge_root_and_cyclic_missing_ancestry_are_rejected() -> None:
    source = report()
    with pytest.raises(ValueError, match="incorrectly rooted"):
        project_report(changed(source, charges=(charge(root_task_id=UUID(int=888)),)))
    cycle = source.lineage[0].model_copy(update={"parent_task_id": source.work[0].work.task_id})
    with pytest.raises(ValueError, match="cyclic"):
        project_report(changed(source, lineage=(cycle, source.lineage[1])))


def test_actual_zero_requires_reconciled_billing_evidence() -> None:
    result = project_report(changed(report(), charges=(charge(actual_usd=Decimal("0")),)))
    assert result.actual_total_usd == 0 and result.unknown_charge_ids == ()
    assert result.snapshot.work[0].billing == "known"


def test_old_acceptance_hash_never_becomes_accepted_report_work() -> None:
    source = report()
    old = accepted(source.work[0].work).model_copy(update={"work_snapshot_sha256": "0" * 64})
    row = source.work[0].model_copy(update={"acceptance": old})
    result = project_report(changed(source, work=(row,)))
    assert result.accepted_task_ids == () and result.snapshot.work[0].acceptance == "invalidated"


@pytest.mark.parametrize(
    "field", ["company_active", "workspace_active", "principal_active", "membership_active"]
)
def test_inactive_read_scope_cannot_emit_report(field: str) -> None:
    source = report()
    scope = source.scope.model_copy(
        update={"access": source.scope.access.model_copy(update={field: False})}
    )
    with pytest.raises(ValueError):
        project_report(changed(source, scope=scope))

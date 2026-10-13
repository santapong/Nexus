"""Pure real-shape eligibility facts; no candidate completion, allowance mint or scheduler."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from nexus.company.brain.base import SourceTime
from nexus.company.management.eligibility_rules import (
    CurrentReadGrant,
    VerificationTrigger,
    evaluate_graph,
    evaluate_work,
)
from nexus.company.management.goals import DueIntent
from nexus.company.management.plans import VerificationIntent
from nexus.execution.runtime_contracts import AttemptQuota
from nexus.tests.management_rule_fixtures import (
    COMPANY,
    NOW,
    accepted,
    binding,
    changed,
    facts,
    receipt,
    target,
)


def test_ready_is_deterministic_but_does_not_issue_or_mutate() -> None:
    source = facts()
    first, replay = evaluate_work(source, NOW), evaluate_work(source, NOW)
    assert first == replay and first.state == "eligible" and first.reason == "ready"
    assert source.execution_state == "eligible" and not hasattr(first, "permit_external_call")
    assert evaluate_work(changed(source, already_scheduled=True), NOW).reason == "dispatch_active"


@pytest.mark.parametrize(
    "values,reason",
    [
        ({"company_paused": True}, "company_paused"),
        ({"mandate_active": False}, "mandate_revoked"),
        ({"registered_active": False}, "scope_unavailable"),
        ({"ancestors_active": False}, "scope_unavailable"),
        ({"execution_state": "outcome_unknown"}, "outcome_unknown"),
        ({"billing_known": False}, "billing_unknown"),
        ({"available_usd": Decimal("0")}, "budget_exhausted"),
        ({"current": None}, "versions_stale"),
    ],
)
def test_current_controls_block(values: dict[str, object], reason: str) -> None:
    result = evaluate_work(changed(facts(), **values), NOW)
    assert result.state == "blocked" and result.reason == reason


def test_expired_revoked_and_changed_source_grants_block() -> None:
    source = facts()
    for values in (
        {"expires_at": NOW},
        {"grant_active": False},
        {"resource_active": False},
        {"current_generation": 2},
        {"source_current": False},
    ):
        grant = CurrentReadGrant.model_validate_json(
            source.grants[0].model_copy(update=values).model_dump_json()
        )
        assert evaluate_work(changed(source, grants=(grant,)), NOW).reason == "source_unavailable"


def test_raw_pass_candidate_cannot_complete_dependency_but_exact_publication_can() -> None:
    author, next_work = facts(), facts(30)
    untrusted = accepted(author.work, valid=False)
    assert (
        evaluate_work(changed(next_work, dependencies=(untrusted,)), NOW).reason
        == "dependency_unaccepted"
    )
    assert (
        evaluate_work(changed(next_work, dependencies=(accepted(author.work),)), NOW).state
        == "eligible"
    )
    invalid = untrusted.model_copy(
        update={
            "publication": untrusted.publication.model_copy(
                update={"trusted_proofs_resolved": True, "invalidated": True}
            )
        }
    )
    assert evaluate_work(changed(next_work, dependencies=(invalid,)), NOW).state == "waiting"


def test_acceptance_for_old_criteria_or_run_never_satisfies_dependency() -> None:
    dependency = accepted(binding())
    for values in (
        {"criterion_ids": ("changed",)},
        {"work_snapshot_sha256": "f" * 64},
        {"work": binding(11)},
    ):
        altered = dependency.model_copy(update=values)
        assert (
            evaluate_work(changed(facts(30), dependencies=(altered,)), NOW).reason
            == "dependency_unaccepted"
        )


def test_verifier_uses_known_result_trigger_without_waiting_for_author_acceptance() -> None:
    author, verifier = facts(), facts(20)
    spec = target(author.work, verifier.work)
    trigger = VerificationTrigger(
        company_id=COMPANY,
        intent=VerificationIntent(
            company_id=COMPANY,
            author_task_id=author.work.task_id,
            verifier_task_id=verifier.work.task_id,
            check_recipe=spec.check_recipe,
        ),
        author=author.work,
        author_work_sha256="c" * 64,
        resolved=spec,
        receipt=receipt(author.work),
        protected_artifacts_available=True,
    )
    result = evaluate_graph((changed(verifier, verification=trigger), author), NOW)
    assert result[1].state == "eligible" and result[1].reason == "verification_result_available"
    missing = trigger.model_copy(update={"receipt": None})
    assert (
        evaluate_work(changed(verifier, verification=missing), NOW).reason == "verification_unbound"
    )


def test_date_only_due_is_unknown_until_operator_supplies_actionable_instant() -> None:
    due = DueIntent(source_time=SourceTime(precision="day", value="2026-10-14", basis="owner date"))
    assert evaluate_work(changed(facts(), due=due), NOW).reason == "due_pending"
    explicit = due.model_copy(
        update={
            "actionable_at": NOW + timedelta(seconds=1),
            "actionable_basis": "operator_explicit",
        }
    )
    assert evaluate_work(changed(facts(), due=explicit), NOW).reason == "due_pending"
    assert (
        evaluate_work(changed(facts(), due=explicit), NOW + timedelta(seconds=1)).state
        == "eligible"
    )


def test_graph_cycles_absent_dependencies_and_duplicate_work_fail() -> None:
    first, second = facts(), facts(30)
    with pytest.raises(ValueError, match="cycle"):
        evaluate_graph(
            (
                changed(first, dependencies=(accepted(second.work),)),
                changed(second, dependencies=(accepted(first.work),)),
            ),
            NOW,
        )
    with pytest.raises(ValueError, match="absent"):
        evaluate_graph((changed(first, dependencies=(accepted(second.work),)),), NOW)
    with pytest.raises(ValueError, match="unique"):
        evaluate_graph((first, first), NOW)


def test_verifier_author_source_and_hash_bindings_are_exact() -> None:
    author, verifier = facts(), facts(20)
    spec = target(author.work, verifier.work)
    trigger = VerificationTrigger(
        company_id=COMPANY,
        intent=VerificationIntent(
            company_id=COMPANY,
            author_task_id=author.work.task_id,
            verifier_task_id=verifier.work.task_id,
            check_recipe=spec.check_recipe,
        ),
        author=author.work,
        author_work_sha256="c" * 64,
        resolved=spec,
        receipt=receipt(author.work),
        protected_artifacts_available=True,
    )
    for values in (
        {"author_work_sha256": "0" * 64},
        {"author": binding(11)},
        {"resolved": spec.model_copy(update={"receipt_sha256": "0" * 64})},
        {"resolved": spec.model_copy(update={"verifier": binding(21)})},
        {"protected_artifacts_available": False},
        {"receipt": receipt(author.work).model_copy(update={"artifacts": ()})},
        {"receipt": receipt(author.work).model_copy(update={"outcome": "outcome_unknown"})},
    ):
        altered = trigger.model_copy(update=values)
        assert (
            evaluate_work(changed(verifier, verification=altered), NOW).reason
            == "verification_unbound"
        )


def test_zero_quota_cancelled_and_accepted_work_cannot_dispatch() -> None:
    source = facts()
    zero = AttemptQuota(model_requests=0, tool_attempts=0, rework_rounds=0, plan_revisions=0)
    assert evaluate_work(changed(source, remaining_attempts=zero), NOW).reason == "budget_exhausted"
    assert evaluate_work(changed(source, cancelled=True), NOW).state == "cancelled"
    assert (
        evaluate_work(changed(source, own_acceptance=accepted(source.work)), NOW).reason
        == "already_accepted"
    )


def test_own_acceptance_snapshot_must_match_selected_work_snapshot() -> None:
    source = facts()
    with pytest.raises(ValueError, match="snapshot"):
        changed(
            source,
            own_acceptance=accepted(source.work).model_copy(
                update={"work_snapshot_sha256": "0" * 64}
            ),
        )


def test_graph_rejects_old_dependency_binding_even_when_its_old_acceptance_is_valid() -> None:
    author, next_work = facts(), facts(30)
    old = author.work.model_copy(update={"workflow_version": "old"})
    with pytest.raises(ValueError, match="binding"):
        evaluate_graph((author, changed(next_work, dependencies=(accepted(old),))), NOW)


def test_ordinary_two_step_dependencies_use_current_independent_acceptances() -> None:
    first, second, third = facts(), facts(30), facts(40)
    first = changed(first, own_acceptance=accepted(first.work))
    second = changed(
        second, own_acceptance=accepted(second.work), dependencies=(first.own_acceptance,)
    )
    third = changed(third, dependencies=(second.own_acceptance,))
    rows = evaluate_graph((third, second, first), NOW)
    assert tuple(row.work.task_id for row in rows) == tuple(
        sorted(row.work.task_id for row in rows)
    )
    assert tuple(row.reason for row in rows) == ("already_accepted", "already_accepted", "ready")
    invalid = second.own_acceptance.model_copy(
        update={
            "publication": second.own_acceptance.publication.model_copy(
                update={"invalidated": True}
            )
        }
    )
    assert (
        evaluate_work(changed(third, dependencies=(invalid,)), NOW).reason
        == "dependency_unaccepted"
    )


def test_current_run_model_and_workflow_pins_cannot_be_rebound() -> None:
    source = facts()
    for values in (
        {"workflow_version": "v2"},
        {"model_registry_version": "v2"},
        {"run_id": binding(11).run_id},
    ):
        current = source.work.model_copy(update=values)
        assert evaluate_work(changed(source, current_work=current), NOW).reason == "versions_stale"

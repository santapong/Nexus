"""Strict measurement declarations do not accept caller-provided counts or authority."""

from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from nexus.company.management.goals import GoalRevisionRef, UnknownBaseline
from nexus.company.management.lifecycle import PlanRevisionRef
from nexus.company.management.metric_contracts import (
    KnownMetricValue,
    MetricComparison,
    MetricObservationRequest,
    UnknownMetricValue,
)


def request() -> MetricObservationRequest:
    company = uuid4()
    return MetricObservationRequest(
        company_id=company,
        observation_id=uuid4(),
        metric_id="reports.accepted",
        goal=GoalRevisionRef(
            company_id=company,
            goal_id=uuid4(),
            revision_id=uuid4(),
            version="goal-v1",
            sha256="a" * 64,
        ),
        plan=PlanRevisionRef(
            company_id=company,
            plan_id=uuid4(),
            plan_revision_id=uuid4(),
            revision=1,
            sha256="b" * 64,
        ),
        task_ids=(uuid4(), uuid4()),
    )


@pytest.mark.parametrize(
    "extra", ({"value": 1}, {"verdict": "pass"}, {"completed": True}, {"owner": True})
)
def test_caller_result_and_authority_are_forbidden(extra: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        MetricObservationRequest.model_validate(request().model_dump() | extra)


def test_duplicate_foreign_and_unbounded_task_selection_are_rejected() -> None:
    value = request()
    for tasks in ((value.task_ids[0], value.task_ids[0]), (), tuple(uuid4() for _ in range(101))):
        with pytest.raises(ValidationError):
            MetricObservationRequest.model_validate(value.model_dump() | {"task_ids": tasks})
    with pytest.raises(ValidationError):
        MetricObservationRequest.model_validate(value.model_dump() | {"company_id": uuid4()})


@pytest.mark.parametrize("bad", (True, 1.5, "1", -1, 101))
def test_native_count_is_a_bounded_literal_integer(bad: object) -> None:
    with pytest.raises(ValidationError):
        KnownMetricValue.model_validate({"value": bad})


def test_unknown_count_never_becomes_zero_or_satisfied() -> None:
    unknown = UnknownMetricValue(reason="proof_unavailable")
    with pytest.raises(ValidationError):
        UnknownMetricValue.model_validate(unknown.model_dump() | {"value": 0})
    comparison = MetricComparison(
        value=unknown,
        comparator="ge",
        target=Decimal(1),
        baseline=UnknownBaseline(reason="No baseline observation"),
    )
    assert comparison.result == "unknown" and comparison.baseline.kind == "unknown"


def test_known_absolute_comparison_preserves_unknown_baseline() -> None:
    comparison = MetricComparison(
        value=KnownMetricValue(value=2),
        comparator="ge",
        target=Decimal(1),
        baseline=UnknownBaseline(reason="Unknown start"),
    )
    assert comparison.result == "satisfied" and comparison.baseline.kind == "unknown"
    assert comparison.baseline_change is None


@pytest.mark.parametrize(
    ("comparator", "target", "expected"),
    (
        ("gt", 2, "unsatisfied"),
        ("ge", 2, "satisfied"),
        ("eq", 2, "satisfied"),
        ("le", 2, "satisfied"),
        ("lt", 2, "unsatisfied"),
    ),
)
def test_all_comparators_use_actual_known_count(
    comparator: str,
    target: int,
    expected: str,
) -> None:
    comparison = MetricComparison.model_validate(
        {
            "value": KnownMetricValue(value=2),
            "comparator": comparator,
            "target": Decimal(target),
            "baseline": UnknownBaseline(reason="No source-supported baseline"),
        }
    )
    assert comparison.result == expected and comparison.baseline_change is None

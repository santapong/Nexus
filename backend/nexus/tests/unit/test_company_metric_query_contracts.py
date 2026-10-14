"""Typed page wire cannot widen native company/goal or numerical bounds."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from nexus.company.management.metric_queries import PageCandidate, validate_page_limit
from nexus.company.management.metric_query_contracts import MetricObservationPage


@pytest.mark.parametrize("value", (True, False, 0, -1, 9, "4", 4.0))
def test_page_limit_is_literal_bounded_integer(value: object) -> None:
    with pytest.raises(ValueError):
        validate_page_limit(value)


def test_empty_scoped_page_is_truthful_and_accepts_no_extra_authority() -> None:
    page = MetricObservationPage(company_id=uuid4(), goal_id=uuid4(), checked_at=datetime.now(UTC))
    assert page.observations == () and page.next_after_id is None
    with pytest.raises(ValidationError):
        MetricObservationPage.model_validate(page.model_dump() | {"eligible": True})


# The following are declared pure projection fixtures, not stored native observations.
def candidate(*, unknown: bool = False) -> PageCandidate:
    from decimal import Decimal

    from nexus.company.brain.sources import EvidenceRef
    from nexus.company.management.base import SourceTime
    from nexus.company.management.canonical import canonical_sha256
    from nexus.company.management.goals import KnownBaseline
    from nexus.company.management.metric_contracts import (
        KnownMetricValue,
        MetricComparison,
        MetricObservationRecord,
        MetricSnapshot,
        MetricWorkFact,
        UnknownMetricValue,
    )
    from nexus.company.management.metric_queries import PageCandidate
    from nexus.company.management.plans import RunBinding
    from nexus.tests.unit.test_company_metric_contracts import request

    selected = request()
    facts = tuple(
        MetricWorkFact(
            company_id=selected.company_id,
            work=RunBinding(
                company_id=selected.company_id,
                workspace_id=uuid4(),
                actor_id=uuid4(),
                task_id=task,
                trace_id=uuid4(),
                run_id=uuid4(),
                workflow_name="unit-fixture",
                workflow_version="v1",
                model_profile="routine",
                model_registry_version="unit-fixture",
            ),
            registration_sha256="a" * 64,
            acceptance_id=None,
            acceptance_sha256=None,
            receipt_id=None,
            status="unknown" if unknown else "not_accepted",
        )
        for task in selected.task_ids
    )
    snapshot = MetricSnapshot(
        company_id=selected.company_id,
        request=selected,
        recipe="native.accepted-report-count.v1",
        comparison=MetricComparison(
            value=UnknownMetricValue(reason="unsupported_unit")
            if unknown
            else KnownMetricValue(value=0),
            comparator="ge",
            target=Decimal(1),
            baseline=KnownBaseline(
                value=Decimal(0),
                observed_at=SourceTime(
                    precision="day",
                    value="2026-10-01",
                    basis="Declared unit fixture, not actual native measurement",
                ),
                evidence=(EvidenceRef(company_id=selected.company_id, evidence_id=uuid4()),),
            ),
        ),
        work=facts,
    )
    now = datetime.now(UTC)
    record = MetricObservationRecord(
        company_id=selected.company_id,
        observation_id=selected.observation_id,
        snapshot=snapshot,
        snapshot_sha256=canonical_sha256(snapshot),
        recorded_by=uuid4(),
        operation_id=uuid4(),
        audit_trace_id=uuid4(),
        observed_at=now,
    )
    return PageCandidate(record, snapshot, (now,) if unknown else ())


def test_unknown_count_still_masks_licensed_baseline_when_its_deadline_crosses() -> None:
    from nexus.company.management.metric_queries import projection

    item = candidate(unknown=True)
    result = projection(item, item.record.observed_at)
    assert result.snapshot.comparison.value.kind == "unknown"
    assert result.snapshot.comparison.baseline.kind == "unknown"
    assert not result.snapshot.sources


def test_page_size_mask_is_explicit_unknown_not_a_saved_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.company.access import CompanyControlScope
    from nexus.company.management import metric_queries

    item = candidate()
    scope = CompanyControlScope(
        company_id=item.record.company_id,
        principal_id=item.record.recorded_by,
        operation_id=uuid4(),
        trace_id=uuid4(),
    )
    # A smaller test ceiling exercises the same actual serializer/masking branch.
    ordinary = metric_queries.bounded_page(
        scope, item.snapshot.request.goal.goal_id, (item,), None, item.record.observed_at
    )
    ceiling = len(ordinary.model_dump_json().encode()) - 1
    monkeypatch.setattr(metric_queries, "MAX_METRIC_PAGE_BYTES", ceiling)
    result = metric_queries.bounded_page(
        scope, item.snapshot.request.goal.goal_id, (item,), None, item.record.observed_at
    )
    assert len(result.model_dump_json().encode()) <= ceiling
    value = result.observations[0].snapshot.comparison.value
    assert value.kind == "unknown" and value.reason == "scope_unavailable"

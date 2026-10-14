"""Scheduler scans bind exact triggers/pages; decoded results never issue effect permits."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from nexus.company.management.scheduling_contracts import (
    DueWake,
    EventWake,
    ScanPage,
    ScanRequest,
    SchedulerPolicy,
    WorkflowRegistration,
    request_sha256,
)

COMPANY = UUID(int=1)
NOW = datetime(2030, 1, 2, 3, 4, tzinfo=UTC)


def request() -> ScanRequest:
    return ScanRequest(company_id=COMPANY, wake=DueWake(bucket=NOW))


def test_request_hash_is_exact_but_task_selection_is_order_independent() -> None:
    first = request().model_copy(update={"task_ids": (UUID(int=20), UUID(int=10))})
    second = request().model_copy(update={"task_ids": (UUID(int=10), UUID(int=20))})
    assert request_sha256(first) == request_sha256(second)
    assert request_sha256(request()) != request_sha256(first)


def test_due_bucket_must_be_an_exact_aware_minute() -> None:
    with pytest.raises(ValidationError):
        DueWake(bucket=NOW.replace(second=1))
    with pytest.raises(ValidationError):
        DueWake(bucket=NOW.replace(tzinfo=None))


def test_page_requires_exact_monotone_trigger_range_and_plan_snapshot() -> None:
    with pytest.raises(ValidationError):
        ScanPage(
            after_task_id=UUID(int=20),
            brain_sequence=-1,
            control_sequence=2,
            plan_snapshot_sha256="a" * 64,
        )
    page = ScanPage(
        after_task_id=UUID(int=20),
        brain_sequence=1,
        control_sequence=2,
        plan_snapshot_sha256="a" * 64,
    )
    assert request_sha256(request().model_copy(update={"page": page})) != request_sha256(request())


def test_trigger_and_selection_reject_unknown_mutation_or_duplicate_fields() -> None:
    with pytest.raises(ValidationError):
        EventWake.model_validate({"stream": "brain", "event_id": UUID(int=3), "model_requests": 1})
    with pytest.raises(ValidationError):
        ScanRequest(
            company_id=COMPANY, wake=DueWake(bucket=NOW), task_ids=(UUID(int=3), UUID(int=3))
        )


def test_workflow_catalog_has_exact_names_and_no_duplicate_run_abi() -> None:
    workflow = WorkflowRegistration(
        workflow_name="internal.report",
        workflow_version="v1",
        queue_name="management.internal",
        application_name="nexus",
    )
    with pytest.raises(ValidationError):
        SchedulerPolicy(recipe_version="scheduler.v1", workflows=(workflow, workflow))
    policy = SchedulerPolicy(recipe_version="scheduler.v1", workflows=(workflow,))
    assert policy.max_tasks == 100

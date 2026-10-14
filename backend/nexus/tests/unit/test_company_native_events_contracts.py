"""New event references are strict and the original mapper never selects native columns."""

from datetime import UTC, date, datetime
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import Table, select
from sqlalchemy.orm import class_mapper

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.event_models import BrainEvent
from nexus.company.brain.events import OutboxEvent
from nexus.company.brain.native_event_models import NativeBrainEvent

NATIVE_FIELDS = {
    "task_id",
    "report_id",
    "budget_day",
    "native_snapshot_sha256",
    "due_bucket",
    "scheduled_for",
    "notification_policy_sha256",
}


def event(kind: str = "decision_required") -> dict[str, object]:
    company = uuid4()
    return {
        "company_id": company,
        "event_id": uuid4(),
        "sequence": 1,
        "kind": kind,
        "resource": ResourceRef(company_id=company, resource_id=uuid4()),
        "deduplication_key": "native.fixture.v1",
        "operation_id": uuid4(),
        "trace_id": uuid4(),
        "recorded_at": datetime.now(UTC),
        "action_id": uuid4(),
        "task_id": uuid4(),
        "native_snapshot_sha256": "a" * 64,
    }


def test_original_mapper_and_compiled_select_preserve_exact_old_properties() -> None:
    original = set(class_mapper(BrainEvent).column_attrs.keys())
    assert not original & NATIVE_FIELDS
    assert set(cast(Table, BrainEvent.__table__).columns.keys()).issuperset(NATIVE_FIELDS)
    native = set(class_mapper(NativeBrainEvent).column_attrs.keys())
    assert original | NATIVE_FIELDS == native
    sql = str(select(BrainEvent))
    assert not any(f"company_brain_events.{field}" in sql for field in NATIVE_FIELDS)
    full = str(select(NativeBrainEvent))
    assert all(f"company_brain_events.{field}" in full for field in NATIVE_FIELDS)


@pytest.mark.parametrize("missing", ["task_id", "action_id", "native_snapshot_sha256"])
def test_decision_requires_exact_action_task_and_native_state(missing: str) -> None:
    value = event()
    value.pop(missing)
    with pytest.raises(ValueError):
        OutboxEvent.model_validate(value)


@pytest.mark.parametrize(
    "field",
    [
        "report_id",
        "budget_day",
        "due_bucket",
        "scheduled_for",
        "notification_policy_sha256",
        "source_revision_id",
        "resource_generation",
    ],
)
def test_decision_rejects_foreign_kind_refs(field: str) -> None:
    value = event()
    value[field] = {
        "budget_day": date.today(),
        "due_bucket": "daily:2026-10-14",
        "scheduled_for": datetime.now(UTC),
        "notification_policy_sha256": "b" * 64,
        "resource_generation": 1,
    }.get(field, uuid4())
    with pytest.raises(ValueError):
        OutboxEvent.model_validate(value)


@pytest.mark.parametrize(
    "kind",
    [
        "source_revised",
        "acl_changed",
        "claims_changed",
        "derivation_changed",
        "receipt_recorded",
        "verification_recorded",
    ],
)
def test_old_kinds_reject_all_native_refs_and_preserve_old_binding(kind: str) -> None:
    values = event(kind)
    values.update(source_revision_id=uuid4(), resource_generation=1)
    with pytest.raises(ValueError):
        OutboxEvent.model_validate(values)
    for key in NATIVE_FIELDS:
        values.pop(key, None)
    assert OutboxEvent.model_validate(values).kind == kind


@pytest.mark.parametrize("subject", ["none", "both", "task", "day"])
def test_cap_requires_exactly_one_actual_subject(subject: str) -> None:
    value = event("cap_exhausted")
    value.pop("action_id")
    value.pop("task_id")
    if subject in {"task", "both"}:
        value["task_id"] = uuid4()
    if subject in {"day", "both"}:
        value["budget_day"] = date.today()
    if subject in {"task", "day"}:
        assert OutboxEvent.model_validate(value).kind == "cap_exhausted"
    else:
        with pytest.raises(ValueError):
            OutboxEvent.model_validate(value)

"""Uninstalled declaration conformance only; no normal014 or native publication is claimed."""

from collections.abc import Callable
from typing import cast

from sqlalchemy import CheckConstraint, Index, Table, UniqueConstraint
from sqlalchemy.dialects.postgresql.base import PGDialect
from sqlalchemy.engine import Dialect
from sqlalchemy.schema import CreateTable

from nexus.company.notifications.notification_models import (
    NotificationBase,
    NotificationDispatchRow,
    NotificationDraftRow,
    NotificationEventLinkRow,
    NotificationObservationRow,
)

_DIALECT = cast(Callable[[], Dialect], PGDialect)


def test_four_tables_are_isolated_and_company_first() -> None:
    assert set(NotificationBase.metadata.tables) == {
        "company_notification_drafts",
        "company_notification_event_links",
        "company_notification_dispatches",
        "company_notification_observations",
    }
    for table in NotificationBase.metadata.tables.values():
        assert next(iter(table.primary_key.columns)).name == "company_id"
        assert "recorded_at" in table.c
        assert not table.c.company_id.nullable
        assert str(CreateTable(table).compile(dialect=_DIALECT()))


def test_every_fk_has_complete_leading_prefix_index() -> None:
    for table in NotificationBase.metadata.tables.values():
        indexed = [tuple(column.name for column in table.primary_key.columns)]
        indexed += [tuple(column.name for column in index.columns) for index in table.indexes]
        indexed += [
            tuple(column.name for column in constraint.columns)
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        ]
        for key in table.foreign_key_constraints:
            columns = tuple(column.name for column in key.columns)
            assert any(row[: len(columns)] == columns for row in indexed), (table.name, key.name)


def test_event_link_preserves_actual_event_and_sequence_native_ref() -> None:
    table = NotificationEventLinkRow.__table__
    assert isinstance(table, Table)
    key = next(
        item for item in table.foreign_key_constraints if item.name == "fk_notification_link_event"
    )
    assert tuple(column.name for column in key.columns) == (
        "company_id",
        "event_id",
        "event_sequence",
    )
    assert tuple(element.target_fullname for element in key.elements) == (
        "company_brain_events.company_id",
        "company_brain_events.event_id",
        "company_brain_events.sequence",
    )


def test_exact_intent_fk_is_deferred_and_cannot_bind_model_or_other_trace() -> None:
    table = NotificationDispatchRow.__table__
    assert isinstance(table, Table)
    key = next(
        item
        for item in table.foreign_key_constraints
        if item.name == "fk_notification_dispatch_intent"
    )
    assert key.deferrable is True and key.initially == "DEFERRED"
    assert tuple(column.name for column in key.columns) == (
        "company_id",
        "action_id",
        "task_id",
        "trace_id",
        "run_id",
        "intent_fence",
        "attempt_kind",
        "proposal_sha256",
    )
    assert key.elements[-1].target_fullname == "company_effect_intents.proposal_hash"
    checks = {str(item.sqltext) for item in table.constraints if isinstance(item, CheckConstraint)}
    assert any("attempt_kind = 'tool_attempts'" in item for item in checks)
    assert any("Asia/Bangkok" in item for item in checks)


def test_observation_null_branches_and_acceptance_differ_from_delivery() -> None:
    table = NotificationObservationRow.__table__
    assert isinstance(table, Table)
    checks = {
        item.name: str(item.sqltext)
        for item in table.constraints
        if isinstance(item, CheckConstraint)
    }
    binding = checks["ck_notification_observation_binding"]
    assert "provider_id IS NOT NULL AND response_sha256 IS NOT NULL" in binding
    assert "provider_event IS NULL AND delivery_state = 'unknown'" in binding
    state = checks["ck_notification_observation_state"]
    assert "provider_event IS NOT NULL AND" in state
    assert "'opened','clicked','queued','scheduled','sent'" in state
    initial = next(
        item for item in table.indexes if item.name == "uq_notification_initial_submission"
    )
    assert isinstance(initial, Index) and initial.unique
    assert str(initial.dialect_options["postgresql"]["where"]) == "observation_kind = 'submission'"


def test_draft_subject_is_native_lookup_not_invented_foreign_key() -> None:
    table = NotificationDraftRow.__table__
    assert isinstance(table, Table)
    assert not table.c.subject_id.foreign_keys and not table.c.recipient_policy_id.foreign_keys
    checks = {str(item.sqltext) for item in table.constraints if isinstance(item, CheckConstraint)}
    assert any(
        "due_bucket IS NOT NULL" in item and "scheduled_for IS NOT NULL" in item for item in checks
    )
    assert any("octet_length(record_json) BETWEEN 1 AND 4194304" in item for item in checks)

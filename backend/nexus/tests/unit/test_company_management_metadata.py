"""Uninstalled M3 metadata declares native scoped references without changing company head."""

from collections.abc import Callable
from typing import cast

from sqlalchemy import CheckConstraint, Column, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql.base import PGDialect
from sqlalchemy.engine import Dialect
from sqlalchemy.schema import CreateTable

from nexus.company.management.models import ManagementBase

_DIALECT = cast(Callable[[], Dialect], PGDialect)


def test_management_manifest_is_separate_native_company_first_and_compiles_postgresql() -> None:
    tables = ManagementBase.metadata.tables
    assert len(tables) == 23  # Normal013 adds one immutable measured-observation table.
    for table in tables.values():
        assert next(iter(table.primary_key.columns)).name == "company_id"
        assert isinstance(table.c.company_id.type, Uuid)
        assert str(CreateTable(table).compile(dialect=_DIALECT()))
        for key in table.foreign_keys:
            assert isinstance(key.column, Column)
            assert key.column.table.name.startswith("company_")
        for constraint in table.foreign_key_constraints:
            target = constraint.elements[0].column.table
            target_keys = tuple(element.column.name for element in constraint.elements)
            unique_keys = {tuple(column.name for column in target.primary_key.columns)}
            unique_keys.update(
                tuple(column.name for column in unique.columns)
                for unique in target.constraints
                if isinstance(unique, UniqueConstraint)
            )
            assert target_keys in unique_keys, constraint.name


def test_procedure_one_root_per_company_goal_and_approved_binding_split() -> None:
    tables = ManagementBase.metadata.tables
    procedure = tables["company_management_procedures"]
    unique = {
        tuple(column.name for column in constraint.columns)
        for constraint in procedure.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("company_id", "goal_id") in unique
    assert "snapshot_json" in tables["company_management_plan_revisions"].c
    assert "task_id" not in tables["company_management_plan_revisions"].c
    binding = tables["company_management_plan_tasks"]
    assert any(key.column.table.name == "company_execution_work" for key in binding.foreign_keys)
    assert any(
        key.column.table.name == "company_management_charter_revisions"
        for key in binding.foreign_keys
    )


def test_no_completed_state_attempt_zero_fence_or_migration_activation_declared() -> None:
    tables = ManagementBase.metadata.tables
    assert "company_execution_work" not in tables
    revision = tables["company_management_revision_events"]
    assert "owner_id" in revision.c and "revision_counter" in revision.c
    assert "fence" not in revision.c and "attempt_kind" not in revision.c
    assert "company_management_acceptance_invalidations" in tables


def test_control_audit_has_exact_native_subject_shapes_and_explicit_activity_null_denial() -> None:
    event = ManagementBase.metadata.tables["company_management_control_events"]
    assert "subject_id" not in event.c
    checks = {
        check.name: str(check.sqltext)
        for check in event.constraints
        if isinstance(check, CheckConstraint)
    }
    shape = checks["ck_management_control_subject"]
    activity = checks["ck_management_control_activity_head"]
    for subject in ("mandate", "charter", "goal"):
        assert f"{subject}_revision_id IS NOT NULL" in shape
        assert f"previous_{subject}_revision_id IS NOT NULL" in activity
        assert f"previous_{subject}_revision_id={subject}_revision_id" in activity
    assert (
        len(event.foreign_key_constraints) == 8
    )  # company/member + exact current/previous triples.

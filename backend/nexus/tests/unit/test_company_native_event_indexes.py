"""New native event FKs require exact unique targets and full leading indexes."""

from typing import cast

from sqlalchemy import Table, UniqueConstraint

from nexus.company.brain.event_models import BrainEvent
from nexus.harness.journal_models import JournalAction


def test_decision_event_action_task_has_an_exact_native_unique_target() -> None:
    assert any(
        isinstance(constraint, UniqueConstraint)
        and tuple(constraint.columns.keys()) == ("company_id", "id", "task_id")
        for constraint in cast(Table, JournalAction.__table__).constraints
    )


def test_native_event_foreign_keys_have_full_covering_index_prefixes() -> None:
    table = cast(Table, BrainEvent.__table__)
    prefixes = {tuple(index.columns.keys()) for index in table.indexes}
    for foreign in table.foreign_key_constraints:
        if isinstance(foreign.name, str) and foreign.name.startswith("fk_brain_event_native_"):
            columns = tuple(foreign.columns.keys())
            assert any(prefix[: len(columns)] == columns for prefix in prefixes), foreign.name

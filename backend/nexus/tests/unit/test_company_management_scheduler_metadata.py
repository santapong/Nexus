"""Native company-bound scheduler receipts, separate from execution/cost permits."""

from collections.abc import Callable
from typing import cast

from sqlalchemy import Table
from sqlalchemy.dialects.postgresql.base import PGDialect
from sqlalchemy.engine import Dialect
from sqlalchemy.schema import CreateTable

from nexus.company.management.scheduling_models import ManagementSchedulerScan, SchedulingBase


def test_scheduler_scan_declares_native_scoped_unique_history() -> None:
    table = cast(Table, ManagementSchedulerScan.__table__)
    assert tuple(col.name for col in table.primary_key.columns) == ("company_id", "scan_id")
    sql = str(CreateTable(table).compile(dialect=cast(Callable[[], Dialect], PGDialect)()))
    assert "FOREIGN KEY(company_id, owner_id)" in sql
    assert "UNIQUE (company_id, consumer, recipe_version, event_key)" in sql
    assert "end_brain_sequence >= start_brain_sequence" in sql
    assert len(SchedulingBase.metadata.tables) == 1

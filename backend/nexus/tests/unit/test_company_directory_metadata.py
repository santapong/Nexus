"""Native UUID/FK compilation and ownership-only directory schema boundaries."""

from collections.abc import Callable
from typing import cast

from sqlalchemy import Table, Uuid
from sqlalchemy.dialects.postgresql.psycopg import PGDialect_psycopg
from sqlalchemy.engine import Dialect
from sqlalchemy.schema import AddConstraint, CreateTable

from nexus.company.directory_models import DirectoryBase, DirectoryCompany, RegisteredWork
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.harness.journal_models import CompanyControl

# SQLAlchemy's driver dialect has an unannotated optional-arguments constructor.
# This narrow zero-argument factory is exercised by all offline DDL checks below.
_DIALECT = cast(Callable[[], Dialect], PGDialect_psycopg)


def test_directory_fks_are_native_uuid_and_resolve_without_legacy_metadata() -> None:
    for table in DirectoryBase.metadata.sorted_tables:
        assert "CREATE TABLE" in str(CreateTable(table).compile(dialect=_DIALECT()))
        for fk in table.foreign_keys:
            assert isinstance(fk.parent.type, Uuid)
            assert isinstance(fk.column.type, Uuid)
    control_fk = next(
        fk
        for fk in DirectoryCompany.__table__.c.company_id.foreign_keys
        if fk.column.table.name == "company_controls"
    )
    assert control_fk.column is CompanyControl.__table__.c.company_id


def test_circular_owner_fk_is_named_and_deferred_for_atomic_bootstrap() -> None:
    owner_fk = next(
        c
        for c in cast(Table, DirectoryCompany.__table__).constraints
        if c.name == "fk_company_directory_owner"
    )
    ddl = str(AddConstraint(owner_fk).compile(dialect=_DIALECT()))
    assert "DEFERRABLE INITIALLY DEFERRED" in ddl


def test_parent_constraint_carries_company_and_immutable_root() -> None:
    parent_fk = next(
        c
        for c in cast(Table, RegisteredWork.__table__).constraints
        if c.name == "fk_company_work_parent_root"
    )
    ddl = str(AddConstraint(parent_fk).compile(dialect=_DIALECT()))
    assert "company_id, parent_task_id, root_task_id" in ddl
    assert "company_registered_work (company_id, task_id, root_task_id)" in ddl
    assert PersistentCompanyDirectory is not None

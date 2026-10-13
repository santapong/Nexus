"""Separate uninstalled management metadata with native company-first references."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, Table, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column
from sqlalchemy.sql import FromClause

from nexus.harness.journal_models import CompanyControl


class ManagementBase(DeclarativeBase):
    """Importing declarations installs no migrations, runtime or authority."""


class CompanyRow:
    @declared_attr
    def company_id(cls) -> Mapped[UUID]:  # noqa: N805
        return mapped_column(
            Uuid,
            ForeignKey(CompanyControl.__table__.c.company_id),
            primary_key=True,
            sort_order=-100,
        )


class RecordedRow:
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )


def scoped_fk(
    source: FromClause,
    columns: tuple[str, ...],
    target: FromClause,
    target_columns: tuple[str, ...],
    name: str,
    *,
    deferred: bool = False,
) -> None:
    """Actual Column objects avoid unresolved cross-metadata table names and scope drift."""
    if not isinstance(source, Table) or not isinstance(target, Table):
        raise TypeError("Scoped management foreign keys require actual native tables")
    source.append_constraint(
        ForeignKeyConstraint(
            [source.c[key] for key in columns],
            [target.c[key] for key in target_columns],
            name=name,
            use_alter=deferred,
            deferrable=True if deferred else None,
            initially="DEFERRED" if deferred else None,
        )
    )

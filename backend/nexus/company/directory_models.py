"""New-profile native UUID directory metadata, independent of legacy identity tables."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from nexus.harness.journal_models import CompanyControl


class DirectoryBase(DeclarativeBase):
    """Separate metadata; the profile baseline creates journal metadata first."""


class DirectoryCompany(DirectoryBase):
    """Explicit one-workspace/company mapping with the actual registered owner."""

    __tablename__ = "company_directory"
    company_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(CompanyControl.__table__.c.company_id),
        primary_key=True,
    )
    workspace_id: Mapped[UUID] = mapped_column(Uuid, unique=True)
    owner_id: Mapped[UUID] = mapped_column(Uuid)
    company_active: Mapped[bool] = mapped_column(Boolean, default=True)
    workspace_active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (
        UniqueConstraint("company_id", "workspace_id", name="uq_company_directory_workspace_scope"),
        ForeignKeyConstraint(
            ["company_id", "owner_id"],
            ["company_memberships.company_id", "company_memberships.principal_id"],
            name="fk_company_directory_owner",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
    )


class DirectoryMembership(DirectoryBase):
    """Scoped principal/member state; legacy JWT roles never populate this table."""

    __tablename__ = "company_memberships"
    company_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("company_directory.company_id"), primary_key=True
    )
    principal_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    role: Mapped[str] = mapped_column(String(10))
    principal_active: Mapped[bool] = mapped_column(Boolean, default=True)
    membership_active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (
        CheckConstraint(
            "role IN ('owner', 'admin', 'member', 'viewer')", name="ck_company_membership_role"
        ),
    )


class RegisteredWork(DirectoryBase):
    """Immutable task identity and partitioned parent/root lifetime allocations."""

    __tablename__ = "company_registered_work"
    company_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    task_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid)
    trace_id: Mapped[UUID] = mapped_column(Uuid)
    actor_id: Mapped[UUID] = mapped_column(Uuid)
    parent_task_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    root_task_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    allocation_usd: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    delegated_usd: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal(0))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "workspace_id"],
            ["company_directory.company_id", "company_directory.workspace_id"],
            name="fk_company_work_workspace",
        ),
        ForeignKeyConstraint(
            ["company_id", "actor_id"],
            ["company_memberships.company_id", "company_memberships.principal_id"],
            name="fk_company_work_actor",
        ),
        UniqueConstraint(
            "company_id", "task_id", "root_task_id", name="uq_company_work_root_scope"
        ),
        ForeignKeyConstraint(
            ["company_id", "root_task_id"],
            ["company_registered_work.company_id", "company_registered_work.task_id"],
            name="fk_company_work_root",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["company_id", "parent_task_id", "root_task_id"],
            [
                "company_registered_work.company_id",
                "company_registered_work.task_id",
                "company_registered_work.root_task_id",
            ],
            name="fk_company_work_parent_root",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            "allocation_usd >= 0 AND delegated_usd >= 0 AND delegated_usd <= allocation_usd",
            name="ck_company_work_allocation",
        ),
        CheckConstraint(
            "(parent_task_id IS NULL AND root_task_id = task_id) OR "
            "(parent_task_id IS NOT NULL AND parent_task_id <> task_id "
            "AND root_task_id <> task_id)",
            name="ck_company_work_lineage",
        ),
    )


class WorkPrincipal(DirectoryBase):
    """Current work grants referencing scoped membership and registered work."""

    __tablename__ = "company_work_principals"
    company_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    task_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    principal_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "task_id"],
            ["company_registered_work.company_id", "company_registered_work.task_id"],
            name="fk_company_work_principal_work",
        ),
        ForeignKeyConstraint(
            ["company_id", "principal_id"],
            ["company_memberships.company_id", "company_memberships.principal_id"],
            name="fk_company_work_principal_member",
        ),
    )

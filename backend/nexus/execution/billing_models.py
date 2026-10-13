"""Append-only billing evidence metadata; root supplies the company_007 migration."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from nexus.company.directory_models import DirectoryMembership
from nexus.execution.runtime_models import EffectIntent, ExecutionWork


class BillingEvidenceBase(DeclarativeBase):
    """Separate immutable provenance without modifying any known action receipt."""


class BillingEvidence(BillingEvidenceBase):
    """One observed charge for one exact known receipt, retained independently of its outcome."""

    __tablename__ = "company_billing_evidence"
    company_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    action_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    evidence_id: Mapped[UUID] = mapped_column(Uuid)
    task_id: Mapped[UUID] = mapped_column(Uuid)
    trace_id: Mapped[UUID] = mapped_column(Uuid)
    actor_id: Mapped[UUID] = mapped_column(Uuid)
    workspace_id: Mapped[UUID] = mapped_column(Uuid)
    run_id: Mapped[UUID] = mapped_column(Uuid)
    receipt_id: Mapped[UUID] = mapped_column(Uuid)
    receipt_hash: Mapped[str] = mapped_column(String(64))
    proposal_hash: Mapped[str] = mapped_column(String(64))
    external_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    price_version: Mapped[str] = mapped_column(String(500))
    currency: Mapped[str] = mapped_column(String(3))
    provider: Mapped[str] = mapped_column(String(500))
    source_observation_id: Mapped[str] = mapped_column(String(500))
    provider_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    invoice_reference: Mapped[str] = mapped_column(String(500))
    actual_usd: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    proof_json: Mapped[str] = mapped_column(Text)
    proof_sha256: Mapped[str] = mapped_column(String(64))
    observation_json: Mapped[str] = mapped_column(Text)
    observation_hash: Mapped[str] = mapped_column(String(64))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    owner_id: Mapped[UUID] = mapped_column(Uuid)
    operation_id: Mapped[UUID] = mapped_column(Uuid)
    operation_trace_id: Mapped[UUID] = mapped_column(Uuid)
    lease_fence: Mapped[int] = mapped_column(BigInteger)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "action_id"],
            [EffectIntent.__table__.c.company_id, EffectIntent.__table__.c.action_id],
            name="fk_company_billing_effect",
        ),
        ForeignKeyConstraint(
            ["company_id", "task_id", "run_id"],
            [
                ExecutionWork.__table__.c.company_id,
                ExecutionWork.__table__.c.task_id,
                ExecutionWork.__table__.c.run_id,
            ],
            name="fk_company_billing_run",
        ),
        ForeignKeyConstraint(
            ["company_id", "owner_id"],
            [
                DirectoryMembership.__table__.c.company_id,
                DirectoryMembership.__table__.c.principal_id,
            ],
            name="fk_company_billing_owner",
        ),
        UniqueConstraint("company_id", "evidence_id", name="uq_company_billing_evidence_id"),
        UniqueConstraint(
            "company_id",
            "provider",
            "source_observation_id",
            name="uq_company_billing_source_observation",
        ),
        CheckConstraint("currency = 'USD'", name="ck_company_billing_currency"),
        CheckConstraint("actual_usd >= 0 AND lease_fence > 0", name="ck_company_billing_amount"),
        CheckConstraint(
            "receipt_hash ~ '^[0-9a-f]{64}$' AND proposal_hash ~ '^[0-9a-f]{64}$' AND "
            "proof_sha256 ~ '^[0-9a-f]{64}$' AND observation_hash ~ '^[0-9a-f]{64}$'",
            name="ck_company_billing_hashes",
        ),
    )

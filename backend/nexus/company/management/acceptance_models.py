"""Independent acceptance/invalidation declarations, separate from M1 candidates and state."""

from uuid import UUID

from sqlalchemy import CheckConstraint, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.directory_models import DirectoryMembership
from nexus.company.management.model_base import CompanyRow, ManagementBase, RecordedRow, scoped_fk
from nexus.execution.runtime_models import EffectIntent, ExecutionWork


class ManagementWorkAcceptance(CompanyRow, RecordedRow, ManagementBase):
    """A future registered trusted publisher must resolve actual protected results before insert."""

    __tablename__ = "company_management_work_acceptances"
    acceptance_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    author_task_id: Mapped[UUID] = mapped_column(Uuid)
    author_run_id: Mapped[UUID] = mapped_column(Uuid)
    author_id: Mapped[UUID] = mapped_column(Uuid)
    verifier_task_id: Mapped[UUID] = mapped_column(Uuid)
    verifier_run_id: Mapped[UUID] = mapped_column(Uuid)
    verifier_id: Mapped[UUID] = mapped_column(Uuid)
    action_id: Mapped[UUID] = mapped_column(Uuid)
    receipt_id: Mapped[UUID] = mapped_column(Uuid)
    receipt_sha256: Mapped[str] = mapped_column(String(64))
    work_sha256: Mapped[str] = mapped_column(String(64))
    target_sha256: Mapped[str] = mapped_column(String(64))
    verdict: Mapped[str] = mapped_column(String(16))
    target_json: Mapped[str] = mapped_column(Text)
    result_json: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        Index("ix_management_acceptance_author", "company_id", "author_task_id", "author_run_id"),
        Index("ix_management_acceptance_action", "company_id", "action_id"),
        CheckConstraint(
            "author_id <> verifier_id AND author_task_id <> verifier_task_id AND "
            "verdict IN ('pass','reject','inconclusive')",
            name="ck_management_acceptance_independent_shape",
        ),
    )


class ManagementAcceptanceProof(CompanyRow, ManagementBase):
    __tablename__ = "company_management_acceptance_proofs"
    acceptance_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    proof_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    artifact_revision_id: Mapped[UUID] = mapped_column(Uuid)
    artifact_sha256: Mapped[str] = mapped_column(String(64))
    check_recipe: Mapped[str] = mapped_column(String(128))
    target_sha256: Mapped[str] = mapped_column(String(64))
    proof_json: Mapped[str] = mapped_column(Text)


class ManagementAcceptanceInvalidation(CompanyRow, RecordedRow, ManagementBase):
    __tablename__ = "company_management_acceptance_invalidations"
    invalidation_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    acceptance_id: Mapped[UUID] = mapped_column(Uuid)
    target_sha256: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(32))
    recorded_by: Mapped[UUID] = mapped_column(Uuid)
    __table_args__ = (
        Index("ix_management_acceptance_invalidation", "company_id", "acceptance_id"),
        CheckConstraint(
            "reason IN ('source_changed','criteria_changed','proof_unavailable',"
            "'scope_revoked','invalid_check')",
            name="ck_management_acceptance_invalidation_reason",
        ),
    )


for prefix in ("author", "verifier"):
    scoped_fk(
        ManagementWorkAcceptance.__table__,
        ("company_id", f"{prefix}_task_id", f"{prefix}_run_id"),
        ExecutionWork.__table__,
        ("company_id", "task_id", "run_id"),
        f"fk_management_acceptance_{prefix}_run",
    )
    scoped_fk(
        ManagementWorkAcceptance.__table__,
        ("company_id", f"{prefix}_id"),
        DirectoryMembership.__table__,
        ("company_id", "principal_id"),
        f"fk_management_acceptance_{prefix}_principal",
    )
scoped_fk(
    ManagementWorkAcceptance.__table__,
    ("company_id", "action_id"),
    EffectIntent.__table__,
    ("company_id", "action_id"),
    "fk_management_acceptance_issued_effect",
)
for row in (ManagementAcceptanceProof, ManagementAcceptanceInvalidation):
    scoped_fk(
        row.__table__,
        ("company_id", "acceptance_id"),
        ManagementWorkAcceptance.__table__,
        ("company_id", "acceptance_id"),
        f"fk_{row.__tablename__}_acceptance",
    )
scoped_fk(
    ManagementAcceptanceProof.__table__,
    ("company_id", "artifact_revision_id"),
    BrainArtifactRevision.__table__,
    ("company_id", "artifact_revision_id"),
    "fk_management_acceptance_protected_artifact",
)
scoped_fk(
    ManagementAcceptanceInvalidation.__table__,
    ("company_id", "recorded_by"),
    DirectoryMembership.__table__,
    ("company_id", "principal_id"),
    "fk_management_invalidation_principal",
)

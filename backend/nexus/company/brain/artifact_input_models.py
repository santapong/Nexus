"""Immutable native input artifact versions and resource constraints for derived outputs."""

from uuid import UUID

from sqlalchemy import CheckConstraint, Index, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from nexus.company.brain.access_models import BrainResource
from nexus.company.brain.model_base import BrainBase, CompanyRow
from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.management.model_base import scoped_fk


class BrainArtifactInput(CompanyRow, BrainBase):
    __tablename__ = "company_brain_artifact_inputs"
    artifact_revision_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    input_artifact_revision_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    __table_args__ = (
        Index("ix_brain_artifact_input_parent", "company_id", "input_artifact_revision_id"),
        CheckConstraint(
            "artifact_revision_id <> input_artifact_revision_id",
            name="ck_brain_artifact_input_distinct",
        ),
    )


class BrainArtifactResourceInput(CompanyRow, BrainBase):
    __tablename__ = "company_brain_artifact_resource_inputs"
    artifact_revision_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    resource_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    __table_args__ = (Index("ix_brain_artifact_resource_input", "company_id", "resource_id"),)


for table in (BrainArtifactInput, BrainArtifactResourceInput):
    scoped_fk(
        table.__table__,
        ("company_id", "artifact_revision_id"),
        BrainArtifactRevision.__table__,
        ("company_id", "artifact_revision_id"),
        f"fk_{table.__tablename__}_output",
    )
scoped_fk(
    BrainArtifactInput.__table__,
    ("company_id", "input_artifact_revision_id"),
    BrainArtifactRevision.__table__,
    ("company_id", "artifact_revision_id"),
    "fk_brain_artifact_input_parent",
)
scoped_fk(
    BrainArtifactResourceInput.__table__,
    ("company_id", "resource_id"),
    BrainResource.__table__,
    ("company_id", "resource_id"),
    "fk_brain_artifact_resource_input",
)

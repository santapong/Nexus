"""Artifact-resource ancestry denial remains a SQL predicate before source ranking/snippets."""

from uuid import UUID

from sqlalchemy import and_, case, exists, func, literal, or_, select, union
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import CTE, CompoundSelect

from nexus.company.brain.artifact_input_models import BrainArtifactInput, BrainArtifactResourceInput
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.derivation_models import BrainDerivationEvidence, BrainDerivationSource
from nexus.company.brain.source_models import (
    BrainArtifactRevision,
    BrainSource,
    BrainSourceRevision,
)


def artifact_closure(company: UUID) -> CTE:
    seed = select(
        BrainArtifactRevision.artifact_revision_id.label("root"),
        BrainArtifactRevision.artifact_revision_id.label("node"),
        literal(0).label("depth"),
    ).where(BrainArtifactRevision.company_id == company)
    closure = seed.cte(recursive=True)
    return closure.union(
        select(
            closure.c.root,
            BrainArtifactInput.input_artifact_revision_id,
            (closure.c.depth + 1).label("depth"),
        )
        .select_from(
            closure.join(
                BrainArtifactInput,
                and_(
                    BrainArtifactInput.company_id == company,
                    BrainArtifactInput.artifact_revision_id == closure.c.node,
                ),
            )
        )
        .where(closure.c.depth < 16)
    )


def _rank(column: object) -> ColumnElement[int]:
    # ColumnElement is imported at the SQL boundary, not supplied by caller input.
    from typing import Any, cast

    value = cast(ColumnElement[Any], column)
    return case(
        (value == "public", 0),
        (value == "internal", 1),
        (value == "confidential", 2),
        (value == "restricted", 3),
        else_=0,
    )


def artifact_input_denials(
    scope: BrainReadScope, source_tree: CTE, readable: CTE
) -> CompoundSelect[tuple[UUID]]:
    """Every source closure's artifact inputs retain their own resource/classification needs."""
    # Complete joins stay together to keep all native company predicates visible.
    inputs = artifact_closure(scope.company_id)
    revision = BrainSourceRevision.__table__.alias("artifact_input_source_revision")
    source = BrainSource.__table__.alias("artifact_input_source")
    parent = BrainArtifactRevision.__table__.alias("artifact_input_parent")
    base = (
        source_tree.join(
            revision,
            and_(
                revision.c.company_id == scope.company_id,
                revision.c.source_revision_id == source_tree.c.node,
            ),
        )
        .join(
            source,
            and_(
                source.c.company_id == scope.company_id, source.c.source_id == revision.c.source_id
            ),
        )
        .join(inputs, inputs.c.root == revision.c.artifact_revision_id)
    )
    artifacts = (
        select(source_tree.c.root)
        .select_from(
            base.join(
                parent,
                and_(
                    parent.c.company_id == scope.company_id,
                    parent.c.artifact_revision_id == inputs.c.node,
                ),
            )
        )
        .where(
            or_(
                parent.c.resource_id.not_in(select(readable.c.resource_id)),
                _rank(parent.c.data_classification) > _rank(source.c.data_classification),
            )
        )
    )
    resources = (
        select(source_tree.c.root)
        .select_from(
            base.join(
                BrainArtifactResourceInput,
                and_(
                    BrainArtifactResourceInput.company_id == scope.company_id,
                    BrainArtifactResourceInput.artifact_revision_id == inputs.c.node,
                ),
            )
        )
        .where(BrainArtifactResourceInput.resource_id.not_in(select(readable.c.resource_id)))
    )
    excessive = (
        select(source_tree.c.root)
        .select_from(base)
        .group_by(source_tree.c.root)
        .having(or_(func.max(inputs.c.depth) >= 16, func.count(func.distinct(inputs.c.node)) > 33))
    )
    qualified = or_(
        exists(
            select(BrainSourceRevision.source_revision_id).where(
                BrainSourceRevision.company_id == scope.company_id,
                BrainSourceRevision.artifact_revision_id == parent.c.artifact_revision_id,
            )
        ),
        exists(
            select(BrainDerivationSource.derivation_id).where(
                BrainDerivationSource.company_id == scope.company_id,
                BrainDerivationSource.derivation_id == parent.c.derivation_id,
            )
        ),
        exists(
            select(BrainDerivationEvidence.derivation_id).where(
                BrainDerivationEvidence.company_id == scope.company_id,
                BrainDerivationEvidence.derivation_id == parent.c.derivation_id,
            )
        ),
    )
    has_parent = exists(
        select(BrainArtifactInput.input_artifact_revision_id).where(
            BrainArtifactInput.company_id == scope.company_id,
            BrainArtifactInput.artifact_revision_id == parent.c.artifact_revision_id,
        )
    )
    missing_origin = (
        select(source_tree.c.root)
        .select_from(
            base.join(
                parent,
                and_(
                    parent.c.company_id == scope.company_id,
                    parent.c.artifact_revision_id == inputs.c.node,
                ),
            )
        )
        .where(~has_parent, ~qualified)
    )
    return union(artifacts, resources, excessive, missing_origin)

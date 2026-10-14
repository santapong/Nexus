"""Company/complete-contributor ACL predicates precede FTS rank and candidate limits."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, and_, func, literal, or_, select, union
from sqlalchemy.sql.selectable import CTE

from nexus.company.brain.access_support import readable_resource_ids
from nexus.company.brain.artifact_input_sql import artifact_closure, artifact_input_denials
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.models import (
    BrainArtifactRevision,
    BrainClaimEvidence,
    BrainClaimHead,
    BrainClaimRevision,
    BrainDerivation,
    BrainDerivationEvidence,
    BrainDerivationSource,
    BrainEvidence,
    BrainSource,
    BrainSourceHead,
    BrainSourceRevision,
)
from nexus.company.brain.retrieval import SearchRequest


# These declarative joins exceed 50 lines to keep both complete contributor paths
# visible together; neither SQL branch can grant access without the closure predicate.
def source_dependencies(company: UUID) -> CTE:
    """Both source and artifact derivations contribute; never choose just one by coalesce."""
    revision = BrainSourceRevision.__table__.alias("dependency_parent")
    artifact = BrainArtifactRevision.__table__.alias("dependency_artifact")
    direct = BrainDerivationSource.__table__.alias("dependency_source")
    linked = BrainDerivationEvidence.__table__.alias("dependency_evidence")
    evidence = BrainEvidence.__table__.alias("dependency_citation")
    lineage = artifact_closure(company)
    parent = revision.join(lineage, lineage.c.root == revision.c.artifact_revision_id).join(
        artifact,
        and_(
            artifact.c.company_id == revision.c.company_id,
            artifact.c.artifact_revision_id == lineage.c.node,
        ),
    )
    sources = (
        select(
            revision.c.source_revision_id.label("parent"),
            direct.c.source_revision_id.label("child"),
        )
        .select_from(
            parent.join(
                direct,
                and_(
                    direct.c.company_id == company,
                    or_(
                        direct.c.derivation_id == revision.c.derivation_id,
                        direct.c.derivation_id == artifact.c.derivation_id,
                    ),
                ),
            )
        )
        .where(revision.c.company_id == company)
    )
    citations = (
        select(
            revision.c.source_revision_id.label("parent"),
            evidence.c.source_revision_id.label("child"),
        )
        .select_from(
            parent.join(
                linked,
                and_(
                    linked.c.company_id == company,
                    or_(
                        linked.c.derivation_id == revision.c.derivation_id,
                        linked.c.derivation_id == artifact.c.derivation_id,
                    ),
                ),
            ).join(
                evidence,
                and_(
                    evidence.c.company_id == company, evidence.c.evidence_id == linked.c.evidence_id
                ),
            )
        )
        .where(revision.c.company_id == company)
    )
    inherited = BrainSourceRevision.__table__.alias("artifact_input_source_dependency")
    originals = (
        select(
            revision.c.source_revision_id.label("parent"),
            inherited.c.source_revision_id.label("child"),
        )
        .select_from(
            parent.join(
                inherited,
                and_(
                    inherited.c.company_id == company,
                    inherited.c.artifact_revision_id == artifact.c.artifact_revision_id,
                ),
            )
        )
        .where(
            revision.c.company_id == company,
            inherited.c.source_revision_id != revision.c.source_revision_id,
        )
    )
    return union(sources, citations, originals).cte()


def source_closure(company: UUID) -> CTE:
    """UNION deduplicates repeated DAG visits; a depth16 tail denies cycles/overflow."""
    dependencies = source_dependencies(company)
    seed = select(
        BrainSourceRevision.source_revision_id.label("root"),
        BrainSourceRevision.source_revision_id.label("node"),
        literal(0).label("depth"),
    ).where(BrainSourceRevision.company_id == company)
    closure = seed.cte(recursive=True)
    return closure.union(
        select(closure.c.root, dependencies.c.child, (closure.c.depth + 1).label("depth"))
        .select_from(closure.join(dependencies, dependencies.c.parent == closure.c.node))
        .where(closure.c.depth < 16)
    )


# Keep the complete before-rank denial predicate together despite its 50-line boundary.
def eligible_sources(scope: BrainReadScope, now: datetime) -> Select[tuple[UUID]]:
    """Exclude inaccessible direct/derived resources and incomplete provenance before rank."""
    closure = source_closure(scope.company_id)
    readable = readable_resource_ids(scope, now).cte()
    revision = BrainSourceRevision.__table__.alias("closure_revision")
    source = BrainSource.__table__.alias("closure_source")
    artifact = BrainArtifactRevision.__table__.alias("closure_artifact")
    rows = (
        closure.join(
            revision,
            and_(
                revision.c.company_id == scope.company_id,
                revision.c.source_revision_id == closure.c.node,
            ),
        )
        .join(
            source,
            and_(
                source.c.company_id == scope.company_id, source.c.source_id == revision.c.source_id
            ),
        )
        .join(
            artifact,
            and_(
                artifact.c.company_id == scope.company_id,
                artifact.c.artifact_revision_id == revision.c.artifact_revision_id,
            ),
        )
    )
    unreadable = (
        select(closure.c.root)
        .select_from(rows)
        .where(
            or_(
                source.c.resource_id.not_in(select(readable.c.resource_id)),
                artifact.c.resource_id.not_in(select(readable.c.resource_id)),
            )
        )
    )
    excessive = (
        select(closure.c.root)
        .group_by(closure.c.root)
        .having(
            or_(func.max(closure.c.depth) >= 16, func.count(func.distinct(closure.c.node)) > 32)
        )
    )
    derived = _bad_derivations(scope, closure, readable)
    artifact_inputs = artifact_input_denials(scope, closure, readable)
    bad = union(unreadable, excessive, derived, *artifact_inputs.selects).cte()
    return select(BrainSourceRevision.source_revision_id).where(
        BrainSourceRevision.company_id == scope.company_id,
        BrainSourceRevision.source_revision_id.not_in(select(bad.c.root)),
    )


# The company-scoped aliases and absence checks form one declarative SQL predicate;
# splitting its 73 lines would hide a required provenance denial branch.
def _bad_derivations(
    scope: BrainReadScope,
    closure: CTE,
    readable: CTE,
) -> Select[tuple[UUID]]:
    """Typed Core aliases are constructed locally; artifact/edge absence never means public."""
    # Core table aliases are intentionally constructed here to preserve SQL column
    # provenance rather than accepting arbitrary expressions from caller input.
    revision = BrainSourceRevision.__table__.alias("closure_revision")
    artifact = BrainArtifactRevision.__table__.alias("closure_artifact")
    derivation = BrainDerivation.__table__.alias("closure_derivation")
    target = BrainArtifactRevision.__table__.alias("derivation_target")
    sources = BrainDerivationSource.__table__.alias("derivation_source_check")
    evidence = BrainDerivationEvidence.__table__.alias("derivation_evidence_check")
    joined = (
        closure.join(
            revision,
            and_(
                revision.c.company_id == scope.company_id,
                revision.c.source_revision_id == closure.c.node,
            ),
        )
        .join(
            artifact,
            and_(
                artifact.c.company_id == scope.company_id,
                artifact.c.artifact_revision_id == revision.c.artifact_revision_id,
            ),
        )
        .join(
            derivation,
            and_(
                derivation.c.company_id == scope.company_id,
                or_(
                    derivation.c.derivation_id == revision.c.derivation_id,
                    derivation.c.derivation_id == artifact.c.derivation_id,
                ),
            ),
        )
        .join(
            target,
            and_(
                target.c.company_id == scope.company_id,
                target.c.artifact_revision_id == derivation.c.artifact_revision_id,
            ),
        )
    )
    has_sources = (
        select(literal(1))
        .where(
            sources.c.company_id == scope.company_id,
            sources.c.derivation_id == derivation.c.derivation_id,
        )
        .exists()
    )
    has_evidence = (
        select(literal(1))
        .where(
            evidence.c.company_id == scope.company_id,
            evidence.c.derivation_id == derivation.c.derivation_id,
        )
        .exists()
    )
    return (
        select(closure.c.root)
        .select_from(joined)
        .where(
            or_(
                target.c.resource_id.not_in(select(readable.c.resource_id)),
                and_(~has_sources, ~has_evidence),
            )
        )
    )


def evidence_ids(
    scope: BrainReadScope, now: datetime, request: SearchRequest
) -> Select[tuple[UUID]]:
    """Current heads and optional allowed claim-kind filters still apply to exact IDs."""
    statement = (
        select(BrainEvidence.evidence_id)
        .join(
            BrainSourceHead,
            and_(
                BrainSourceHead.company_id == scope.company_id,
                BrainSourceHead.source_id == BrainEvidence.source_id,
            ),
        )
        .where(
            BrainEvidence.company_id == scope.company_id,
            BrainEvidence.source_revision_id.in_(eligible_sources(scope, now)),
        )
    )
    if not request.include_history:
        statement = statement.where(
            BrainSourceHead.current_revision_id == BrainEvidence.source_revision_id,
            BrainSourceHead.availability == "available",
        )
    if request.claim_kinds:
        statement = statement.where(
            BrainEvidence.evidence_id.in_(_claim_evidence(scope, now, request))
        )
    return statement


def _claim_evidence(
    scope: BrainReadScope, now: datetime, request: SearchRequest
) -> Select[tuple[UUID]]:
    statement = (
        select(BrainClaimEvidence.evidence_id)
        .join(
            BrainClaimRevision,
            and_(
                BrainClaimRevision.company_id == scope.company_id,
                BrainClaimRevision.claim_revision_id == BrainClaimEvidence.claim_revision_id,
            ),
        )
        .where(
            BrainClaimEvidence.company_id == scope.company_id,
            BrainClaimRevision.kind.in_(request.claim_kinds),
            BrainClaimRevision.resource_id.in_(readable_resource_ids(scope, now)),
            or_(
                BrainClaimRevision.validity_start.is_(None),
                BrainClaimRevision.validity_start <= now,
            ),
            or_(BrainClaimRevision.validity_end.is_(None), BrainClaimRevision.validity_end > now),
        )
    )
    if not request.include_history:
        statement = statement.join(
            BrainClaimHead,
            and_(
                BrainClaimHead.company_id == scope.company_id,
                BrainClaimHead.current_revision_id == BrainClaimRevision.claim_revision_id,
            ),
        )
    return statement

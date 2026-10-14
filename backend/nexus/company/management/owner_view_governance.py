"""Native governance declarations survive source-field redaction without fabricating facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.commitment_support import (
    commitment_record,
    require_commitment_binding,
)
from nexus.company.management.goals import GoalDefinition, GoalRevisionRef
from nexus.company.management.governance_models import ManagementGoalHead, ManagementGoalRevision
from nexus.company.management.operation_models import ManagementCommitmentRevision
from nexus.company.management.owner_view_contracts import CommitmentView, GoalMetricView, GoalView
from nexus.company.management.owner_view_sources import (
    OwnerViewSources,
    SourceDisclosure,
    evidence_artifacts,
    source_disclosure,
)
from nexus.company.management.transactions import ManagementDeniedError
from nexus.harness.journal_models import CompanyControl


@dataclass(frozen=True)
class GoalObservation:
    value: GoalView
    disclosures: tuple[SourceDisclosure | None, ...]

    def render(self, now: datetime) -> GoalView:
        metrics = tuple(
            metric
            if authority is not None and authority.permits(now)
            else metric.model_copy(update={"baseline": None})
            for metric, authority in zip(self.value.metrics, self.disclosures, strict=True)
        )
        return GoalView.model_validate_json(
            self.value.model_copy(update={"metrics": metrics}).model_dump_json()
        )


async def observe_goal(
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    row: ManagementGoalRevision,
    active: bool,
    sources: OwnerViewSources | None,
) -> GoalObservation:
    definition = GoalDefinition.model_validate_json(row.payload_json)
    if (row.company_id, row.goal_id, row.sha256, row.actionable_at) != (
        scope.company_id,
        definition.goal_id,
        canonical_sha256(definition),
        definition.due.actionable_at,
    ):
        raise ManagementDeniedError("Owner goal native declaration differs")
    reference = GoalRevisionRef(
        company_id=scope.company_id,
        goal_id=row.goal_id,
        revision_id=row.revision_id,
        version=row.version,
        sha256=row.sha256,
    )
    metrics, disclosures = await _metric_views(
        session, control, scope, identity, definition, sources
    )
    return GoalObservation(
        GoalView(
            company_id=scope.company_id,
            reference=reference,
            active=active,
            title=definition.title,
            responsible_id=definition.owner_id,
            due=definition.due,
            metrics=tuple(metrics),
        ),
        tuple(disclosures),
    )


async def _metric_views(
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    definition: GoalDefinition,
    sources: OwnerViewSources | None,
) -> tuple[tuple[GoalMetricView, ...], tuple[SourceDisclosure | None, ...]]:
    metrics, disclosures = [], []
    for metric in definition.metrics:
        refs = await evidence_artifacts(session, scope, metric.baseline.evidence)
        disclosure = (
            await source_disclosure(session, control, scope, identity, sources, refs)
            if refs is not None
            else None
        )
        metrics.append(
            GoalMetricView(
                metric_id=metric.metric_id,
                unit=metric.unit,
                comparator=metric.comparator,
                target=metric.target,
                baseline=metric.baseline if disclosure is not None else None,
            )
        )
        disclosures.append(disclosure)
    return tuple(metrics), tuple(disclosures)


async def observe_commitment(
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    row: ManagementCommitmentRevision,
) -> CommitmentView:
    record = commitment_record(row)
    head = await session.get(ManagementGoalHead, (scope.company_id, record.definition.goal.goal_id))
    if head is not None and not head.active:
        return CommitmentView(revision=record, binding_state="inactive")
    try:
        await require_commitment_binding(session, control, scope, record.definition)
    except ValueError:
        return CommitmentView(revision=record, binding_state="stale")
    return CommitmentView(revision=record, binding_state="current")

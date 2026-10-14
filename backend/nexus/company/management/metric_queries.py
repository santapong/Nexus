"""Current measurement discovery under one owner mutex and aggregate final deadline fence."""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.control_support import db_clock
from nexus.company.management.metric_capture import capture_metric
from nexus.company.management.metric_contracts import (
    MetricCurrentObservation,
    MetricObservationRecord,
    MetricSnapshot,
    MetricUnknownReason,
    UnknownMetricValue,
)
from nexus.company.management.metric_models import ManagementMetricObservation
from nexus.company.management.metric_persistence import observation_record
from nexus.company.management.metric_query_contracts import (
    MAX_METRIC_PAGE_BYTES,
    MetricObservationPage,
)
from nexus.company.management.metric_read import unavailable_snapshot
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.company.management.transactions import (
    ManagementDeniedError,
    management_owner_transaction,
)
from nexus.harness.journal_models import CompanyControl


@dataclass(frozen=True)
class PageCandidate:
    record: MetricObservationRecord
    snapshot: MetricSnapshot
    deadlines: tuple[datetime, ...]


def validate_page_limit(value: object) -> int:
    if type(value) is not int or not 1 <= value <= 8:
        raise ValueError("Metric page limit must be an integer from1to8")
    return value


class MetricQueries:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        catalog: PlanAdmissionCatalog,
        artifacts: BoundedArtifactReader,
        freshness: RegisteredSourceFreshness,
    ) -> None:
        self.factory, self.artifacts, self.freshness = factory, artifacts, freshness
        self.catalog = PlanAdmissionCatalog.model_validate_json(catalog.model_dump_json())

    async def current_page(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        goal_id: UUID,
        *,
        after_id: UUID | None = None,
        limit: int = 4,
    ) -> MetricObservationPage:
        limit = validate_page_limit(limit)
        if self.catalog.company_id != scope.company_id:
            raise ManagementDeniedError("Metric discovery company is unavailable")
        async with (
            asyncio.timeout(30),
            management_owner_transaction(
                self.factory,
                scope,
                identity,
                allow_paused=True,
            ) as (session, control, _),
        ):
            rows = await scoped_rows(session, scope, goal_id, after_id, limit)
            candidates = tuple(
                [
                    await self._candidate(
                        session, control, scope, identity, observation_record(row)
                    )
                    for row in rows[:limit]
                ]
            )
            final = await db_clock(session)
            return bounded_page(
                scope,
                goal_id,
                candidates,
                rows[limit - 1].observation_id if len(rows) > limit else None,
                final,
            )

    async def _candidate(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        record: MetricObservationRecord,
    ) -> PageCandidate:
        try:
            captured = await capture_metric(
                session,
                control,
                scope,
                identity,
                record.snapshot.request,
                self.catalog,
                self.artifacts,
                self.freshness,
            )
        except ValueError:
            return PageCandidate(record, unavailable_snapshot(record.snapshot), ())
        return PageCandidate(record, captured.snapshot, captured.protection.deadlines)


async def scoped_rows(
    session: AsyncSession,
    scope: CompanyControlScope,
    goal_id: UUID,
    after_id: UUID | None,
    limit: int,
) -> tuple[ManagementMetricObservation, ...]:
    query = select(ManagementMetricObservation).where(
        ManagementMetricObservation.company_id == scope.company_id,
        ManagementMetricObservation.goal_id == goal_id,
    )
    if after_id is not None:
        cursor = await session.get(ManagementMetricObservation, (scope.company_id, after_id))
        if cursor is None or cursor.goal_id != goal_id:
            raise ManagementDeniedError("Metric discovery cursor is unavailable")
        query = query.where(
            or_(
                ManagementMetricObservation.observed_at < cursor.observed_at,
                and_(
                    ManagementMetricObservation.observed_at == cursor.observed_at,
                    ManagementMetricObservation.observation_id < cursor.observation_id,
                ),
            )
        )
    rows = tuple(
        (
            await session.scalars(
                query.order_by(
                    ManagementMetricObservation.observed_at.desc(),
                    ManagementMetricObservation.observation_id.desc(),
                ).limit(limit + 1)
            )
        ).all()
    )
    return rows


def mask(snapshot: MetricSnapshot, reason: MetricUnknownReason) -> MetricSnapshot:
    safe = unavailable_snapshot(snapshot)
    comparison = safe.comparison.model_copy(update={"value": UnknownMetricValue(reason=reason)})
    return MetricSnapshot.model_validate_json(
        safe.model_copy(update={"comparison": comparison}).model_dump_json()
    )


def projection(
    candidate: PageCandidate, checked_at: datetime, *, force_mask: bool = False
) -> MetricCurrentObservation:
    snapshot = candidate.snapshot
    if force_mask:
        snapshot = mask(snapshot, "scope_unavailable")
    elif any(deadline <= checked_at for deadline in candidate.deadlines):
        snapshot = mask(snapshot, "proof_unavailable")
    return MetricCurrentObservation(
        company_id=candidate.record.company_id,
        observation_id=candidate.record.observation_id,
        snapshot=snapshot,
        snapshot_sha256=canonical_sha256(snapshot),
        recorded_at=candidate.record.observed_at,
        checked_at=checked_at,
        comparison_result=snapshot.comparison.result,
        baseline_change=snapshot.comparison.baseline_change,
    )


def bounded_page(
    scope: CompanyControlScope,
    goal_id: UUID,
    candidates: tuple[PageCandidate, ...],
    next_after_id: UUID | None,
    checked_at: datetime,
) -> MetricObservationPage:
    items = [projection(item, checked_at) for item in candidates]
    page = MetricObservationPage(
        company_id=scope.company_id,
        goal_id=goal_id,
        checked_at=checked_at,
        observations=tuple(items),
        next_after_id=next_after_id,
    )
    for index in sorted(
        range(len(items)), key=lambda i: len(items[i].model_dump_json().encode()), reverse=True
    ):
        if len(page.model_dump_json().encode()) <= MAX_METRIC_PAGE_BYTES:
            return page
        items[index] = projection(candidates[index], checked_at, force_mask=True)
        page = MetricObservationPage.model_validate_json(
            page.model_copy(update={"observations": tuple(items)}).model_dump_json()
        )
    if len(page.model_dump_json().encode()) > MAX_METRIC_PAGE_BYTES:
        raise ManagementDeniedError("Metric current page exceeds its bounded representation")
    return page

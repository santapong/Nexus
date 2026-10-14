"""Owner-only immutable native measurements; no completion, budget or execution authority."""

import asyncio
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.control_support import ManagementConflictError, db_clock
from nexus.company.management.metric_capture import CapturedMetric, capture_metric
from nexus.company.management.metric_contracts import (
    MetricCurrentObservation,
    MetricObservationRecord,
    MetricObservationRequest,
)
from nexus.company.management.metric_models import ManagementMetricObservation
from nexus.company.management.metric_persistence import observation_record, write_observation
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.company.management.transactions import (
    ManagementDeniedError,
    management_owner_transaction,
)
from nexus.harness.journal_models import CompanyControl

METRIC_TIMEOUT_SECONDS = 30


class MetricStore:
    """Only configured native read gates produce facts; caller input cannot provide the value."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        catalog: PlanAdmissionCatalog,
        artifacts: BoundedArtifactReader,
        freshness: RegisteredSourceFreshness,
    ) -> None:
        self.factory, self.artifacts, self.freshness = factory, artifacts, freshness
        self.catalog = PlanAdmissionCatalog.model_validate_json(catalog.model_dump_json())

    async def observe(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        request: MetricObservationRequest,
    ) -> MetricObservationRecord:
        request = MetricObservationRequest.model_validate_json(request.model_dump_json())
        if request.company_id != scope.company_id or self.catalog.company_id != scope.company_id:
            raise ManagementDeniedError("Metric company is unavailable")
        async with (
            asyncio.timeout(METRIC_TIMEOUT_SECONDS),
            management_owner_transaction(
                self.factory,
                scope,
                identity,
                allow_paused=True,
            ) as (session, control, _),
        ):
            captured = await capture_metric(
                session,
                control,
                scope,
                identity,
                request,
                self.catalog,
                self.artifacts,
                self.freshness,
            )
            return await self._commit(session, control, scope, request, captured)

    async def _commit(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: CompanyControlScope,
        request: MetricObservationRequest,
        captured: CapturedMetric,
    ) -> MetricObservationRecord:
        prior = await session.get(
            ManagementMetricObservation, (scope.company_id, request.observation_id)
        )
        if prior is not None:
            old = observation_record(prior)
            require_exact_replay(old, scope, control.owner_id, request, captured)
            captured.protection.require_time(await db_clock(session))
            return old
        operation = await session.scalar(
            select(ManagementMetricObservation.observation_id).where(
                ManagementMetricObservation.company_id == scope.company_id,
                ManagementMetricObservation.operation_id == scope.operation_id,
            )
        )
        if operation is not None:
            raise ManagementConflictError(
                "Metric audit operation already binds another observation"
            )
        now = await db_clock(session)
        record = MetricObservationRecord(
            company_id=scope.company_id,
            observation_id=request.observation_id,
            snapshot=captured.snapshot,
            snapshot_sha256=canonical_sha256(captured.snapshot),
            recorded_by=control.owner_id,
            operation_id=scope.operation_id,
            audit_trace_id=scope.trace_id,
            observed_at=now,
        )
        await write_observation(session, record)
        captured.protection.require_time(await db_clock(session))
        return record

    async def get_saved(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        observation_id: UUID,
    ) -> MetricObservationRecord | None:
        from nexus.company.management.metric_read import require_saved_read

        async with (
            asyncio.timeout(METRIC_TIMEOUT_SECONDS),
            management_owner_transaction(self.factory, scope, identity, allow_paused=True) as (
                session,
                control,
                _,
            ),
        ):
            row = await session.get(ManagementMetricObservation, (scope.company_id, observation_id))
            if row is None:
                return None
            record = observation_record(row)
            await require_saved_read(
                session, control, scope, identity, record, self.artifacts, self.freshness
            )
            return record

    async def current(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        observation_id: UUID,
    ) -> MetricCurrentObservation | None:
        from nexus.company.management.metric_read import current_record

        async with (
            asyncio.timeout(METRIC_TIMEOUT_SECONDS),
            management_owner_transaction(
                self.factory,
                scope,
                identity,
                allow_paused=True,
            ) as (session, control, _),
        ):
            row = await session.get(ManagementMetricObservation, (scope.company_id, observation_id))
            if row is None:
                return None
            return await current_record(
                session,
                control,
                scope,
                identity,
                observation_record(row),
                self.catalog,
                self.artifacts,
                self.freshness,
            )


def require_exact_replay(
    old: MetricObservationRecord,
    scope: CompanyControlScope,
    actual_owner: UUID,
    request: MetricObservationRequest,
    captured: CapturedMetric,
) -> None:
    if (
        old.snapshot.request != request
        or old.snapshot_sha256 != canonical_sha256(captured.snapshot)
        or (old.operation_id, old.audit_trace_id, old.recorded_by)
        != (scope.operation_id, scope.trace_id, actual_owner)
    ):
        raise ManagementConflictError(
            "Metric replay binds another immutable request or audit identity"
        )

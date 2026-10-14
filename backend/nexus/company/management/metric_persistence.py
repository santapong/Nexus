"""Exact immutable native measurement envelope encoding; caller owns company mutex."""

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.metric_contracts import MetricObservationRecord
from nexus.company.management.metric_models import ManagementMetricObservation
from nexus.company.management.transactions import ManagementDeniedError


def observation_record(row: ManagementMetricObservation) -> MetricObservationRecord:
    record = MetricObservationRecord.model_validate_json(row.record_json)
    request, value = record.snapshot.request, record.snapshot.comparison.value
    if (
        (
            record.company_id,
            record.observation_id,
            request.goal.goal_id,
            request.goal.revision_id,
            request.plan.plan_id,
            request.plan.plan_revision_id,
            request.metric_id,
            record.snapshot.recipe,
            len(request.task_ids),
            value.kind,
            value.value if value.kind == "known" else None,
            canonical_sha256(request),
            record.snapshot_sha256,
            canonical_sha256(record),
            record.recorded_by,
            record.operation_id,
            record.audit_trace_id,
            record.observed_at,
        )
        != (
            row.company_id,
            row.observation_id,
            row.goal_id,
            row.goal_revision_id,
            row.plan_id,
            row.plan_revision_id,
            row.metric_id,
            row.recipe,
            row.selection_count,
            row.value_kind,
            row.count_value,
            row.request_sha256,
            row.snapshot_sha256,
            row.record_sha256,
            row.recorded_by,
            row.operation_id,
            row.audit_trace_id,
            row.observed_at,
        )
        or row.request_json != request.model_dump_json()
        or row.recorded_at != record.observed_at
    ):
        raise ManagementDeniedError("Stored metric observation differs from native envelope")
    return record


async def write_observation(session: AsyncSession, record: MetricObservationRecord) -> None:
    request, value = record.snapshot.request, record.snapshot.comparison.value
    raw = record.model_dump_json()
    if len(raw.encode()) > 4194304:
        raise ManagementDeniedError("Native metric observation exceeds its bound")
    session.add(
        ManagementMetricObservation(
            company_id=record.company_id,
            observation_id=record.observation_id,
            goal_id=request.goal.goal_id,
            goal_revision_id=request.goal.revision_id,
            plan_id=request.plan.plan_id,
            plan_revision_id=request.plan.plan_revision_id,
            metric_id=request.metric_id,
            recipe=record.snapshot.recipe,
            selection_count=len(request.task_ids),
            value_kind=value.kind,
            count_value=value.value if value.kind == "known" else None,
            request_sha256=canonical_sha256(request),
            snapshot_sha256=record.snapshot_sha256,
            record_sha256=canonical_sha256(record),
            request_json=request.model_dump_json(),
            record_json=raw,
            recorded_by=record.recorded_by,
            operation_id=record.operation_id,
            audit_trace_id=record.audit_trace_id,
            observed_at=record.observed_at,
            recorded_at=record.observed_at,
        )
    )
    await session.flush()

"""Dated licensed history and freshly rederived known/unknown metric projections."""

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.acceptance_models import ManagementWorkAcceptance
from nexus.company.management.acceptance_persistence import acceptance_record
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.control_support import db_clock
from nexus.company.management.goals import UnknownBaseline
from nexus.company.management.metric_capture import capture_metric
from nexus.company.management.metric_contracts import (
    MetricComparison,
    MetricCurrentObservation,
    MetricObservationRecord,
    MetricSnapshot,
    MetricWorkFact,
    UnknownMetricValue,
)
from nexus.company.management.metric_provenance import protect_facts
from nexus.company.management.owner_view_sources import OwnerViewSources
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.company.management.transactions import ManagementDeniedError
from nexus.harness.journal_models import CompanyControl


async def require_saved_read(
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    record: MetricObservationRecord,
    artifacts: BoundedArtifactReader,
    freshness: RegisteredSourceFreshness,
) -> None:
    from nexus.company.management.owner_view_sources import evidence_artifacts

    await require_native_history(session, record)
    refs = await evidence_artifacts(session, scope, record.snapshot.comparison.baseline.evidence)
    if refs is None:
        raise ManagementDeniedError("Metric history source is unavailable")
    protected = await protect_facts(
        session,
        control,
        scope,
        identity,
        OwnerViewSources(artifacts, freshness),
        record.snapshot.work,
        refs,
        record.snapshot.resources,
    )
    if protected is None:
        raise ManagementDeniedError("Metric history source permission is unavailable")
    final = await db_clock(session)
    if any(value <= final for value in protected.deadlines):
        raise ManagementDeniedError("Metric history source permission expired")


async def current_record(
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    record: MetricObservationRecord,
    catalog: PlanAdmissionCatalog,
    artifacts: BoundedArtifactReader,
    freshness: RegisteredSourceFreshness,
) -> MetricCurrentObservation:
    try:
        captured = await capture_metric(
            session,
            control,
            scope,
            identity,
            record.snapshot.request,
            catalog,
            artifacts,
            freshness,
        )
        checked_at = await db_clock(session)
        captured.protection.require_time(checked_at)
    except ValueError:
        snapshot = unavailable_snapshot(record.snapshot)
        checked_at = await db_clock(session)
    else:
        snapshot = captured.snapshot
    return MetricCurrentObservation(
        company_id=scope.company_id,
        observation_id=record.observation_id,
        snapshot=snapshot,
        snapshot_sha256=canonical_sha256(snapshot),
        recorded_at=record.observed_at,
        checked_at=checked_at,
        comparison_result=snapshot.comparison.result,
        baseline_change=snapshot.comparison.baseline_change,
    )


def unavailable_snapshot(previous: MetricSnapshot) -> MetricSnapshot:
    facts = tuple(
        MetricWorkFact(
            company_id=previous.company_id,
            work=entry.work,
            registration_sha256=entry.registration_sha256,
            acceptance_id=None,
            acceptance_sha256=None,
            receipt_id=None,
            status="unknown",
        )
        for entry in previous.work
    )
    return MetricSnapshot(
        company_id=previous.company_id,
        request=previous.request,
        recipe=previous.recipe,
        comparison=MetricComparison(
            value=UnknownMetricValue(reason="versions_stale"),
            comparator=previous.comparison.comparator,
            target=previous.comparison.target,
            baseline=UnknownBaseline(reason="Current native selection is unavailable"),
        ),
        work=facts,
    )


async def require_native_history(session: AsyncSession, record: MetricObservationRecord) -> None:
    for fact in record.snapshot.work:
        if fact.status != "accepted_report":
            continue
        row = await session.get(ManagementWorkAcceptance, (record.company_id, fact.acceptance_id))
        if row is None:
            raise ManagementDeniedError("Metric historical proof is unavailable")
        accepted = acceptance_record(row)
        if (
            accepted.target.author != fact.work
            or accepted.target.work_snapshot_sha256 != fact.registration_sha256
            or canonical_sha256(accepted) != fact.acceptance_sha256
            or accepted.target.receipt_id != fact.receipt_id
            or accepted.recorded_at != fact.accepted_at
            or tuple(item.proof_id for item in accepted.proofs) != fact.proof_ids
            or (*accepted.target.artifacts, *(item.result_artifact for item in accepted.proofs))
            != fact.artifacts
        ):
            raise ManagementDeniedError("Metric history differs from immutable native proof")

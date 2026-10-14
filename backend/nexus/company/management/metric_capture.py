"""Bounded server measurement capture and final time fence; no blob/model/effect I/O."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.control_support import current_charter, db_clock
from nexus.company.management.goals import Baseline, UnknownBaseline
from nexus.company.management.metric_contracts import (
    NATIVE_REPORT_COUNT,
    KnownMetricValue,
    MetricComparison,
    MetricObservationRequest,
    MetricSnapshot,
    MetricUnknownReason,
    MetricValue,
    MetricWorkFact,
    UnknownMetricValue,
)
from nexus.company.management.metric_provenance import ProtectedMetricFacts
from nexus.company.management.metric_recipes import empty_fact, report_fact
from nexus.company.management.metric_support import MetricSelection, selected_metric
from nexus.company.management.owner_view_sources import (
    OwnerViewSources,
    SourceDisclosure,
    evidence_artifacts,
    source_disclosure,
)
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.company.management.transactions import ManagementDeniedError
from nexus.harness.journal_models import CompanyControl


@dataclass(frozen=True)
class MetricProtection:
    deadlines: tuple[datetime, ...]

    def require_time(self, now: datetime) -> None:
        if any(value <= now for value in self.deadlines):
            raise ManagementDeniedError("Metric source permission or freshness expired")


@dataclass(frozen=True)
class CapturedMetric:
    snapshot: MetricSnapshot
    protection: MetricProtection


async def capture_metric(
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    request: MetricObservationRequest,
    catalog: PlanAdmissionCatalog,
    artifacts: BoundedArtifactReader,
    freshness: RegisteredSourceFreshness,
) -> CapturedMetric:
    selection = await selected_metric(session, control, request)
    facts = tuple(
        [
            await report_fact(session, control, identity, row, artifacts, freshness)
            for row in selection.work
        ]
    )
    return await finish_capture(
        session,
        control,
        scope,
        identity,
        request,
        catalog,
        selection,
        facts,
        OwnerViewSources(artifacts, freshness),
    )


async def baseline_capture(
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    selection: MetricSelection,
    sources: OwnerViewSources,
) -> tuple[Baseline, tuple[ArtifactRevisionRef, ...], SourceDisclosure | None]:
    refs = await evidence_artifacts(session, scope, selection.metric.baseline.evidence)
    if refs is not None:
        disclosure = await source_disclosure(session, control, scope, identity, sources, refs)
        if disclosure is not None:
            return selection.metric.baseline, refs, disclosure
    return UnknownBaseline(reason="Source-backed baseline is unavailable"), (), None


async def selection_resources(
    session: AsyncSession,
    scope: CompanyControlScope,
    selection: MetricSelection,
    catalog: PlanAdmissionCatalog,
) -> tuple[UUID, ...]:
    mapping = {value.symbol: value.resource.resource_id for value in catalog.resources}
    result: set[UUID] = set()
    for row in selection.work:
        charter = await current_charter(session, scope, row.binding.child.charter)
        for symbol in charter.charter.resource_scopes:
            resource = mapping.get(symbol)
            if resource is None:
                raise ManagementDeniedError("Metric native resource mapping is unavailable")
            result.add(resource)
    return tuple(sorted(result))


async def finish_capture(
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    request: MetricObservationRequest,
    catalog: PlanAdmissionCatalog,
    selection: MetricSelection,
    facts: tuple[MetricWorkFact, ...],
    sources: OwnerViewSources,
) -> CapturedMetric:
    from nexus.company.management.metric_provenance import protect_facts

    baseline, refs, admitted = await baseline_capture(
        session,
        control,
        scope,
        identity,
        selection,
        sources,
    )
    resources = await selection_resources(session, scope, selection, catalog)
    protected = await protect_facts(
        session,
        control,
        scope,
        identity,
        sources,
        facts,
        refs,
        resources,
    )
    reason = metric_reason(selection, facts, admitted, protected is not None)
    if reason is not None:
        facts = tuple(empty_fact(row, "unknown") for row in selection.work)
    value = (
        UnknownMetricValue(reason=reason)
        if reason is not None
        else KnownMetricValue(
            value=sum(row.status == "accepted_report" for row in facts),
        )
    )
    snapshot = metric_snapshot(
        scope, request, selection, facts, value, baseline, protected if reason is None else None
    )
    protection = capture_protection(admitted, protected)
    protection.require_time(await db_clock(session))
    return CapturedMetric(snapshot, protection)


def metric_reason(
    selection: MetricSelection,
    facts: tuple[MetricWorkFact, ...],
    baseline: SourceDisclosure | None,
    protected: bool,
) -> MetricUnknownReason | None:
    if selection.metric.observation_recipe != NATIVE_REPORT_COUNT:
        return "unsupported_recipe"
    if selection.metric.unit != "count":
        return "unsupported_unit"
    if baseline is None:
        return "baseline_unavailable"
    if not protected or any(row.status == "unknown" for row in facts):
        return "proof_unavailable"
    return None


def metric_snapshot(
    scope: CompanyControlScope,
    request: MetricObservationRequest,
    selection: MetricSelection,
    facts: tuple[MetricWorkFact, ...],
    value: MetricValue,
    baseline: Baseline,
    protected: ProtectedMetricFacts | None,
) -> MetricSnapshot:
    metric = selection.metric
    return MetricSnapshot(
        company_id=scope.company_id,
        request=request,
        recipe=metric.observation_recipe,
        comparison=MetricComparison(
            value=value, comparator=metric.comparator, target=metric.target, baseline=baseline
        ),
        work=facts,
        resources=protected.resources if protected else (),
        sources=protected.sources if protected else (),
    )


def capture_protection(
    admitted: SourceDisclosure | None,
    protected: ProtectedMetricFacts | None,
) -> MetricProtection:
    deadlines = () if protected is None else protected.deadlines
    if admitted is not None and admitted.valid_until is not None:
        deadlines = (*deadlines, admitted.valid_until)
    return MetricProtection(deadlines)

"""Configured actual source/resource/read services never enter event JSON or authority payloads."""

from dataclasses import dataclass

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.native_fact_contracts import RegisteredDigestPolicy
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.company.management.scheduling_support import SchedulerServices


@dataclass(frozen=True)
class NativeFactServices:
    """Operator-provisioned subject resource and qualified native catalog/reader/schedules."""

    catalog: PlanAdmissionCatalog
    artifacts: BoundedArtifactReader
    freshness: RegisteredSourceFreshness
    scheduler: SchedulerServices
    resource: ResourceRef
    digests: tuple[RegisteredDigestPolicy, ...] = ()

    def __post_init__(self) -> None:
        if self.resource.company_id != self.catalog.company_id or len(self.digests) > 32:
            raise ValueError("Native fact service company/configuration bounds differ")
        if self.scheduler.catalog != self.catalog:
            raise ValueError("Native fact scheduler must retain the exact configured catalog")
        if any(row.company_id != self.catalog.company_id for row in self.digests) or len(
            {row.schedule for row in self.digests}
        ) != len(self.digests):
            raise ValueError("Native digest registrations must be exact and unique")
        if len(
            {(row.report_id, row.kind, canonical_sha256(row.policy)) for row in self.digests}
        ) != len(self.digests):
            raise ValueError("Native digest event selectors must remain unambiguous after restart")

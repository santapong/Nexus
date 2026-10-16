"""Optional current-owner HTTP services; no worker/model/scheduler startup side effects."""

from __future__ import annotations

from dataclasses import dataclass, field

from nexus.company.access import CompanyDirectory
from nexus.company.management.action_review_store import OwnerActionReviewStore
from nexus.company.management.cancellation_store import WorkCancellationStore
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.commitment_store import CommitmentStore
from nexus.company.management.control_store import ManagementControlStore
from nexus.company.management.goal_store import GoalStore
from nexus.company.management.metric_queries import MetricQueries
from nexus.company.management.metric_store import MetricStore
from nexus.company.management.native_profile_store import NativeReportPreparationService
from nexus.company.management.operating_report_store import OperatingReportStore
from nexus.company.management.owner_view_store import ManagementOwnerViews
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.execution.planning_lifecycle import PlanningLifecycle


@dataclass(frozen=True, slots=True)
class ManagementApiServices:
    directory: CompanyDirectory
    controls: ManagementControlStore
    goals: GoalStore
    plans: ManagementPlanStore
    views: ManagementOwnerViews | None = None
    commitments: CommitmentStore | None = None
    action_reviews: OwnerActionReviewStore | None = None
    cancellations: WorkCancellationStore | None = None
    metrics: MetricStore | None = None
    metric_queries: MetricQueries | None = None
    reports: OperatingReportStore | None = None
    report_preparation: NativeReportPreparationService | None = None
    planning_lifecycle: PlanningLifecycle | None = None
    _lifecycle_binding: tuple[object, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_lifecycle_binding", self._planning_pins())
        self.require_lifecycle()

    def _planning_pins(self) -> tuple[object, ...]:
        if self.planning_lifecycle is None:
            return (None,)
        return (
            self.planning_lifecycle,
            self.directory,
            self.plans,
            self.plans.factory,
            self.plans.catalog,
            self.plans.source_freshness,
        )

    def require_lifecycle(self) -> PlanningLifecycle | None:
        """The approval hook must retain the exact concrete configured runtime graph."""
        if any(
            a is not b for a, b in zip(self._planning_pins(), self._lifecycle_binding, strict=True)
        ):
            raise ValueError("Original management planning lifecycle changed")
        value = self.planning_lifecycle
        if value is None:
            return None
        from nexus.company.directory_store import PersistentCompanyDirectory
        from nexus.execution.planning_lifecycle import PlanningLifecycle

        if value is not None:
            if (
                type(value) is not PlanningLifecycle
                or type(self.directory) is not PersistentCompanyDirectory
                or self.directory._factory is not value.factory
                or self.plans.factory is not value.factory
                or self.plans.source_freshness is not value.services.management.freshness
                or canonical_sha256(self.plans.catalog)
                != canonical_sha256(value.services.management.catalog)
            ):
                raise ValueError(
                    "Management planning hook differs from actual same-factory sources"
                )
            value.require_composition()
        return value

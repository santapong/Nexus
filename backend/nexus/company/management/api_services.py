"""Optional current-owner HTTP services; no worker/model/scheduler startup side effects."""

from dataclasses import dataclass

from nexus.company.access import CompanyDirectory
from nexus.company.management.action_review_store import OwnerActionReviewStore
from nexus.company.management.commitment_store import CommitmentStore
from nexus.company.management.control_store import ManagementControlStore
from nexus.company.management.goal_store import GoalStore
from nexus.company.management.owner_view_store import ManagementOwnerViews
from nexus.company.management.plan_store import ManagementPlanStore


@dataclass(frozen=True, slots=True)
class ManagementApiServices:
    directory: CompanyDirectory
    controls: ManagementControlStore
    goals: GoalStore
    plans: ManagementPlanStore
    views: ManagementOwnerViews | None = None
    commitments: CommitmentStore | None = None
    action_reviews: OwnerActionReviewStore | None = None

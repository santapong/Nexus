"""Optional current-owner HTTP services; no worker/model/scheduler startup side effects."""

from dataclasses import dataclass

from nexus.company.access import CompanyDirectory
from nexus.company.management.control_store import ManagementControlStore
from nexus.company.management.goal_store import GoalStore
from nexus.company.management.plan_store import ManagementPlanStore


@dataclass(frozen=True, slots=True)
class ManagementApiServices:
    directory: CompanyDirectory
    controls: ManagementControlStore
    goals: GoalStore
    plans: ManagementPlanStore

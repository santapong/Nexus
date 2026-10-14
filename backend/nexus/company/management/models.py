"""Explicit23-table management inventory; normal company013 installs its static schema."""

from nexus.company.management.acceptance_models import (
    ManagementAcceptanceInvalidation,
    ManagementAcceptanceProof,
    ManagementWorkAcceptance,
)
from nexus.company.management.control_models import ManagementControlEvent
from nexus.company.management.governance_models import (
    ManagementCharterHead,
    ManagementCharterRevision,
    ManagementGoalEvidence,
    ManagementGoalHead,
    ManagementGoalRevision,
    ManagementMandateHead,
    ManagementMandateRevision,
)
from nexus.company.management.metric_models import ManagementMetricObservation
from nexus.company.management.model_base import ManagementBase
from nexus.company.management.model_indexes import register_indexes
from nexus.company.management.operation_models import (
    ManagementCommitmentHead,
    ManagementCommitmentRevision,
    ManagementReportSnapshot,
)
from nexus.company.management.plan_models import (
    ManagementOwnerDecision,
    ManagementPlanDependency,
    ManagementPlanHead,
    ManagementPlanRevision,
    ManagementPlanTask,
    ManagementProcedure,
    ManagementRevisionEvent,
    ManagementVerificationBinding,
)

register_indexes()

__all__ = [
    "ManagementAcceptanceInvalidation",
    "ManagementAcceptanceProof",
    "ManagementBase",
    "ManagementCharterHead",
    "ManagementCharterRevision",
    "ManagementCommitmentHead",
    "ManagementCommitmentRevision",
    "ManagementControlEvent",
    "ManagementGoalEvidence",
    "ManagementGoalHead",
    "ManagementGoalRevision",
    "ManagementMandateHead",
    "ManagementMandateRevision",
    "ManagementMetricObservation",
    "ManagementOwnerDecision",
    "ManagementPlanDependency",
    "ManagementPlanHead",
    "ManagementPlanRevision",
    "ManagementPlanTask",
    "ManagementProcedure",
    "ManagementReportSnapshot",
    "ManagementRevisionEvent",
    "ManagementVerificationBinding",
    "ManagementWorkAcceptance",
]

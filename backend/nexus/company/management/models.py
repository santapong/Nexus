"""Explicit22-table management inventory, uninstalled and not imported by company migrations."""

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

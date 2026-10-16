"""Owner planning data shapes; descriptions and original read cutoffs confer no authority."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime

from nexus.company.brain.context import ContextManifest
from nexus.company.management.base import SHA256, Name, ValueContract
from nexus.company.management.goals import GoalRevisionRef
from nexus.company.management.lifecycle import PlanRevisionRef
from nexus.company.management.planning_content import PlanningContent
from nexus.company.management.planning_origin_contracts import PlanningOriginRef
from nexus.execution.runtime_contracts import EffectState, ExecutionState
from nexus.harness.lifecycle import ActionState


class PlanningGoalSelection(ValueContract):
    goal: GoalRevisionRef
    expected_current_revision_id: UUID | None


class PlanningLifecycleStatus(ValueContract):
    company_id: UUID
    goal: GoalRevisionRef
    plan_id: UUID
    observed_at: AwareDatetime
    bootstrap: PlanRevisionRef | None
    current: PlanRevisionRef | None
    current_state: Literal["proposed", "approved", "revoked"] | None
    action_id: UUID | None
    proposal_sha256: SHA256 | None
    action_state: ActionState | None
    owner_decision: Literal["approved", "rejected"] | None
    owner_decision_expires_at: AwareDatetime | None
    work_state: ExecutionState | None
    workflow_id: Name | None
    segment_id: UUID | None
    native_state: EffectState | None
    formal_proposal: PlanRevisionRef | None
    resources_pending: bool
    company_completed: Literal[False] = False


class PlanningCandidateReview(ValueContract):
    company_id: UUID
    action_id: UUID
    goal: GoalRevisionRef
    bootstrap: PlanRevisionRef
    origin: PlanningOriginRef
    content: PlanningContent
    manifest: ContextManifest
    model_recorded_at: AwareDatetime
    historical: Literal[True] = True
    company_completed: Literal[False] = False


@dataclass(frozen=True, slots=True)
class PlanningLifecycleRead[T]:
    """Internal descriptive cutoff: HTTP must min its own end and check after serialization."""

    value: T
    read_end_us: int

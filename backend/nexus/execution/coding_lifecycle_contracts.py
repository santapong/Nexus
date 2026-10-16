"""Current-owner C descriptions and internal original read ends, never execution permits."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime

from nexus.company.brain.context import ContextManifest
from nexus.company.management.base import SHA256, Name, ValueContract
from nexus.company.management.coding_content import CodeChangeContent, CodingBinding
from nexus.company.management.goals import GoalRevisionRef
from nexus.company.management.lifecycle import PlanRevisionRef
from nexus.execution.runtime_contracts import EffectState, ExecutionState
from nexus.harness.lifecycle import ActionState


class CodingGoalSelection(ValueContract):
    goal: GoalRevisionRef
    expected_current_revision_id: UUID


class CodingLifecycleStatus(ValueContract):
    company_id: UUID
    goal: GoalRevisionRef
    current: PlanRevisionRef | None
    approved_r2: bool
    observed_at: AwareDatetime
    action_id: UUID | None
    proposal_sha256: SHA256 | None
    action_state: ActionState | None
    work_state: ExecutionState | None
    workflow_id: Name | None
    native_state: EffectState | None
    resources_pending: bool
    company_completed: Literal[False] = False


class CodingCandidateReview(ValueContract):
    company_id: UUID
    action_id: UUID
    binding: CodingBinding
    manifest: ContextManifest
    content: CodeChangeContent
    request_id: UUID
    request_sha256: SHA256
    receipt_id: UUID
    artifact_id: UUID
    artifact_sha256: SHA256
    recorded_at: AwareDatetime
    historical: Literal[True] = True
    company_completed: Literal[False] = False


@dataclass(frozen=True, slots=True)
class CodingLifecycleRead[T]:
    value: T
    read_end_us: int

"""Closed kind/role parameter decoding; native scope and action authority remain separate."""

import json
from typing import Literal
from uuid import UUID

from nexus.company.contracts.actions import ActionProposal
from nexus.company.cycle_artifacts.common import bounded_json
from nexus.company.management.base import SHA256, ManagementContract, ValueContract
from nexus.company.management.goals import GoalRevisionRef
from nexus.company.management.lifecycle import PlanRevisionRef
from nexus.company.management.plans import RunBinding
from nexus.company.strategy.artifact_contracts import (
    StrategyCheckParameters,
    StrategyWriteParameters,
)
from nexus.harness.standing_contracts import ToolPermission


class CycleAuthorSelector(ManagementContract):
    goal: GoalRevisionRef
    producing_plan: PlanRevisionRef
    procedure_id: UUID
    author: RunBinding
    registration_sha256: SHA256


class _Write(ValueContract):
    selector: CycleAuthorSelector
    output_manifest_sha256: SHA256
    input_snapshot_sha256: SHA256
    input_manifest_sha256: SHA256


class PresentationWriteParameters(_Write):
    artifact_kind: Literal["presentation"]
    recipe_version: Literal["stockflow-presentation-v1"] = "stockflow-presentation-v1"


class SupportWriteParameters(_Write):
    artifact_kind: Literal["support"]
    recipe_version: Literal["stockflow-support-v1"] = "stockflow-support-v1"


class _Check(ValueContract):
    author_action_id: UUID
    verification_target_sha256: SHA256
    author_output_manifest_sha256: SHA256
    output_sha256: SHA256
    input_snapshot_sha256: SHA256
    input_manifest_sha256: SHA256


class PresentationCheckParameters(_Check):
    artifact_kind: Literal["presentation"]
    recipe_version: Literal["stockflow-presentation-v1"] = "stockflow-presentation-v1"


class SupportCheckParameters(_Check):
    artifact_kind: Literal["support"]
    recipe_version: Literal["stockflow-support-v1"] = "stockflow-support-v1"


ClosedCycleActionParameters = (
    StrategyWriteParameters
    | StrategyCheckParameters
    | PresentationWriteParameters
    | PresentationCheckParameters
    | SupportWriteParameters
    | SupportCheckParameters
)


def decode_cycle_action(
    actual_action: ActionProposal,
    *,
    expected_kind: str,
    phase: str,
    binding: RunBinding,
    permission: ToolPermission,
) -> ClosedCycleActionParameters:
    """Trusted expected bindings select a closed schema; decoding never proves them native."""
    action = ActionProposal.model_validate(actual_action.model_dump(warnings=False))
    bound = RunBinding.model_validate(binding.model_dump(warnings=False))
    tool = ToolPermission.model_validate(permission.model_dump(warnings=False))
    if expected_kind not in {"strategy", "presentation", "support"} or phase not in {
        "write",
        "check",
    }:
        raise ValueError("Unsupported cycle artifact kind or role phase")
    _require_action_binding(action, bound, tool, phase, expected_kind)
    raw = json.dumps(action.parameters, allow_nan=False)
    bounded_json(raw.encode())
    model: type[ClosedCycleActionParameters]
    if expected_kind == "strategy":
        model = StrategyWriteParameters if phase == "write" else StrategyCheckParameters
    elif expected_kind == "presentation":
        model = PresentationWriteParameters if phase == "write" else PresentationCheckParameters
    else:
        model = SupportWriteParameters if phase == "write" else SupportCheckParameters
    decoded = model.model_validate_json(raw)
    _require_selector_binding(decoded, action, bound)
    return decoded


def _require_selector_binding(
    decoded: ClosedCycleActionParameters, action: ActionProposal, bound: RunBinding
) -> None:
    if isinstance(decoded, StrategyWriteParameters):
        scope = decoded.selector.scope
        if (
            scope.company_id,
            scope.author.actor_id,
            scope.author.task_id,
            scope.author.trace_id,
        ) != (action.company_id, action.actor_id, action.task_id, action.trace_id):
            raise ValueError("Legacy strategy selector differs from exact action scope")
    if isinstance(decoded, (PresentationWriteParameters, SupportWriteParameters)):
        selector = decoded.selector
        if (
            selector.company_id != action.company_id
            or selector.author != bound
            or selector.goal.company_id != action.company_id
            or selector.producing_plan.company_id != action.company_id
            or selector.producing_plan.revision != 2
        ):
            raise ValueError("Cycle selector belongs to another exact producing binding")
    if isinstance(decoded, (StrategyCheckParameters, _Check)) and (
        decoded.author_action_id == action.action_id
    ):
        raise ValueError("Cycle verifier cannot select its own action")


def _require_action_binding(
    action: ActionProposal,
    binding: RunBinding,
    permission: ToolPermission,
    phase: str,
    kind: str,
) -> None:
    profile = (
        "verification" if phase == "check" else "reasoning" if kind == "strategy" else "routine"
    )
    if (
        (action.company_id, action.actor_id, action.task_id, action.trace_id)
        != (binding.company_id, binding.actor_id, binding.task_id, binding.trace_id)
        or (action.tool, action.tool_version, action.resource)
        != (permission.tool, permission.tool_version, permission.resource)
        or (action.tool, action.tool_version) != (f"company.cycle-artifact.{phase}.v1", "v1")
        or (binding.workflow_name, binding.workflow_version, binding.model_profile)
        != ("company.cycle.artifact", "v1", profile)
    ):
        raise ValueError("Cycle action differs from trusted kind/role/tool/resource binding")

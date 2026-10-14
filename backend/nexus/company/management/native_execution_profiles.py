"""Closed model-free identities are explicit admission configuration, never execution proof."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self

from pydantic import Field, model_validator

from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.base import SHA256, ManagementContract, Name
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.plans import ChildAllocation, PlanPayload
from nexus.company.management.transactions import ManagementDeniedError
from nexus.core.llm.company_registry import ModelRegistry
from nexus.execution.runtime_contracts import AttemptKind, AttemptQuota
from nexus.harness.standing_contracts import ToolPermission

if TYPE_CHECKING:
    from nexus.company.management.plan_support import PlanAdmissionCatalog

NATIVE_CRITERIA = (
    "engineering.patch.v1",
    "engineering.baseline.v1",
    "engineering.post.v1",
    "engineering.behavior.v1",
    "engineering.independent.v1",
    "engineering.sandbox.v1",
    "engineering.artifacts.v1",
)
_WORKFLOWS = {
    "engineering.native.v1": "engineering.change",
    "verification.native.v1": "engineering.verify",
}


class NativeExecutionProfile(ManagementContract):
    """Server-only exact mechanical identity; no model health or capability claim."""

    execution_profile: Literal["engineering.native.v1", "verification.native.v1"]
    workflow_name: Literal["engineering.change", "engineering.verify"]
    workflow_version: Literal["v1"] = "v1"
    registry_revision: Name
    registry_sha256: SHA256
    check_recipe: Literal["native-engineering-change-v1"] = "native-engineering-change-v1"
    tools: tuple[ToolPermission, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def closed_identity(self) -> Self:
        """Refuse crossed workflows, model tools, other adapters and duplicate tuples."""
        keys = tuple((row.tool, row.tool_version, row.resource) for row in self.tools)
        if (
            self.workflow_name != _WORKFLOWS[self.execution_profile]
            or any(key[:2] != ("company.builder.run.v1", "v1") for key in keys)
            or len(set(keys)) != len(keys)
        ):
            raise ValueError("Native execution profile has an unsupported or ambiguous identity")
        return self


def require_exact_native_quota(quota: AttemptQuota) -> None:
    """Validate actual raw counts before JSON serialization can normalize copied values."""
    AttemptQuota.model_validate(
        {field: getattr(quota, field) for field in AttemptQuota.model_fields}
    )


def validate_native_profiles(
    registry: ModelRegistry, profiles: tuple[NativeExecutionProfile, ...]
) -> None:
    """Validate the complete bounded tuple, including model_copy inputs, before selection."""
    if len(profiles) > 2 or len({row.execution_profile for row in profiles}) != len(profiles):
        raise ManagementDeniedError("Native execution profiles are bounded and unique")
    if not profiles:
        return
    digest = canonical_sha256(registry)
    for profile in profiles:
        checked = NativeExecutionProfile.model_validate_json(profile.model_dump_json())
        if (
            checked.company_id != registry.company_id
            or checked.registry_revision != registry.revision
            or checked.registry_sha256 != digest
        ):
            raise ManagementDeniedError("Native execution profile binds another exact catalog")


def native_execution_profile(
    catalog: PlanAdmissionCatalog, child: ChildAllocation
) -> NativeExecutionProfile | None:
    """Return descriptive exact eligibility; this function grants no lease or call permit."""
    validate_native_profiles(catalog.models, catalog.native_profiles)
    selected = next(
        (
            row
            for row in catalog.native_profiles
            if row.execution_profile == child.binding.model_profile
        ),
        None,
    )
    if selected is None:
        return None
    require_exact_native_quota(child.quota)
    child = ChildAllocation.model_validate_json(child.model_dump_json())
    binding = child.binding
    permissions = {(row.tool, row.tool_version, row.resource) for row in catalog.tools}
    if (
        child.company_id != catalog.company_id
        or binding.company_id != catalog.company_id
        or binding.model_registry_version != selected.registry_revision
        or (binding.workflow_name, binding.workflow_version)
        != (selected.workflow_name, selected.workflow_version)
        or child.quota.model_requests != 0
        or selected.check_recipe not in catalog.check_recipes
        or not {(row.tool, row.tool_version, row.resource) for row in selected.tools} <= permissions
    ):
        raise ManagementDeniedError("Native work differs from its exact zero-model admission")
    return selected


def require_native_plan(catalog: PlanAdmissionCatalog, payload: PlanPayload) -> None:
    """Initial native plans are one closed author/verifier pair with a zero-model root."""
    selected = tuple(native_execution_profile(catalog, row) for row in payload.children)
    if not any(selected):
        return
    require_exact_native_quota(payload.procedure.quota)
    if (
        len(selected) != 2
        or any(row is None for row in selected)
        or payload.procedure.quota.model_requests != 0
        or len(payload.verification) != 1
        or any(item.acceptance != NATIVE_CRITERIA for item in payload.plan.items)
    ):
        raise ManagementDeniedError(
            "Native plan must retain the closed zero-model engineering pair"
        )
    by_profile = {
        row.execution_profile: child.binding.task_id
        for child, row in zip(payload.children, selected, strict=True)
        if row is not None
    }
    parent = payload.procedure.binding
    if (
        parent.company_id != catalog.company_id
        or parent.model_profile != "engineering.native.v1"
        or parent.model_registry_version != catalog.models.revision
        or (parent.workflow_name, parent.workflow_version) != ("engineering.change", "v1")
    ):
        raise ManagementDeniedError("Native non-executing root differs from its plan identity")
    edge = payload.verification[0]
    if (
        len(by_profile) != 2
        or edge.author_task_id != by_profile.get("engineering.native.v1")
        or edge.verifier_task_id != by_profile.get("verification.native.v1")
        or edge.check_recipe != "native-engineering-change-v1"
    ):
        raise ManagementDeniedError("Native plan author/verifier edge differs")


def require_native_action(
    catalog: PlanAdmissionCatalog,
    child: ChildAllocation,
    proposal: ActionProposal,
    kind: AttemptKind,
) -> bool:
    """Narrow native effects to exact builder tuples; no model kind or model tool is allowed."""
    profile = native_execution_profile(catalog, child)
    if profile is None:
        return False
    if kind != "tool_attempts" or (proposal.tool, proposal.tool_version, proposal.resource) not in {
        (row.tool, row.tool_version, row.resource) for row in profile.tools
    }:
        raise ManagementDeniedError("Native execution cannot request models or unsupported tools")
    return True

"""Pure exact notification eligibility; actual owner/effect gates remain mandatory."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.plans import ChildAllocation, PlanPayload
from nexus.company.management.transactions import ManagementDeniedError
from nexus.company.notifications.native_profile_contracts import (
    NOTIFICATION_PROFILE,
    NOTIFICATION_TOOL,
    NOTIFICATION_VERSION,
    NOTIFICATION_WORKFLOW,
    NativeNotificationProfile,
)
from nexus.core.llm.company_registry import ModelRegistry
from nexus.execution.runtime_contracts import AttemptKind, AttemptQuota

if TYPE_CHECKING:
    from nexus.company.management.plan_support import PlanAdmissionCatalog


def _require_exact_quota(quota: AttemptQuota) -> None:
    """Check actual field types before an int serializer can normalize copied booleans."""
    AttemptQuota.model_validate({name: getattr(quota, name) for name in AttemptQuota.model_fields})


def validate_notification_profiles(
    registry: ModelRegistry, profiles: tuple[NativeNotificationProfile, ...]
) -> None:
    """Validate the complete bounded tuple before selecting any child or model view."""
    if len(profiles) > 1:
        raise ManagementDeniedError("Notification profiles contain at most one exact identity")
    if not profiles:
        return
    digest = canonical_sha256(registry)
    for profile in profiles:
        checked = NativeNotificationProfile.model_validate_json(profile.model_dump_json())
        if (
            checked.company_id != registry.company_id
            or checked.registry_revision != registry.revision
            or checked.registry_sha256 != digest
        ):
            raise ManagementDeniedError("Notification profile binds another exact catalog")


def native_notification_profile(
    catalog: PlanAdmissionCatalog, child: ChildAllocation
) -> NativeNotificationProfile | None:
    """Return configured identity metadata; no credential, approval or permit is issued."""
    validate_notification_profiles(catalog.models, catalog.notification_profiles)
    if child.binding.model_profile != NOTIFICATION_PROFILE or not catalog.notification_profiles:
        return None
    selected = catalog.notification_profiles[0]
    _require_exact_quota(child.quota)
    checked = ChildAllocation.model_validate_json(child.model_dump_json())
    binding = checked.binding
    resources = tuple(
        row.resource for row in catalog.resources if row.symbol == selected.target_symbol
    )
    tools = tuple(
        row
        for row in catalog.tools
        if (row.tool, row.tool_version, row.resource)
        == (NOTIFICATION_TOOL, NOTIFICATION_VERSION, selected.target_symbol)
    )
    if (
        checked.company_id != catalog.company_id
        or selected.company_id != catalog.company_id
        or binding.model_registry_version != selected.registry_revision
        or (binding.workflow_name, binding.workflow_version)
        != (selected.workflow_name, selected.workflow_version)
        or checked.quota.model_requests != 0
        or resources != (selected.target_resource,)
        or len(tools) != 1
    ):
        raise ManagementDeniedError("Notification work differs from its exact no-model identity")
    return selected


def require_notification_plan(catalog: PlanAdmissionCatalog, payload: PlanPayload) -> None:
    """Initial sender plans contain one child, no verifier edge and a zero-model root."""
    if catalog.nexus_cycle_admission is not None:
        from nexus.company.management.nexus_cycle_admission import select_nexus_plan

        select_nexus_plan(catalog.nexus_cycle_admission, catalog, payload)
        return
    if catalog.cycle_admission is not None:
        from nexus.company.management.cycle_admission import validate_stockflow_cycle
        from nexus.company.management.cycle_catalog_checks import validate_cycle_catalog

        validate_cycle_catalog(catalog.cycle_admission, catalog)
        matched = validate_stockflow_cycle(catalog.cycle_admission, catalog.models, payload)
        if matched is not None and matched.stage == "full":
            return
    selected = tuple(native_notification_profile(catalog, child) for child in payload.children)
    if not any(selected) and payload.procedure.binding.model_profile != NOTIFICATION_PROFILE:
        return
    _require_exact_quota(payload.procedure.quota)
    checked = PlanPayload.model_validate_json(payload.model_dump_json())
    parent = checked.procedure.binding
    if (
        len(selected) != 1
        or selected[0] is None
        or checked.company_id != catalog.company_id
        or checked.procedure.quota.model_requests != 0
        or checked.verification
        or parent.model_profile != NOTIFICATION_PROFILE
        or parent.model_registry_version != catalog.models.revision
        or (parent.workflow_name, parent.workflow_version)
        != (NOTIFICATION_WORKFLOW, NOTIFICATION_VERSION)
    ):
        raise ManagementDeniedError("Notification plan requires one exact no-model sender")


def require_notification_action(
    catalog: PlanAdmissionCatalog,
    child: ChildAllocation,
    proposal: ActionProposal,
    kind: AttemptKind,
) -> bool:
    """Narrow configured effects to the sender tuple; this is not call authorization."""
    profile = native_notification_profile(catalog, child)
    if profile is None:
        return False
    if kind != "tool_attempts" or (proposal.tool, proposal.tool_version, proposal.resource) != (
        NOTIFICATION_TOOL,
        NOTIFICATION_VERSION,
        profile.target_symbol,
    ):
        raise ManagementDeniedError("Native notifications cannot request models or other tools")
    return True

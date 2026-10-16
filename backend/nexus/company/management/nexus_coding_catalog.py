"""Closed Nexus catalog/role selection; no model, native or owner permission is produced."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.check_contracts import REPORT_CHECK_RECIPE
from nexus.company.management.governance import CharterRevision
from nexus.company.management.native_execution_profiles import native_execution_profile
from nexus.company.management.nexus_coding_admission import (
    NexusCodingAdmission,
    select_nexus_coding_plan,
)
from nexus.company.management.nexus_cycle_admission import (
    NexusCycleAdmission,
    NexusStage,
    select_nexus_plan,
    validate_nexus_catalog,
)
from nexus.company.management.plans import ChildAllocation, PlanPayload
from nexus.company.management.transactions import ManagementDeniedError
from nexus.company.notifications.native_profile_checks import native_notification_profile
from nexus.core.llm.company_registry import ModelRegistration, ModelRegistry

if TYPE_CHECKING:
    from nexus.company.management.plan_catalog import PlanAdmissionCatalog

NexusAdmission = NexusCycleAdmission | NexusCodingAdmission
_CAPABILITIES = {
    "reasoning": frozenset({"reasoning", "structured_output"}),
    "engineering": frozenset({"code", "tools", "structured_output"}),
    "routine": frozenset({"text"}),
}


def _exclusive(catalog: PlanAdmissionCatalog) -> None:
    if (
        sum(
            value is not None
            for value in (
                catalog.cycle_admission,
                catalog.nexus_cycle_admission,
                catalog.nexus_coding_admission,
            )
        )
        > 1
    ):
        raise ValueError("Company admission profiles are mutually exclusive")


def validate_nexus_coding_catalog(
    admission: NexusCodingAdmission | None,
    catalog: PlanAdmissionCatalog,
) -> NexusCodingAdmission | None:
    """Validate every fixed role target; temporal eligibility remains at native admission/effect."""
    _exclusive(catalog)
    if admission is None:
        return None
    checked = NexusCodingAdmission.model_validate(admission.model_dump())
    registry = ModelRegistry.model_validate(catalog.models.model_dump())
    if catalog.nexus_coding_admission != checked or (
        checked.company_id,
        checked.registry_revision,
        checked.registry_sha256,
    ) != (catalog.company_id, registry.revision, canonical_sha256(registry)):
        raise ValueError("Coding catalog differs from its complete declared registry/family")
    permissions = tuple((row.tool, row.tool_version, row.resource) for row in catalog.tools)
    expected = {
        (slot.tool.tool, slot.tool.tool_version, slot.tool.resource) for slot in checked.slots
    }
    resources = {row.symbol: row.resource for row in catalog.resources}
    if (
        len(set(permissions)) != len(permissions)
        or set(permissions) != expected
        or len(resources) != len(catalog.resources)
        or any(row.company_id != catalog.company_id for row in resources.values())
        or any(slot.tool.resource not in resources for slot in checked.slots)
        or not {"native-engineering-change-v1", REPORT_CHECK_RECIPE} <= catalog.check_recipes
    ):
        raise ValueError("Coding tools/resources/check recipes must match every exact role")
    for slot in checked.slots[:5]:
        model = next(
            (row for row in registry.models if slot.tool.resource == "model:" + row.registry_id),
            None,
        )
        profile = slot.child.binding.model_profile
        if (
            model is None
            or profile not in catalog.admitted_profiles
            or not any(row.profile == profile for row in model.evaluations)
            or not _CAPABILITIES[profile] <= model.capabilities
            or model.price is None
            or model.price.version != registry.pricebook_version
            or not model.allowed_data
        ):
            raise ValueError("Coding role model/profile/prices/classification is not configured")
    for slot in checked.slots[5:7]:
        native = native_execution_profile(catalog, slot.child)
        if native is None or native.tools != (slot.tool,):
            raise ValueError("Coding native role lacks its exact registered profile")
    sender = native_notification_profile(catalog, checked.slots[-1].child)
    if sender is None or sender.target_symbol != checked.slots[-1].tool.resource:
        raise ValueError("Coding sender lacks its exact registered native profile")
    return checked


def configured_nexus_admission(catalog: PlanAdmissionCatalog) -> NexusAdmission | None:
    """Select one finite concrete configuration; a new profile never becomes ordinary work."""
    _exclusive(catalog)
    if catalog.nexus_coding_admission is not None:
        return validate_nexus_coding_catalog(catalog.nexus_coding_admission, catalog)
    return validate_nexus_catalog(catalog.nexus_cycle_admission, catalog)


def select_configured_nexus_plan(
    catalog: PlanAdmissionCatalog, payload: PlanPayload
) -> NexusStage | None:
    """Require the exact full-profile digest in its real persisted r1/r2 payload."""
    admission = configured_nexus_admission(catalog)
    if isinstance(admission, NexusCodingAdmission):
        return select_nexus_coding_plan(admission, payload)
    if payload.coding_admission_sha256 is not None:
        raise ManagementDeniedError("Coding metadata requires its complete configured admission")
    return select_nexus_plan(admission, catalog, payload)


def coding_role_model(
    catalog: PlanAdmissionCatalog, child: ChildAllocation
) -> ModelRegistration | None:
    """A configured exact target is distinct from current source/lease/effect permission."""
    if catalog.nexus_coding_admission is None:
        return None
    admission = validate_nexus_coding_catalog(catalog.nexus_coding_admission, catalog)
    assert admission is not None
    slot = next((slot for slot in admission.slots if slot.child == child), None)
    if slot is None:
        raise ManagementDeniedError("Work is outside the complete coding family")
    if slot.child.quota.model_requests == 0:
        return None
    return next(
        row for row in catalog.models.models if slot.tool.resource == "model:" + row.registry_id
    )


def validate_configured_role_profile(
    catalog: PlanAdmissionCatalog,
    child: ChildAllocation,
    now: datetime,
) -> None:
    """Use the exact role model, avoiding another healthy model rescuing a stale target."""
    from nexus.company.management.model_profile_checks import validate_model_profile

    model = coding_role_model(catalog, child)
    if model is None:
        validate_model_profile(catalog, child, now)
        return
    selected = catalog.model_copy(
        update={
            "models": catalog.models.model_copy(update={"models": (model,)}),
            "model_observations": tuple(
                row for row in catalog.model_observations if row.registry_id == model.registry_id
            ),
            "native_profiles": (),
            "notification_profiles": (),
            "cycle_admission": None,
            "nexus_cycle_admission": None,
            "nexus_coding_admission": None,
        }
    )
    validate_model_profile(selected, child, now)


def require_role_charter(
    catalog: PlanAdmissionCatalog, child: ChildAllocation, charter: CharterRevision
) -> None:
    """Preserve legacy single-target rules and require exact coding role charter resources."""
    resources = {row.symbol for row in catalog.resources}
    if catalog.nexus_coding_admission is None:
        tools = {row.tool: row for row in catalog.tools}
        if (
            not set(charter.charter.allowed_tools) <= tools.keys()
            or not set(charter.charter.resource_scopes) <= resources
        ):
            raise ManagementDeniedError("Charter contains unknown tool or resource eligibility")
        if any(
            tools[name].resource not in charter.charter.resource_scopes
            for name in charter.charter.allowed_tools
        ):
            raise ManagementDeniedError("Configured tool resource escapes the charter scope")
        return
    admission = configured_nexus_admission(catalog)
    assert isinstance(admission, NexusCodingAdmission)
    slot = next((slot for slot in admission.slots if slot.child == child), None)
    scopes, allowed_tools = set(charter.charter.resource_scopes), set(charter.charter.allowed_tools)
    if (
        slot is None
        or not scopes <= resources
        or slot.tool.tool not in allowed_tools
        or slot.tool.resource not in scopes
        or any(
            not any(row.tool == name and row.resource in scopes for row in catalog.tools)
            for name in allowed_tools
        )
    ):
        raise ManagementDeniedError("Coding charter differs from its exact role resource tuple")

"""Complete cycle/catalog bindings, never current permission or model-health evidence."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import TypeAdapter

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.management.base import Name, require_company
from nexus.company.management.cycle_admission import validate_stockflow_cycle_configuration
from nexus.company.management.cycle_admission_contracts import StockFlowCycleAdmission
from nexus.company.management.model_observations import validate_model_observations
from nexus.company.management.native_execution_profiles import (
    native_execution_profile,
    validate_native_profiles,
)
from nexus.company.notifications.native_profile_checks import (
    native_notification_profile,
    validate_notification_profiles,
)
from nexus.harness.standing_contracts import ToolPermission

if TYPE_CHECKING:
    from nexus.company.management.plan_catalog import PlanAdmissionCatalog


def validate_cycle_catalog(
    admission: StockFlowCycleAdmission | None,
    catalog: PlanAdmissionCatalog,
) -> StockFlowCycleAdmission | None:
    """Validate full original configuration before selection; absent config changes nothing."""
    if admission is None:
        return None
    checked = validate_stockflow_cycle_configuration(admission, catalog.models)
    require_company(catalog.company_id, checked, *(row.resource for row in catalog.resources))
    _catalog_symbols(catalog)
    # Validate every original tuple before either native selector can discard anything.
    validate_model_observations(catalog.models, catalog.model_observations)
    validate_native_profiles(catalog.models, catalog.native_profiles)
    validate_notification_profiles(catalog.models, catalog.notification_profiles)
    _slot_bindings(checked, catalog)
    _native_bindings(checked, catalog)
    return checked


def _catalog_symbols(catalog: PlanAdmissionCatalog) -> None:
    if (
        len(catalog.tools) > 32
        or len({row.tool for row in catalog.tools}) != len(catalog.tools)
        or len(catalog.resources) > 32
        or len({row.symbol for row in catalog.resources}) != len(catalog.resources)
    ):
        raise ValueError("Cycle catalog tools/resources must be bounded and unambiguous")
    for tool in catalog.tools:
        ToolPermission.model_validate(tool.model_dump(warnings=False))
    for resource in catalog.resources:
        TypeAdapter(Name).validate_python(resource.symbol)
        ResourceRef.model_validate(resource.resource.model_dump(warnings=False))


def _slot_bindings(admission: StockFlowCycleAdmission, catalog: PlanAdmissionCatalog) -> None:
    resources = {row.symbol for row in catalog.resources}
    if admission.procedure.binding.model_profile not in catalog.admitted_profiles:
        raise ValueError("Cycle nonexecuting root profile is not structurally admitted")
    for slot in admission.slots:
        if slot.tool not in catalog.tools or slot.tool.resource not in resources:
            raise ValueError("Cycle slot tool/version/resource lacks its exact catalog mapping")
        if (
            slot.verification is not None
            and slot.verification.check_recipe not in catalog.check_recipes
        ):
            raise ValueError("Cycle verifier recipe is not structurally admitted")
        if (
            slot.role not in {"engineering", "engineering_check", "sender"}
            and slot.child.binding.model_profile not in catalog.admitted_profiles
        ):
            raise ValueError("Cycle ordinary child profile is not structurally admitted")


def _native_bindings(admission: StockFlowCycleAdmission, catalog: PlanAdmissionCatalog) -> None:
    for slot in admission.slots[2:4]:
        profile = native_execution_profile(catalog, slot.child)
        if profile is None or profile.tools != (slot.tool,):
            raise ValueError("Cycle requires each actual native profile's exact singleton tool")
    sender = admission.slots[-1]
    sender_profile = native_notification_profile(catalog, sender.child)
    if sender_profile is None or sender_profile.target_symbol != sender.tool.resource:
        raise ValueError("Cycle requires the actual sender's exact mapped resource")

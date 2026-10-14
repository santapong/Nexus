"""Synthetic structural catalog only; no current native or model authority."""

from dataclasses import dataclass
from uuid import UUID

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.cycle_admission_contracts import StockFlowCycleAdmission
from nexus.company.management.native_execution_profiles import NativeExecutionProfile
from nexus.company.management.plan_catalog import NamedPlanResource, PlanAdmissionCatalog
from nexus.company.notifications.native_profile_contracts import NativeNotificationProfile
from nexus.core.llm.company_registry import ModelRegistry
from nexus.tests.unit.cycle_admission_fixture import cycle


@dataclass(frozen=True)
class CycleCatalog:
    """Separate explicit cycle description and existing genuine catalog type."""

    admission: StockFlowCycleAdmission
    catalog: PlanAdmissionCatalog


def cycle_catalog(registry: ModelRegistry | None = None) -> CycleCatalog:
    """Build all actual profile/tool/resource pins, with no invented model health."""
    original = cycle()
    models = original.registry if registry is None else registry
    digest = canonical_sha256(models)
    admission = original.admission.model_copy(update={"registry_sha256": digest})
    native = tuple(
        NativeExecutionProfile.model_validate(
            {
                "company_id": admission.company_id,
                "execution_profile": slot.child.binding.model_profile,
                "workflow_name": slot.child.binding.workflow_name,
                "registry_revision": models.revision,
                "registry_sha256": digest,
                "tools": (slot.tool,),
            }
        )
        for slot in admission.slots[2:4]
    )
    target = ResourceRef(company_id=admission.company_id, resource_id=UUID(int=700))
    sender = NativeNotificationProfile(
        company_id=admission.company_id,
        execution_profile="notification.native.v1",
        workflow_name="internal.owner-notification",
        registry_revision=models.revision,
        registry_sha256=digest,
        target_symbol=admission.slots[-1].tool.resource,
        target_resource=target,
    )
    catalog = PlanAdmissionCatalog(
        company_id=admission.company_id,
        models=models,
        tools=tuple(dict.fromkeys(slot.tool for slot in admission.slots)),
        resources=(NamedPlanResource(symbol=sender.target_symbol, resource=target),),
        admitted_profiles=frozenset({"reasoning", "routine", "verification"}),
        check_recipes=frozenset(
            slot.verification.check_recipe
            for slot in admission.slots
            if slot.verification is not None
        ),
        native_profiles=native,
        notification_profiles=(sender,),
    )
    return CycleCatalog(admission, catalog)

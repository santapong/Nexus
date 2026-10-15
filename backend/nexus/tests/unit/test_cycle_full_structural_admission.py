"""Configured full structural admission through real shared hooks; no SQL/runtime evidence."""

from collections.abc import Callable

import pytest

from nexus.company.management.native_execution_profiles import require_native_plan
from nexus.company.management.plan_catalog import PlanAdmissionCatalog
from nexus.company.management.plans import PlanPayload
from nexus.company.notifications.native_profile_checks import require_notification_plan
from nexus.tests.unit.cycle_admission_fixture import declared
from nexus.tests.unit.cycle_full_structural_support import configured, full
from nexus.tests.unit.test_company_native_execution_profiles import mechanical
from nexus.tests.unit.test_company_notification_native_profiles import notification_plan

Hook = Callable[[PlanAdmissionCatalog, PlanPayload], None]
HOOKS = (require_native_plan, require_notification_plan)


@pytest.mark.parametrize("hook", HOOKS)
def test_exact_configured_full_layout_is_structurally_admitted(hook: Hook) -> None:
    catalog, payload = full()
    hook(catalog, payload)


def test_ordinary_pair_and_single_sender_admission_stay_unchanged() -> None:
    catalog, payload = mechanical()
    require_native_plan(catalog, payload)
    catalog, payload = notification_plan()
    require_notification_plan(catalog, payload)


@pytest.mark.parametrize("hook", HOOKS)
@pytest.mark.parametrize(
    "problem",
    [
        "native_missing",
        "native_extra",
        "native_wrong",
        "sender_missing",
        "sender_duplicate",
        "sender_wrong",
        "resource_missing",
        "resource_duplicate",
        "resource_wrong",
        "resource_foreign",
        "resource_different",
        "extra_child",
        "missing_child",
        "extra_edge",
        "criteria_missing",
        "criteria_extra",
        "criteria_placeholder",
        "payload_root_bool",
        "unused_role_bool",
        "configured_root_bool",
    ],
)
def test_full_configured_mismatch_denies_without_fallback(hook: Hook, problem: str) -> None:
    catalog, payload = full()
    if problem == "native_missing":
        catalog = catalog.model_copy(update={"native_profiles": catalog.native_profiles[:1]})
    elif problem == "native_extra":
        catalog = catalog.model_copy(
            update={"native_profiles": (*catalog.native_profiles, catalog.native_profiles[0])}
        )
    elif problem == "native_wrong":
        catalog = catalog.model_copy(
            update={
                "native_profiles": (
                    catalog.native_profiles[0].model_copy(update={"registry_sha256": "0" * 64}),
                    catalog.native_profiles[1],
                )
            }
        )
    elif problem == "sender_missing":
        catalog = catalog.model_copy(update={"notification_profiles": ()})
    elif problem == "sender_duplicate":
        catalog = catalog.model_copy(
            update={"notification_profiles": catalog.notification_profiles * 2}
        )
    elif problem == "sender_wrong":
        catalog = catalog.model_copy(
            update={
                "notification_profiles": (
                    catalog.notification_profiles[0].model_copy(
                        update={"registry_sha256": "0" * 64}
                    ),
                )
            }
        )
    elif problem == "resource_missing":
        catalog = catalog.model_copy(update={"resources": ()})
    elif problem == "resource_duplicate":
        catalog = catalog.model_copy(update={"resources": catalog.resources * 2})
    elif problem == "resource_wrong":
        catalog = catalog.model_copy(
            update={
                "resources": (catalog.resources[0].model_copy(update={"symbol": "other.output"}),)
            }
        )
    elif problem in {"resource_foreign", "resource_different"}:
        from uuid import UUID

        row = catalog.resources[0]
        key = "company_id" if problem == "resource_foreign" else "resource_id"
        changed = row.model_copy(
            update={"resource": row.resource.model_copy(update={key: UUID(int=999)})}
        )
        catalog = catalog.model_copy(update={"resources": (changed,)})
    elif problem == "extra_child":
        payload = payload.model_copy(update={"children": (*payload.children, payload.children[-1])})
    elif problem == "missing_child":
        payload = payload.model_copy(update={"children": payload.children[:-1]})
    elif problem == "extra_edge":
        payload = payload.model_copy(
            update={"verification": (*payload.verification, payload.verification[-1])}
        )
    elif problem.startswith("criteria_"):
        item = payload.plan.items[0]
        criteria = (
            item.acceptance[:-1]
            if problem == "criteria_missing"
            else (*item.acceptance, "other.v1")
            if problem == "criteria_extra"
            else ("cycle.strategy.v1",)
        )
        payload = payload.model_copy(
            update={
                "plan": payload.plan.model_copy(
                    update={
                        "items": (
                            item.model_copy(update={"acceptance": criteria}),
                            *payload.plan.items[1:],
                        )
                    }
                )
            }
        )
    elif problem == "payload_root_bool":
        payload = payload.model_copy(
            update={
                "procedure": payload.procedure.model_copy(
                    update={
                        "quota": payload.procedure.quota.model_copy(update={"plan_revisions": True})
                    }
                )
            }
        )
    else:
        admission = catalog.cycle_admission
        assert admission is not None
        if problem == "configured_root_bool":
            admission = admission.model_copy(
                update={
                    "procedure": admission.procedure.model_copy(
                        update={
                            "quota": admission.procedure.quota.model_copy(
                                update={"plan_revisions": True}
                            )
                        }
                    )
                }
            )
        else:
            slots = list(admission.slots)
            child = slots[6].child
            slots[6] = slots[6].model_copy(
                update={
                    "child": child.model_copy(
                        update={"quota": child.quota.model_copy(update={"tool_attempts": True})}
                    )
                }
            )
            admission = admission.model_copy(update={"slots": tuple(slots)})
        catalog = catalog.model_copy(update={"cycle_admission": admission})
    with pytest.raises((ValueError, RuntimeError)):
        hook(catalog, payload)


@pytest.mark.parametrize("hook", HOOKS)
def test_strategy_stage_revalidates_unused_sender_catalog(hook: Hook) -> None:
    current = configured()
    payload = declared(current.admission, 1)
    bad = current.catalog.notification_profiles[0].model_copy(update={"registry_sha256": "0" * 64})
    catalog = current.catalog.model_copy(update={"notification_profiles": (bad,)})
    with pytest.raises((ValueError, RuntimeError)):
        hook(catalog, payload)


@pytest.mark.parametrize("hook", HOOKS)
@pytest.mark.parametrize(
    "problem", ["native", "model_observation", "registry", "unused_resource", "unused_tool"]
)
def test_strategy_stage_validates_all_unused_original_configuration(
    hook: Hook, problem: str
) -> None:
    from nexus.tests.unit.test_company_model_observations import observed

    current = configured()
    catalog = current.catalog
    payload = declared(current.admission, 1)
    if problem == "native":
        catalog = catalog.model_copy(
            update={
                "native_profiles": (
                    catalog.native_profiles[0].model_copy(update={"registry_sha256": "f" * 64}),
                    catalog.native_profiles[1],
                )
            }
        )
    elif problem == "model_observation":
        catalog = catalog.model_copy(update={"model_observations": (observed(),)})
    elif problem == "registry":
        catalog = catalog.model_copy(
            update={"models": catalog.models.model_copy(update={"revision": "different"})}
        )
    elif problem == "unused_tool":
        bad = catalog.tools[0].model_copy(update={"tool": ""})
        catalog = catalog.model_copy(update={"tools": (*catalog.tools, bad)})
    else:
        resource = catalog.resources[0].model_copy(update={"symbol": ""})
        catalog = catalog.model_copy(update={"resources": (*catalog.resources, resource)})
    with pytest.raises((ValueError, RuntimeError)):
        hook(catalog, payload)


@pytest.mark.parametrize("hook", HOOKS)
@pytest.mark.parametrize("problem", ["missing", "extra", "placeholder", "duplicate"])
def test_coherently_copied_configuration_and_payload_still_require_six_strategy_criteria(
    hook: Hook, problem: str
) -> None:
    current = configured()
    slots = list(current.admission.slots)
    for index in (0, 1):
        old = slots[index].work.acceptance
        bad = (
            old[:-1]
            if problem == "missing"
            else (*old, "other.v1")
            if problem == "extra"
            else ("cycle.strategy.v1",)
            if problem == "placeholder"
            else (*old[:-1], old[0])
        )
        slots[index] = slots[index].model_copy(
            update={"work": slots[index].work.model_copy(update={"acceptance": bad})}
        )
    admission = current.admission.model_copy(update={"slots": tuple(slots)})
    catalog = current.catalog.model_copy(update={"cycle_admission": admission})
    valid = declared(current.admission, 2)
    payload = valid.model_copy(
        update={
            "plan": valid.plan.model_copy(
                update={"items": tuple(slot.work for slot in admission.slots)}
            )
        }
    )
    with pytest.raises((ValueError, RuntimeError)):
        hook(catalog, payload)

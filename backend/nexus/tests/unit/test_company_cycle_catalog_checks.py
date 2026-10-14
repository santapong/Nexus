"""Complete configured metadata must bind real catalog entries before selection."""

from datetime import timedelta
from uuid import UUID

import pytest

from nexus.company.management.cycle_catalog_checks import validate_cycle_catalog
from nexus.company.management.model_profile_checks import validate_model_profile
from nexus.company.management.native_execution_profiles import NativeExecutionProfile
from nexus.company.management.plan_catalog import PlanAdmissionCatalog
from nexus.company.management.plans import ChildAllocation
from nexus.core.llm.company_registry import EvaluationEvidence, ModelHealth
from nexus.harness.standing_contracts import ToolPermission
from nexus.tests.unit.cycle_catalog_fixture import cycle_catalog
from nexus.tests.unit.test_company_model_observations import observed
from nexus.tests.unit.test_company_model_registry import NOW, model


def test_absent_cycle_preserves_existing_catalog_bytes() -> None:
    case = cycle_catalog()
    before = case.catalog.model_dump_json()
    assert validate_cycle_catalog(None, case.catalog) is None
    assert case.catalog.model_dump_json() == before


def test_complete_cycle_uses_actual_native_pair_sender_and_declared_catalog_pins() -> None:
    case = cycle_catalog()
    assert validate_cycle_catalog(case.admission, case.catalog) == case.admission
    assert case.catalog.models.models == ()
    assert case.catalog.model_observations == ()
    with pytest.raises(ValueError, match="no current registered model evidence"):
        validate_model_profile(case.catalog, case.admission.slots[0].child, NOW)


@pytest.mark.parametrize("profile", ["reasoning", "routine", "verification"])
def test_even_unselected_ordinary_profiles_must_be_admitted(profile: str) -> None:
    case = cycle_catalog()
    catalog = case.catalog.model_copy(
        update={"admitted_profiles": case.catalog.admitted_profiles - {profile}}
    )
    with pytest.raises(ValueError):
        validate_cycle_catalog(case.admission, catalog)


@pytest.mark.parametrize("position", [0, 1])
def test_both_actual_native_profiles_are_required(position: int) -> None:
    case = cycle_catalog()
    catalog = case.catalog.model_copy(
        update={"native_profiles": (case.catalog.native_profiles[position],)}
    )
    with pytest.raises(ValueError):
        validate_cycle_catalog(case.admission, catalog)


def test_actual_sender_profile_is_required_even_before_sender_stage() -> None:
    case = cycle_catalog()
    catalog = case.catalog.model_copy(update={"notification_profiles": ()})
    with pytest.raises(ValueError):
        validate_cycle_catalog(case.admission, catalog)


@pytest.mark.parametrize("position", [0, 1])
def test_enlarged_native_scope_cannot_enter_unambiguous_catalog(position: int) -> None:
    case = cycle_catalog()
    extra = ToolPermission(tool="company.builder.run.v1", tool_version="v1", resource="cycle.other")
    profiles = list(case.catalog.native_profiles)
    profiles[position] = profiles[position].model_copy(
        update={"tools": (*profiles[position].tools, extra)}
    )
    resource = case.catalog.resources[0]
    catalog = case.catalog.model_copy(
        update={
            "native_profiles": tuple(profiles),
            "tools": (*case.catalog.tools, extra),
            "resources": (
                *case.catalog.resources,
                resource.model_copy(update={"symbol": extra.resource}),
            ),
        }
    )
    with pytest.raises(ValueError, match="unambiguous"):
        validate_cycle_catalog(case.admission, catalog)


@pytest.mark.parametrize("field", ["native_profiles", "notification_profiles"])
@pytest.mark.parametrize("failure", ["digest", "duplicate", "company", "revision"])
def test_all_original_profile_tuples_validate_before_selection(field: str, failure: str) -> None:
    case = cycle_catalog()
    rows = getattr(case.catalog, field)
    changes = {
        "digest": {"registry_sha256": "f" * 64},
        "company": {"company_id": UUID(int=999)},
        "revision": {"registry_revision": "other"},
    }
    values = (
        (*rows, rows[-1])
        if failure == "duplicate"
        else (
            *rows[:-1],
            rows[-1].model_copy(update=changes[failure]),
        )
    )
    with pytest.raises(ValueError):
        validate_cycle_catalog(case.admission, case.catalog.model_copy(update={field: values}))


@pytest.mark.parametrize("failure", ["company", "models", "observation"])
def test_original_company_registry_and_observation_pins_are_not_filtered(failure: str) -> None:
    case = cycle_catalog()
    updates: dict[str, dict[str, object]] = {
        "company": {"company_id": UUID(int=999)},
        "models": {"models": case.catalog.models.model_copy(update={"revision": "other"})},
        "observation": {"model_observations": (observed(),)},
    }
    with pytest.raises(ValueError):
        validate_cycle_catalog(case.admission, case.catalog.model_copy(update=updates[failure]))


def test_bad_unselected_sender_tuple_denies_before_native_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = cycle_catalog()
    sender = case.catalog.notification_profiles[0].model_copy(update={"registry_sha256": "f" * 64})

    def unexpected_selection(
        _catalog: PlanAdmissionCatalog, _child: ChildAllocation
    ) -> NativeExecutionProfile | None:
        raise AssertionError("Native selection ran before full original tuple validation")

    monkeypatch.setattr(
        "nexus.company.management.cycle_catalog_checks.native_execution_profile",
        unexpected_selection,
    )
    with pytest.raises(ValueError, match="another exact catalog"):
        validate_cycle_catalog(
            case.admission,
            case.catalog.model_copy(update={"notification_profiles": (sender,)}),
        )


@pytest.mark.parametrize("failure", ["missing", "duplicate", "foreign", "different"])
def test_sender_requires_exact_single_same_company_resource_mapping(failure: str) -> None:
    case = cycle_catalog()
    resource = case.catalog.resources[0]
    changed = resource.model_copy(
        update={
            "resource": resource.resource.model_copy(
                update={"company_id" if failure == "foreign" else "resource_id": UUID(int=999)}
            )
        }
    )
    resources = {
        "missing": (),
        "duplicate": (resource, resource),
        "foreign": (changed,),
        "different": (changed,),
    }
    with pytest.raises(ValueError):
        validate_cycle_catalog(
            case.admission, case.catalog.model_copy(update={"resources": resources[failure]})
        )


@pytest.mark.parametrize("failure", ["version", "resource", "duplicate"])
def test_all_exact_slot_tools_must_exist_unambiguously(failure: str) -> None:
    case = cycle_catalog()
    tool = case.catalog.tools[-1]
    changed = tool.model_copy(
        update={"tool_version": "v2"} if failure == "version" else {"resource": "cycle.other"}
    )
    tools = {
        "version": (*case.catalog.tools[:-1], changed),
        "resource": (*case.catalog.tools[:-1], changed),
        "duplicate": (*case.catalog.tools, tool),
    }
    with pytest.raises(ValueError):
        validate_cycle_catalog(
            case.admission, case.catalog.model_copy(update={"tools": tools[failure]})
        )


@pytest.mark.parametrize("position", range(6))
def test_missing_any_declared_tool_including_future_ordinary_roles_denies(position: int) -> None:
    case = cycle_catalog()
    tools = case.catalog.tools[:position] + case.catalog.tools[position + 1 :]
    with pytest.raises(ValueError):
        validate_cycle_catalog(case.admission, case.catalog.model_copy(update={"tools": tools}))


def test_ordinary_slot_requires_its_resource_mapping_before_health_or_selection() -> None:
    case = cycle_catalog()
    original = case.admission.slots[0].tool
    changed = original.model_copy(update={"resource": "cycle.other"})
    slots = tuple(
        slot.model_copy(update={"tool": changed}) if slot.tool == original else slot
        for slot in case.admission.slots
    )
    tools = tuple(changed if tool == original else tool for tool in case.catalog.tools)
    with pytest.raises(ValueError, match="exact catalog mapping"):
        validate_cycle_catalog(
            case.admission.model_copy(update={"slots": slots}),
            case.catalog.model_copy(update={"tools": tools}),
        )


def test_every_unselected_verifier_recipe_is_required() -> None:
    case = cycle_catalog()
    for recipe in case.catalog.check_recipes:
        catalog = case.catalog.model_copy(
            update={"check_recipes": case.catalog.check_recipes - {recipe}}
        )
        with pytest.raises(ValueError):
            validate_cycle_catalog(case.admission, catalog)


@pytest.mark.parametrize("value", [True, 1.0, "1"])
def test_copied_raw_unselected_quota_denies_before_dump(value: object) -> None:
    case = cycle_catalog()
    slots = list(case.admission.slots)
    selected = slots[4]
    slots[4] = selected.model_copy(
        update={
            "child": selected.child.model_copy(
                update={"quota": selected.child.quota.model_copy(update={"model_requests": value})}
            )
        }
    )
    with pytest.raises(ValueError):
        validate_cycle_catalog(
            case.admission.model_copy(update={"slots": tuple(slots)}), case.catalog
        )


def test_unselected_malformed_full_plan_still_denies() -> None:
    case = cycle_catalog()
    slots = list(case.admission.slots)
    slots[6] = slots[6].model_copy(
        update={"work": slots[6].work.model_copy(update={"acceptance": ("duplicate", "duplicate")})}
    )
    with pytest.raises(ValueError):
        validate_cycle_catalog(
            case.admission.model_copy(update={"slots": tuple(slots)}), case.catalog
        )


@pytest.mark.parametrize("health", ["healthy", "unknown", "expired"])
def test_structural_eligibility_does_not_substitute_for_current_model_health(health: str) -> None:
    original = cycle_catalog()
    registration = model(
        price=None,
        health=ModelHealth(
            status="unknown" if health == "unknown" else "healthy",
            checked_at=NOW - timedelta(minutes=5),
            expires_at=NOW if health == "expired" else NOW + timedelta(minutes=5),
        ),
        evaluations=(
            EvaluationEvidence(
                profile="reasoning",
                suite_version="synthetic",
                artifact_reference="fixture:evaluation",
                score="0.9",
                conformance_passed=True,
                evaluated_at=NOW - timedelta(days=1),
                expires_at=NOW + timedelta(days=1),
            ),
        ),
    )
    registry = original.catalog.models.model_copy(update={"models": (registration,)})
    case = cycle_catalog(registry)
    assert validate_cycle_catalog(case.admission, case.catalog) == case.admission
    if health == "healthy":
        validate_model_profile(case.catalog, case.admission.slots[0].child, NOW)
        return
    with pytest.raises(ValueError, match="no current registered model evidence"):
        validate_model_profile(case.catalog, case.admission.slots[0].child, NOW)

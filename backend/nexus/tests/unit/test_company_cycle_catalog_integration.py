"""Explicit cycle metadata narrows validation but cannot activate mixed work or model authority."""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from nexus.company.management.canonical import canonical_json
from nexus.company.management.governance import CharterRevision
from nexus.company.management.model_profile_checks import validate_model_profile
from nexus.company.management.native_execution_profiles import require_native_plan
from nexus.company.management.plan_catalog import PlanAdmissionCatalog
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.notifications.native_profile_checks import require_notification_plan
from nexus.tests.unit.cycle_admission_fixture import declared
from nexus.tests.unit.cycle_catalog_fixture import CycleCatalog, cycle_catalog
from nexus.tests.unit.test_company_model_registry import NOW, model


def configured() -> PlanAdmissionCatalog:
    case = cycle_catalog()
    return PlanAdmissionCatalog.model_validate(
        case.catalog.model_dump() | {"cycle_admission": case.admission}
    )


def test_absent_cycle_is_excluded_from_existing_canonical_wire() -> None:
    case = cycle_catalog()
    checked = PlanAdmissionCatalog.model_validate(
        case.catalog.model_dump() | {"cycle_admission": None}
    )
    assert "cycle_admission" not in checked.model_dump()
    assert canonical_json(checked) == canonical_json(case.catalog)


def test_exact_full_structural_layout_does_not_substitute_for_current_model_evidence() -> None:
    catalog = configured()
    admission = catalog.cycle_admission
    assert admission is not None
    payload = declared(admission, 2)
    require_native_plan(catalog, payload)
    require_notification_plan(catalog, payload)
    with pytest.raises(ValueError, match="no current registered model evidence"):
        validate_model_profile(catalog, admission.slots[0].child, NOW)


@pytest.mark.parametrize("bad", [True, 1.0, "1"])
def test_store_checks_copied_raw_quota_before_json_reconstruction(bad: object) -> None:
    catalog = configured()
    admission = catalog.cycle_admission
    assert admission is not None
    slot = admission.slots[4]
    changed = slot.model_copy(
        update={
            "child": slot.child.model_copy(
                update={"quota": slot.child.quota.model_copy(update={"model_requests": bad})}
            )
        }
    )
    admission = admission.model_copy(
        update={"slots": (*admission.slots[:4], changed, *admission.slots[5:])}
    )
    with pytest.raises(ValueError):
        ManagementPlanStore(MagicMock(), catalog.model_copy(update={"cycle_admission": admission}))


def test_native_profile_early_return_still_rejects_corrupt_unselected_cycle() -> None:
    catalog = configured()
    admission = catalog.cycle_admission
    assert admission is not None
    malformed = admission.model_copy(update={"registry_sha256": "f" * 64})
    catalog = catalog.model_copy(update={"cycle_admission": malformed})
    with pytest.raises(ValueError):
        validate_model_profile(catalog, admission.slots[2].child, NOW)


def test_selected_model_view_clears_cycle_only_after_full_original_validation() -> None:
    from nexus.company.management.plan_support import validate_plan_action
    from nexus.core.llm.company_registry import EvaluationEvidence
    from nexus.tests.unit.test_company_foundation import proposal

    original = cycle_catalog()
    evaluation = EvaluationEvidence(
        profile="reasoning",
        suite_version="synthetic",
        artifact_reference="fixture:evaluation",
        score=Decimal("0.9"),
        conformance_passed=True,
        evaluated_at=NOW - timedelta(days=1),
        expires_at=NOW + timedelta(days=1),
    )
    registry = original.catalog.models.model_copy(
        update={
            "models": (
                model("fixture-a", price=None, evaluations=(evaluation,)),
                model("fixture-b", price=None, evaluations=(evaluation,)),
            )
        }
    )
    case = cycle_catalog(registry)
    catalog = PlanAdmissionCatalog.model_validate(
        case.catalog.model_dump() | {"cycle_admission": case.admission}
    )
    action = proposal().model_copy(
        update={"tool": "model.request.v1", "tool_version": "v1", "resource": "model:fixture-a"}
    )
    validate_plan_action(
        catalog,
        case.admission.slots[0].child,
        declared_charter(case),
        action,
        "model_requests",
        NOW,
    )
    corrupt = catalog.model_copy(
        update={"cycle_admission": case.admission.model_copy(update={"registry_sha256": "f" * 64})}
    )
    with pytest.raises(ValueError):
        validate_plan_action(
            corrupt,
            case.admission.slots[0].child,
            declared_charter(case),
            action,
            "model_requests",
            NOW,
        )


def declared_charter(case: CycleCatalog) -> CharterRevision:
    from nexus.company.contracts.company import DepartmentCharter
    from nexus.company.management.canonical import canonical_sha256
    from nexus.company.management.governance import CharterRevision

    slot = case.admission.slots[0]
    ref = slot.child.charter
    value = DepartmentCharter(
        company_id=case.admission.company_id,
        department_id=ref.department_id,
        name="strategy",
        version=ref.version,
        responsibilities=("Bounded strategy",),
        allowed_tools=tuple(t.tool for t in case.catalog.tools),
        resource_scopes=(slot.tool.resource,),
        deliverables=("Typed brief",),
        verifier_id=case.admission.slots[1].child.binding.actor_id,
    )
    return CharterRevision(
        **ref.model_dump(exclude={"sha256"}),
        sha256=canonical_sha256(value),
        charter=value,
        mandate=case.admission.mandate,
        recorded_by=slot.child.binding.actor_id,
        recorded_at=NOW,
    )


def test_ordinary_cycle_nonmodel_effect_cannot_borrow_sibling_tool() -> None:
    from nexus.company.management.plan_support import validate_plan_action
    from nexus.tests.unit.test_company_foundation import proposal

    case = cycle_catalog()
    catalog = configured()
    slot = case.admission.slots[0]
    good = proposal().model_copy(
        update={
            "tool": slot.tool.tool,
            "tool_version": slot.tool.tool_version,
            "resource": slot.tool.resource,
        }
    )
    validate_plan_action(catalog, slot.child, declared_charter(case), good, "tool_attempts", NOW)
    other = case.admission.slots[1].tool
    with pytest.raises(ValueError, match="exact declared role tuple"):
        validate_plan_action(
            catalog,
            slot.child,
            declared_charter(case),
            good.model_copy(update={"tool": other.tool}),
            "tool_attempts",
            NOW,
        )


def test_managed_artifact_write_cannot_spend_the_model_request_slice() -> None:
    from nexus.company.management.plan_support import validate_plan_action
    from nexus.tests.unit.test_company_foundation import proposal

    case = cycle_catalog()
    slot = case.admission.slots[0]
    action = proposal().model_copy(
        update={
            "tool": slot.tool.tool,
            "tool_version": slot.tool.tool_version,
            "resource": slot.tool.resource,
        }
    )
    with pytest.raises(ValueError, match="tool-attempt"):
        validate_plan_action(
            configured(), slot.child, declared_charter(case), action, "model_requests", NOW
        )

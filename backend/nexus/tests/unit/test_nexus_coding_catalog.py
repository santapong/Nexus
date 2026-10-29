"""Concrete full-ten server catalogs and old-wire compatibility; no model/native activation."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.nexus_coding_admission import NexusCodingAdmission
from nexus.company.management.nexus_coding_catalog import (
    configured_nexus_admission,
    select_configured_nexus_plan,
    validate_nexus_coding_catalog,
)
from nexus.company.management.plan_catalog import NamedPlanResource, PlanAdmissionCatalog
from nexus.core.llm.company_registry import ModelRegistry
from nexus.execution.planning_application_config import PlanningApplicationConfig
from nexus.tests.unit.nexus_cycle_fixture import case, key
from nexus.tests.unit.planning_application_fixture import configuration
from nexus.tests.unit.test_nexus_coding_admission import admission, planning_origin


@pytest.mark.parametrize(
    "field",
    [
        None,
        "budget_usd",
        "acceptance",
        "task_id",
        "trace_id",
        "goal_id",
        "department",
        "depends_on",
    ],
)
def test_only_admitted_display_title_is_normalized_against_fixed_work(field: str | None) -> None:
    from decimal import Decimal
    from uuid import UUID

    from nexus.company.management.nexus_coding_catalog import coding_work_matches_template

    fixed = admission().slots[1].work
    actual = fixed.model_copy(update={"title": "Model proposed coder"})
    if field is not None:
        values = {
            "budget_usd": Decimal(".2"),
            "acceptance": ("changed",),
            "task_id": UUID(int=999),
            "trace_id": UUID(int=998),
            "goal_id": UUID(int=997),
            "department": "other",
            "depends_on": (UUID(int=996),),
        }
        actual = actual.model_copy(update={field: values[field]})
    assert coding_work_matches_template(actual, fixed) is (field is None)
    assert actual.title == "Model proposed coder" and fixed.title == "Synthetic Nexus coder"


def coding_case() -> tuple[NexusCodingAdmission, PlanAdmissionCatalog]:
    """Distinct L/C/S/P/U targets and providers are supplied metadata, never live quality."""
    value, old = admission(), case()[1]
    original = old.models.models[0]
    models = tuple(
        original.model_copy(
            update={
                "registry_id": slot.tool.resource.removeprefix("model:"),
                "model_id": "gemini-3.5-flash-lite" if slot.role == "coder" else original.model_id,
                "provider": "google" if slot.role == "coder" else "openai",
                "endpoint_id": "synthetic." + slot.role,
                "context_window": 1048576 if slot.role == "coder" else original.context_window,
                "api_family": "google_generate_content"
                if slot.role == "coder"
                else "openai_responses",
                "capabilities": frozenset(
                    {"text", "reasoning", "structured_output", "code", "tools"}
                ),
                "evaluations": (
                    *original.evaluations,
                    original.evaluations[0].model_copy(update={"profile": "engineering"}),
                ),
                "health": original.health.model_copy(
                    update={"expires_at": original.health.expires_at + timedelta(minutes=index)}
                ),
            }
        )
        for index, slot in enumerate(value.slots[:5])
    )
    registry = ModelRegistry(
        company_id=value.company_id,
        revision=value.registry_revision,
        pricebook_version=old.models.pricebook_version,
        models=models,
    )
    digest = canonical_sha256(registry)
    value = NexusCodingAdmission.model_validate(
        value.model_copy(update={"registry_sha256": digest}).model_dump()
    )
    tools = tuple(dict.fromkeys(slot.tool for slot in value.slots))
    resources = tuple(
        NamedPlanResource(
            symbol=symbol,
            resource=ResourceRef(
                company_id=value.company_id, resource_id=key("coding-resource:" + symbol)
            ),
        )
        for symbol in dict.fromkeys(slot.tool.resource for slot in value.slots)
    )
    catalog = PlanAdmissionCatalog(
        company_id=value.company_id,
        tools=tools,
        resources=resources,
        models=registry,
        admitted_profiles=frozenset({"reasoning", "engineering", "routine", "verification"}),
        check_recipes=old.check_recipes,
        native_profiles=tuple(
            row.model_copy(update={"registry_sha256": digest}) for row in old.native_profiles
        ),
        notification_profiles=tuple(
            row.model_copy(
                update={
                    "registry_sha256": digest,
                    "target_resource": next(
                        row.resource
                        for row in resources
                        if row.symbol == value.slots[-1].tool.resource
                    ),
                }
            )
            for row in old.notification_profiles
        ),
        nexus_coding_admission=value,
    )
    return value, catalog


def coding_configuration(root: Path) -> PlanningApplicationConfig:
    value, catalog = coding_case()
    data = configuration(root).model_copy(
        update={
            "catalog": catalog,
            "registry_id": value.slots[0].tool.resource.removeprefix("model:"),
        }
    )
    return PlanningApplicationConfig.model_validate_json(data.model_dump_json())


def test_distinct_role_models_and_full_profiles_are_exact_configured_choices() -> None:
    value, catalog = coding_case()
    assert configured_nexus_admission(catalog) == value
    assert validate_nexus_coding_catalog(value, catalog) == value
    assert len({row.tool.resource for row in value.slots[:5]}) == 5
    assert {row.provider for row in catalog.models.models} == {"openai", "google"}
    assert select_configured_nexus_plan(catalog, value.payload("planning")) == "planning"
    assert (
        select_configured_nexus_plan(
            catalog, value.payload("execution", origin=planning_origin(value))
        )
        == "execution"
    )


@pytest.mark.parametrize(
    "fault",
    [
        "exclusive",
        "missing-tool",
        "duplicate-tool",
        "mixed-version",
        "foreign-resource",
        "registry",
        "missing-model",
        "wrong-profile",
        "native",
        "sender",
    ],
)
def test_catalog_rejects_role_tuple_profile_registry_and_ordinary_fallback(fault: str) -> None:
    _value, catalog = coding_case()
    data = catalog.model_dump()
    if fault == "exclusive":
        data["nexus_cycle_admission"] = case()[0].model_dump()
    elif fault == "missing-tool":
        data["tools"] = data["tools"][1:]
    elif fault == "duplicate-tool":
        data["tools"] = (*data["tools"], data["tools"][0])
    elif fault == "mixed-version":
        data["tools"][1]["tool_version"] = "v2"
    elif fault == "foreign-resource":
        data["resources"] = data["resources"][1:]
    elif fault == "registry":
        data["nexus_coding_admission"]["registry_sha256"] = "f" * 64
    elif fault == "missing-model":
        data["models"]["models"] = data["models"]["models"][1:]
    elif fault == "wrong-profile":
        data["admitted_profiles"] = frozenset({"routine"})
    elif fault == "native":
        data["native_profiles"] = ()
    else:
        data["notification_profiles"] = ()
    with pytest.raises(ValueError):
        PlanAdmissionCatalog.model_validate(data)


def test_absent_new_field_preserves_old_wire_and_original_tool_uniqueness() -> None:
    _, old = case()
    assert "nexus_coding_admission" not in old.model_dump_json()
    assert configured_nexus_admission(old) == old.nexus_cycle_admission
    data = old.model_dump()
    data["tools"] = (*data["tools"], data["tools"][0].copy())
    data["tools"][-1]["resource"] = "another:model"
    with pytest.raises(ValueError):
        PlanAdmissionCatalog.model_validate(data)


def test_planning_configuration_uses_full_profile_planner_without_relabeling_recipe(
    tmp_path: Path,
) -> None:
    value = coding_configuration(tmp_path)
    assert value.admission == value.catalog.nexus_coding_admission
    assert value.goal == value.admission.goal
    assert value.role_policy.model_profile == value.recipe.profile == "reasoning"
    assert value.admission.slots[0].child.binding.workflow_name == "company.planning.v1"
    assert datetime.now(UTC).utcoffset() is not None


def test_healthy_other_role_cannot_rescue_expired_exact_planner_target() -> None:
    from nexus.company.management.plan_admission_candidates import capture_child_window

    value, catalog = coding_case()
    now = datetime.now(UTC)
    window = capture_child_window(catalog, value.slots[0].child, now)
    later = catalog.models.models[0].health.expires_at + timedelta(microseconds=1)
    with pytest.raises(ValueError):
        window.require_time(later)
    with pytest.raises(ValueError):
        capture_child_window(catalog, value.slots[0].child, later)


def test_broad_charter_cannot_choose_another_roles_model_resource() -> None:
    from nexus.company.contracts.actions import ActionProposal
    from nexus.company.contracts.company import DepartmentCharter
    from nexus.company.management.governance import CharterRevision
    from nexus.company.management.plan_support import validate_plan_action

    value, catalog = coding_case()
    slot = value.slots[0]
    body = DepartmentCharter(
        company_id=value.company_id,
        department_id=slot.child.charter.department_id,
        name=slot.work.department,
        version="v1",
        responsibilities=("synthetic bounded task",),
        allowed_tools=("model.request.v1",),
        resource_scopes=(slot.tool.resource, value.slots[1].tool.resource),
        deliverables=("model output",),
        verifier_id=key("synthetic-verifier"),
    )
    charter = CharterRevision(
        company_id=value.company_id,
        revision_id=slot.child.charter.revision_id,
        department_id=body.department_id,
        version="v1",
        sha256=canonical_sha256(body),
        charter=body,
        mandate=value.mandate,
        recorded_by=value.procedure.binding.actor_id,
        recorded_at=datetime.now(UTC),
    )
    proposal = ActionProposal(
        company_id=value.company_id,
        action_id=key("crossed-model-action"),
        task_id=slot.work.task_id,
        trace_id=slot.work.trace_id,
        actor_id=slot.child.binding.actor_id,
        revision=1,
        tool="model.request.v1",
        tool_version="v1",
        resource=value.slots[1].tool.resource,
        parameters={},
        policy_version="p1",
        price_version="p1",
        estimated_cost_usd=".01",
    )
    with pytest.raises(ValueError, match="exact configured role"):
        validate_plan_action(
            catalog, slot.child, charter, proposal, "model_requests", datetime.now(UTC)
        )


async def test_actual_source_classification_is_checked_before_model_body_read() -> None:
    from unittest.mock import AsyncMock, MagicMock

    from sqlalchemy.ext.asyncio import AsyncSession

    from nexus.company.brain.access_models import BrainResource, BrainResourceAccess
    from nexus.company.brain.base import BrainReadScope
    from nexus.company.brain.source_models import BrainSource, BrainSourceHead
    from nexus.company.management.plan_support import _resource

    value, catalog = coding_case()
    ref = catalog.resources[0].resource
    principal = value.slots[0].child.binding.actor_id
    rows = {
        BrainResource: BrainResource(active=True, kind="source"),
        BrainResourceAccess: BrainResourceAccess(active=True, expires_at=None),
        BrainSourceHead: BrainSourceHead(availability="available"),
    }
    session = MagicMock(spec=AsyncSession)
    session.get = AsyncMock(side_effect=lambda cls, selector: rows.get(cls))
    session.scalar = AsyncMock(
        return_value=BrainSource(
            source_id=key("restricted-source"), data_classification="restricted"
        )
    )
    scope = BrainReadScope(
        company_id=value.company_id,
        workspace_id=value.procedure.binding.workspace_id,
        principal_id=principal,
        operation_id=key("classification-read"),
        trace_id=key("classification-trace"),
    )
    with pytest.raises(ValueError, match="source classification"):
        await _resource(
            session,
            value.company_id,
            ref,
            {principal},
            datetime.now(UTC),
            scope,
            None,
            catalog.models.models[0].allowed_data,
        )


def test_coding_payload_metadata_cannot_be_laundered_through_old_or_ordinary_catalog() -> None:
    from nexus.company.management.plans import PlanPayload

    value, catalog = coding_case()
    payload = value.payload("planning")
    with pytest.raises(ValueError):
        select_configured_nexus_plan(
            catalog.model_copy(update={"nexus_coding_admission": None}), payload
        )
    old = case()[0].payload("planning").model_dump()
    old["coding_admission_sha256"] = canonical_sha256(value)
    with pytest.raises(ValueError):
        PlanPayload.model_validate(old)

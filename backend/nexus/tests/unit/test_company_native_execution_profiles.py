"""Explicit mechanical identity cannot invent model eligibility or executable authority."""

from datetime import UTC, datetime
from typing import Literal

import pytest
from pydantic import ValidationError

from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.model_profile_checks import validate_model_profile
from nexus.company.management.native_execution_profiles import (
    NATIVE_CRITERIA,
    NativeExecutionProfile,
    native_execution_profile,
    require_native_plan,
    validate_native_profiles,
)
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.company.management.plans import PlanPayload
from nexus.core.llm.company_registry import ModelRegistry
from nexus.execution.runtime_contracts import AttemptQuota
from nexus.harness.standing_contracts import ToolPermission
from nexus.tests.unit.test_company_management_plans import payload


def mechanical() -> tuple[PlanAdmissionCatalog, PlanPayload]:
    """A new mechanical declaration has no model, reused allowance or live qualification."""
    # The >50-line fixture retains complete constructor data rather than hidden grant flags.
    data = payload()
    registry = ModelRegistry(
        company_id=data.company_id, revision="native-catalog-v1", pricebook_version="p1"
    )
    permission = ToolPermission(
        tool="company.builder.run.v1", tool_version="v1", resource="engineering.source"
    )
    identities: tuple[
        tuple[
            Literal["engineering.native.v1", "verification.native.v1"],
            Literal["engineering.change", "engineering.verify"],
        ],
        ...,
    ] = (
        ("engineering.native.v1", "engineering.change"),
        ("verification.native.v1", "engineering.verify"),
    )
    profiles = tuple(
        NativeExecutionProfile(
            company_id=data.company_id,
            execution_profile=name,
            workflow_name=workflow,
            registry_revision=registry.revision,
            registry_sha256=canonical_sha256(registry),
            tools=(permission,),
        )
        for name, workflow in identities
    )
    children = tuple(
        child.model_copy(
            update={
                "binding": child.binding.model_copy(
                    update={
                        "workflow_name": profile.workflow_name,
                        "workflow_version": profile.workflow_version,
                        "model_profile": profile.execution_profile,
                        "model_registry_version": registry.revision,
                    }
                ),
                "quota": AttemptQuota(
                    model_requests=0, tool_attempts=1, rework_rounds=0, plan_revisions=0
                ),
            }
        )
        for child, profile in zip(data.children, profiles, strict=True)
    )
    data = data.model_copy(
        update={
            "children": children,
            "procedure": data.procedure.model_copy(
                update={
                    "quota": AttemptQuota(model_requests=0),
                    "binding": data.procedure.binding.model_copy(
                        update={
                            "workflow_name": "engineering.change",
                            "workflow_version": "v1",
                            "model_profile": "engineering.native.v1",
                            "model_registry_version": registry.revision,
                        }
                    ),
                }
            ),
            "plan": data.plan.model_copy(
                update={
                    "items": tuple(
                        item.model_copy(update={"acceptance": NATIVE_CRITERIA})
                        for item in data.plan.items
                    )
                }
            ),
            "verification": (
                data.verification[0].model_copy(
                    update={"check_recipe": "native-engineering-change-v1"}
                ),
            ),
        }
    )
    catalog = PlanAdmissionCatalog(
        company_id=data.company_id,
        models=registry,
        admitted_profiles=frozenset(),
        check_recipes=frozenset({"native-engineering-change-v1"}),
        tools=(permission,),
        native_profiles=profiles,
    )
    return catalog, data


def test_empty_models_require_exact_native_work_and_preserve_default_serialization() -> None:
    catalog, data = mechanical()
    require_native_plan(catalog, data)
    for child in data.children:
        validate_model_profile(catalog, child, datetime.now(UTC))
    old = catalog.model_copy(update={"native_profiles": ()})
    assert "native_profiles" not in old.model_dump(mode="json")
    with pytest.raises(ValueError):
        validate_model_profile(old, data.children[0], datetime.now(UTC))
    with pytest.raises(ValueError):
        validate_model_profile(catalog, payload().children[0], datetime.now(UTC))


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("model_registry_version", "other"),
        ("workflow_name", "internal.report"),
        ("workflow_version", "v2"),
        ("model_profile", "engineering"),
    ],
)
def test_partial_native_binding_never_admits(field: str, bad: str) -> None:
    catalog, data = mechanical()
    child = data.children[0]
    changed = child.model_copy(update={"binding": child.binding.model_copy(update={field: bad})})
    with pytest.raises(ValueError):
        validate_model_profile(catalog, changed, datetime.now(UTC))


@pytest.mark.parametrize("bad", [False, True, 1, 12])
def test_native_child_cannot_select_positive_or_coerced_model_quota(bad: object) -> None:
    catalog, data = mechanical()
    if type(bad) is not int:
        with pytest.raises(ValidationError):
            AttemptQuota.model_validate({"model_requests": bad})
        return
    child = data.children[0].model_copy(update={"quota": AttemptQuota(model_requests=bad)})
    with pytest.raises(ValueError):
        native_execution_profile(catalog, child)


@pytest.mark.parametrize("failure", ["duplicate", "digest", "company", "tool", "pair"])
def test_complete_native_configuration_rejects_ambiguity(failure: str) -> None:
    catalog, _ = mechanical()
    original = catalog.native_profiles[0]
    if failure == "duplicate":
        profiles = (*catalog.native_profiles, original)
    else:
        updates: dict[str, dict[str, object]] = {
            "digest": {"registry_sha256": "f" * 64},
            "company": {"company_id": payload().procedure.procedure_id},
            "tool": {
                "tools": (
                    ToolPermission(tool="model.request.v1", tool_version="v1", resource="model:x"),
                )
            },
            "pair": {"workflow_name": "engineering.verify"},
        }
        profiles = (original.model_copy(update=updates[failure]), catalog.native_profiles[1])
    with pytest.raises(ValueError):
        validate_native_profiles(catalog.models, profiles)
    with pytest.raises(ValueError):
        native_execution_profile(
            catalog.model_copy(update={"native_profiles": profiles}), mechanical()[1].children[0]
        )


@pytest.mark.parametrize("failure", ["parent", "mixed", "recipe", "criteria", "edge"])
def test_native_plan_requires_closed_pair_zero_parent_and_actual_engineering_edge(
    failure: str,
) -> None:
    catalog, data = mechanical()
    changes: dict[str, dict[str, object]] = {
        "parent": {"procedure": data.procedure.model_copy(update={"quota": AttemptQuota()})},
        "mixed": {"children": (payload().children[0], data.children[1])},
        "recipe": {
            "verification": (
                data.verification[0].model_copy(update={"check_recipe": "report.check.v1"}),
            )
        },
        "criteria": {"plan": payload().plan},
        "edge": {"verification": ()},
    }
    with pytest.raises(ValueError):
        require_native_plan(catalog, data.model_copy(update=changes[failure]))

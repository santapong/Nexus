"""One pure coexistence probe: full catalog native pins survive model selection."""

from datetime import timedelta
from uuid import UUID

import pytest

from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.governance import CharterRevision
from nexus.company.management.native_execution_profiles import NativeExecutionProfile
from nexus.company.management.plan_support import (
    PlanAdmissionCatalog,
    validate_plan_action,
    validate_plan_profile,
)
from nexus.harness.standing_contracts import ToolPermission
from nexus.tests.management_control_support import charter
from nexus.tests.unit.test_company_foundation import proposal
from nexus.tests.unit.test_company_management_plans import payload
from nexus.tests.unit.test_company_model_observations import child, observed
from nexus.tests.unit.test_company_model_registry import COMPANY, NOW, model, registry


def test_valid_unselected_native_profiles_do_not_invalidate_selected_model_action() -> None:
    # Keep the >50-line pure fixture's full catalog, observation and action data together.
    original = registry(model(), model("fixture-b"))
    tool = ToolPermission(
        tool="company.builder.run.v1", tool_version="v1", resource="engineering.source"
    )
    native = tuple(
        NativeExecutionProfile.model_validate(
            {
                "company_id": COMPANY,
                "execution_profile": name,
                "workflow_name": workflow,
                "registry_revision": original.revision,
                "registry_sha256": canonical_sha256(original),
                "tools": (tool,),
            }
        )
        for name, workflow in (
            ("engineering.native.v1", "engineering.change"),
            ("verification.native.v1", "engineering.verify"),
        )
    )
    common = {
        "company_id": COMPANY,
        "models": original,
        "admitted_profiles": frozenset({"engineering"}),
        "check_recipes": frozenset({"native-engineering-change-v1"}),
        "tools": (tool,),
        "model_observations": (observed(),),
    }
    ordinary = PlanAdmissionCatalog.model_validate(common)
    configured = PlanAdmissionCatalog.model_validate(common | {"native_profiles": native})
    declaration = charter()
    selected_charter = CharterRevision(
        company_id=COMPANY,
        department_id=declaration.department_id,
        revision_id=UUID(int=806),
        version=declaration.version,
        sha256=canonical_sha256(declaration),
        charter=declaration,
        mandate=payload().mandate,
        recorded_by=UUID(int=3),
        recorded_at=NOW,
    )
    action = proposal().model_copy(
        update={"tool": "model.request.v1", "tool_version": "v1", "resource": "model:fixture-a"}
    )
    now = NOW + timedelta(minutes=10)
    validate_plan_profile(configured, child(), now)
    validate_plan_action(ordinary, child(), selected_charter, action, "model_requests", now)
    validate_plan_action(configured, child(), selected_charter, action, "model_requests", now)


def test_model_selection_still_rejects_a_corrupt_unselected_native_tuple() -> None:
    original = registry(model(), model("fixture-b"))
    tool = ToolPermission(
        tool="company.builder.run.v1", tool_version="v1", resource="engineering.source"
    )
    native = NativeExecutionProfile(
        company_id=COMPANY,
        execution_profile="verification.native.v1",
        workflow_name="engineering.verify",
        registry_revision=original.revision,
        registry_sha256=canonical_sha256(original),
        tools=(tool,),
    )
    catalog = PlanAdmissionCatalog(
        company_id=COMPANY,
        models=original,
        admitted_profiles=frozenset({"engineering"}),
        check_recipes=frozenset({"native-engineering-change-v1"}),
        tools=(tool,),
        model_observations=(observed(),),
        native_profiles=(native,),
    ).model_copy(
        update={"native_profiles": (native.model_copy(update={"registry_sha256": "f" * 64}),)}
    )
    declaration = charter()
    selected_charter = CharterRevision(
        company_id=COMPANY,
        department_id=declaration.department_id,
        revision_id=UUID(int=806),
        version=declaration.version,
        sha256=canonical_sha256(declaration),
        charter=declaration,
        mandate=payload().mandate,
        recorded_by=UUID(int=3),
        recorded_at=NOW,
    )
    action = proposal().model_copy(
        update={
            "tool": "model.request.v1",
            "tool_version": "v1",
            "resource": "model:fixture-a",
        }
    )
    with pytest.raises(ValueError, match="another exact catalog"):
        validate_plan_action(catalog, child(), selected_charter, action, "model_requests", NOW)

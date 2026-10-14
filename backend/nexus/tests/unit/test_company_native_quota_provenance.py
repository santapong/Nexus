"""Corrupt typed zero quotas must be rejected before JSON can normalize their provenance."""

import pytest

from nexus.company.management.native_execution_profiles import (
    native_execution_profile,
    require_native_plan,
)
from nexus.tests.unit.test_company_native_execution_profiles import mechanical


def test_copied_engineering_child_bool_is_rejected_before_serialization() -> None:
    catalog, plan = mechanical()
    child = plan.children[0]
    corrupted = child.model_copy(
        update={"quota": child.quota.model_copy(update={"model_requests": False})}
    )
    with pytest.raises(ValueError):
        native_execution_profile(catalog, corrupted)


def test_copied_engineering_procedure_bool_is_rejected_before_serialization() -> None:
    catalog, plan = mechanical()
    corrupted = plan.model_copy(
        update={
            "procedure": plan.procedure.model_copy(
                update={"quota": plan.procedure.quota.model_copy(update={"model_requests": False})}
            )
        }
    )
    with pytest.raises(ValueError):
        require_native_plan(catalog, corrupted)

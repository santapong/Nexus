"""Path-free model-origin selectors cannot provide actor, workflow or budget authority."""

from uuid import UUID

import pytest

from nexus.company.management.planning_origin_contracts import PlanningOriginRef
from nexus.tests.unit.test_company_planning_intent import prepared_inputs


def origin() -> PlanningOriginRef:
    _, _, binding, _, _, _ = prepared_inputs()
    return PlanningOriginRef(
        company_id=binding.goal.company_id,
        goal=binding.goal,
        source_plan_id=binding.plan_id,
        source_plan_revision_id=UUID(int=50),
        task_id=UUID(int=6),
        action_id=UUID(int=5),
        request_id=UUID(int=7),
        receipt_id=UUID(int=8),
        artifact_id=UUID(int=9),
        artifact_sha256="a" * 64,
        request_sha256="b" * 64,
        context_manifest_sha256=binding.context_manifest_sha256,
        content_sha256="c" * 64,
        mapping_revision="v1",
        mapping_sha256="d" * 64,
    )


@pytest.mark.parametrize("field", ["actor_id", "workflow", "budget_usd", "reference", "approved"])
def test_origin_is_a_closed_reference_not_authority(field: str) -> None:
    with pytest.raises(ValueError):
        PlanningOriginRef.model_validate(origin().model_dump() | {field: "caller supplied"})


def test_foreign_goal_and_invalid_digest_are_denied() -> None:
    for changed in ({"company_id": UUID(int=99)}, {"artifact_sha256": "bad"}):
        with pytest.raises(ValueError):
            PlanningOriginRef.model_validate(origin().model_dump() | changed)

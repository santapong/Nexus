"""Closed pair layout negatives; SQL current membership/procedure proof is a later actual gate."""

from uuid import UUID

import pytest

from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.lifecycle import PlanRevisionRef
from nexus.company.management.plans import PlanPayload
from nexus.company.strategy.contracts import STRATEGY_CHECK_CRITERIA, StrategyScope
from nexus.company.strategy.pair_reader import require_pair_layout
from nexus.tests.unit.cycle_admission_fixture import cycle


def pair_layout() -> tuple[PlanPayload, StrategyScope]:
    payload = cycle().strategy
    items = tuple(
        row.model_copy(update={"acceptance": STRATEGY_CHECK_CRITERIA}) for row in payload.plan.items
    )
    payload = payload.model_copy(update={"plan": payload.plan.model_copy(update={"items": items})})
    payload = PlanPayload.model_validate(payload.model_dump(warnings=False))
    scope = StrategyScope(
        company_id=payload.company_id,
        goal=payload.goal,
        producing_plan=PlanRevisionRef(
            company_id=payload.company_id,
            plan_id=payload.plan.plan_id,
            plan_revision_id=UUID(int=800),
            revision=1,
            sha256=canonical_sha256(payload),
        ),
        author=payload.children[0].binding,
        verifier=payload.children[1].binding,
        author_registration_sha256="a" * 64,
    )
    return payload, scope


def test_original_pair_layout_preserves_exact_six_criteria_and_recipe() -> None:
    payload, scope = pair_layout()
    require_pair_layout(payload, scope)


@pytest.mark.parametrize("change", ["recipe", "extra_edge", "criteria", "actor", "goal"])
def test_foreign_or_ambiguous_retained_strategy_pair_denies(change: str) -> None:
    payload, scope = pair_layout()
    if change == "recipe":
        payload = payload.model_copy(
            update={
                "verification": (
                    payload.verification[0].model_copy(update={"check_recipe": "report"}),
                )
            }
        )
    elif change == "extra_edge":
        edge = payload.verification[0].model_copy(update={"verifier_task_id": UUID(int=999)})
        payload = payload.model_copy(update={"verification": (*payload.verification, edge)})
    elif change == "criteria":
        item = payload.plan.items[0].model_copy(update={"acceptance": ("strategy.generic",)})
        payload = payload.model_copy(
            update={
                "plan": payload.plan.model_copy(update={"items": (item, payload.plan.items[1])})
            }
        )
    elif change == "actor":
        child = payload.children[0].model_copy(
            update={
                "binding": payload.children[0].binding.model_copy(
                    update={"actor_id": UUID(int=999)}
                )
            }
        )
        payload = payload.model_copy(update={"children": (child, payload.children[1])})
    else:
        payload = payload.model_copy(
            update={"goal": payload.goal.model_copy(update={"goal_id": UUID(int=999)})}
        )
    with pytest.raises(ValueError):
        require_pair_layout(payload, scope)

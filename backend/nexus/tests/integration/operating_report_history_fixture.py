"""Public replan keeps already registered work immutable while adding an output pair."""

from uuid import uuid4

from nexus.company.management.plans import PlanPayload, VerificationIntent


def new_output_pair(payload: PlanPayload) -> PlanPayload:
    additions, items = [], []
    for child, item in zip(payload.children[:2], payload.plan.items[:2], strict=True):
        bound = child.binding.model_copy(
            update={"task_id": uuid4(), "trace_id": uuid4(), "run_id": uuid4()}
        )
        additions.append(child.model_copy(update={"binding": bound}))
        items.append(
            item.model_copy(
                update={"task_id": bound.task_id, "trace_id": bound.trace_id, "depends_on": ()}
            )
        )
    edge = payload.verification[0]
    verification = VerificationIntent(
        company_id=payload.company_id,
        author_task_id=additions[0].binding.task_id,
        verifier_task_id=additions[1].binding.task_id,
        check_recipe=edge.check_recipe,
    )
    return PlanPayload.model_validate_json(
        payload.model_copy(
            update={
                "children": (*payload.children, *additions),
                "verification": (*payload.verification, verification),
                "plan": payload.plan.model_copy(
                    update={
                        "plan_id": uuid4(),
                        "revision": 1,
                        "items": (*payload.plan.items, *items),
                    }
                ),
            }
        ).model_dump_json(by_alias=True)
    )

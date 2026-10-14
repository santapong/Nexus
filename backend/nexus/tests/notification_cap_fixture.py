"""Add genuinely distinct public native report/check children; never reset the used child quota."""

from decimal import Decimal
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plans import PlanPayload, VerificationIntent
from nexus.company.management.revision_store import plan_reference
from nexus.tests.integration.test_company_directory import OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.metric_fixture import MetricScenario


async def distinct_report_case(
    factory: async_sessionmaker[AsyncSession], case: MetricScenario
) -> MetricScenario:
    author, verifier = case.payload.children[:2]
    new_author = author.model_copy(
        update={
            "binding": author.binding.model_copy(
                update={"task_id": uuid4(), "trace_id": uuid4(), "run_id": uuid4()}
            ),
            "allocation_usd": Decimal(".05"),
        }
    )
    new_verifier = verifier.model_copy(
        update={
            "binding": verifier.binding.model_copy(
                update={"task_id": uuid4(), "trace_id": uuid4(), "run_id": uuid4()}
            ),
            "allocation_usd": Decimal(".05"),
        }
    )
    new_items = tuple(
        item.model_copy(
            update={
                "task_id": child.binding.task_id,
                "trace_id": child.binding.trace_id,
                "budget_usd": Decimal(".05"),
            }
        )
        for item, child in zip(case.payload.plan.items[:2], (new_author, new_verifier), strict=True)
    )
    data = PlanPayload.model_validate_json(
        case.payload.model_copy(
            update={
                "plan": case.payload.plan.model_copy(
                    update={
                        "revision": case.payload.plan.revision + 1,
                        "items": (*case.payload.plan.items, *new_items),
                    }
                ),
                "children": (*case.payload.children, new_author, new_verifier),
                "verification": (
                    *case.payload.verification,
                    VerificationIntent(
                        company_id=case.payload.company_id,
                        author_task_id=new_author.binding.task_id,
                        verifier_task_id=new_verifier.binding.task_id,
                        check_recipe=case.payload.verification[0].check_recipe,
                    ),
                ),
            }
        ).model_dump_json()
    )
    plans = ManagementPlanStore(factory, case.store.catalog, source_freshness=case.store.freshness)
    proposed = await plans.propose(
        control(),
        identity(OWNER),
        data,
        expected_current_revision_id=case.request.plan.plan_revision_id,
    )
    approved = await plans.approve_and_register(
        control(),
        identity(OWNER),
        proposed.plan_revision_id,
        proposed.sha256,
        expected_current_revision_id=case.request.plan.plan_revision_id,
    )
    # Metric helper operates the first author/verifier pair; reordered selection is test-only.
    selected = data.model_copy(
        update={"children": (new_author, new_verifier, *case.payload.children)}
    )
    return MetricScenario(
        case.store,
        case.request.model_copy(
            update={"plan": plan_reference(approved), "task_ids": (new_author.binding.task_id,)}
        ),
        selected,
        case.publisher,
        case.producer,
        case.execution,
        case.effects,
        case.retriever,
    )

"""Fixed server slots map content without minting model-selected authority or roots."""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.lifecycle import PlanRevision
from nexus.company.management.planning_content import PlanningContent, PlanningTask
from nexus.company.management.planning_origin_contracts import PlanningOriginRef
from nexus.company.management.planning_proposal_bridge import (
    PlanningProposalTemplate,
    PlanningTaskSlot,
    map_content,
)
from nexus.execution.runtime_contracts import AttemptQuota
from nexus.tests.unit.test_company_management_plans import payload


def template() -> PlanningProposalTemplate:
    original = payload()
    child = original.children[0].model_copy(
        update={
            "quota": AttemptQuota(
                model_requests=1, tool_attempts=0, rework_rounds=0, plan_revisions=0
            )
        }
    )
    data = type(original).model_validate(
        original.model_dump()
        | {
            "children": (child,),
            "verification": (),
            "plan": original.plan.model_copy(update={"items": (original.plan.items[0],)}),
        }
    )
    base = PlanRevision(
        company_id=data.company_id,
        plan_id=data.plan.plan_id,
        plan_revision_id=UUID(int=80),
        revision=1,
        sha256=canonical_sha256(data),
        payload=data,
        proposed_by=UUID(int=103),
        recorded_at=datetime.now(UTC),
    )
    allocation = original.children[1].model_copy(update={"quota": child.quota})
    return PlanningProposalTemplate(
        base_plan=base,
        revision="mapping-v1",
        slots=(
            PlanningTaskSlot(
                key="draft",
                allocation=allocation,
                department="research",
                required_dependencies=(child.binding.task_id,),
            ),
        ),
    )


def content() -> PlanningContent:
    return PlanningContent(
        tasks=(
            PlanningTask(
                key="draft",
                title="Propose Nexus work",
                description="Describe the supported proposal.",
                acceptance=("Show source evidence",),
                depends_on=(),
                evidence_ids=(),
            ),
        ),
        questions=("Owner chooses implementation scope",),
    )


def origin(policy: PlanningProposalTemplate) -> PlanningOriginRef:
    base = policy.base_plan
    return PlanningOriginRef(
        company_id=base.company_id,
        goal=base.payload.goal,
        source_plan_id=base.plan_id,
        source_plan_revision_id=base.plan_revision_id,
        task_id=base.payload.children[0].binding.task_id,
        action_id=UUID(int=5),
        request_id=UUID(int=6),
        receipt_id=UUID(int=7),
        artifact_id=UUID(int=8),
        artifact_sha256="a" * 64,
        request_sha256="b" * 64,
        context_manifest_sha256="c" * 64,
        content_sha256=canonical_sha256(content()),
        mapping_revision=policy.revision,
        mapping_sha256=canonical_sha256(policy),
    )


def test_mapping_preserves_root_planner_slot_authority_and_fixed_safety_dependencies() -> None:
    policy = template()
    mapped = map_content(content(), origin(policy), policy)
    assert mapped.procedure == policy.base_plan.payload.procedure
    assert mapped.children[0] == policy.base_plan.payload.children[0]
    assert mapped.plan.items[0] == policy.base_plan.payload.plan.items[0]
    assert mapped.children[1] == policy.slots[0].allocation
    assert mapped.plan.items[1].depends_on == policy.slots[0].required_dependencies
    assert mapped.plan.revision == 2 and mapped.planning_origin == origin(policy)


@pytest.mark.parametrize("change", ["key", "content", "mapping", "goal"])
def test_unmatched_keys_or_spliced_provenance_cannot_be_mapped(change: str) -> None:
    policy, data = template(), content()
    ref = origin(policy)
    if change == "key":
        data = data.model_copy(
            update={"tasks": (data.tasks[0].model_copy(update={"key": "foreign"}),)}
        )
        ref = ref.model_copy(update={"content_sha256": canonical_sha256(data)})
    elif change == "content":
        data = data.model_copy(update={"questions": ()})
    elif change == "mapping":
        ref = ref.model_copy(update={"mapping_sha256": "f" * 64})
    else:
        ref = ref.model_copy(
            update={"goal": ref.goal.model_copy(update={"revision_id": UUID(int=99)})}
        )
    with pytest.raises(ValueError):
        map_content(data, ref, policy)


def test_default_plan_wire_omits_origin_and_oversized_formal_text_is_not_truncated() -> None:
    assert "planning_origin" not in payload().model_dump_json()
    policy, data = template(), content()
    data = data.model_copy(
        update={"tasks": (data.tasks[0].model_copy(update={"acceptance": ("x" * 501,)}),)}
    )
    ref = origin(policy).model_copy(update={"content_sha256": canonical_sha256(data)})
    with pytest.raises(ValueError):
        map_content(data, ref, policy)


def test_added_model_order_cannot_erase_fixed_edges_or_create_a_combined_cycle() -> None:
    policy = template()
    first = policy.slots[0]
    second = first.model_copy(
        update={
            "key": "review",
            "allocation": first.allocation.model_copy(
                update={
                    "binding": first.allocation.binding.model_copy(
                        update={
                            "task_id": UUID(int=300),
                            "trace_id": UUID(int=301),
                            "run_id": UUID(int=302),
                        }
                    ),
                    "allocation_usd": first.allocation.allocation_usd / 2,
                }
            ),
        }
    )
    first = first.model_copy(
        update={
            "allocation": first.allocation.model_copy(
                update={"allocation_usd": first.allocation.allocation_usd / 2}
            ),
            "required_dependencies": (
                *first.required_dependencies,
                second.allocation.binding.task_id,
            ),
        }
    )
    policy = type(policy).model_validate(policy.model_dump() | {"slots": (first, second)})
    data = content().model_copy(
        update={
            "tasks": (
                content().tasks[0],
                content().tasks[0].model_copy(update={"key": "review", "depends_on": ("draft",)}),
            )
        }
    )
    ref = origin(policy).model_copy(update={"content_sha256": canonical_sha256(data)})
    # The content DAG alone is acyclic; adding it cannot remove server draft->review.
    type(data).model_validate_json(data.model_dump_json())
    with pytest.raises(ValueError):
        map_content(data, ref, policy)


async def test_plan_store_checks_origin_twice_under_one_original_end_and_denies_late_commit(
    tmp_path: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from collections.abc import AsyncIterator
    from contextlib import asynccontextmanager
    from pathlib import Path
    from typing import cast
    from unittest.mock import AsyncMock

    import nexus.company.management.plan_store as module
    import nexus.company.management.planning_native_facts as clocks
    from nexus.company.access import CompanyControlScope, VerifiedIdentity
    from nexus.company.management.plan_catalog import PlanAdmissionCatalog
    from nexus.company.management.plan_store import ManagementPlanStore
    from nexus.harness.journal_models import CompanyControl
    from nexus.tests.unit.test_company_planning_consumer import planning_registry
    from nexus.tests.unit.test_planning_source_reader import recorded

    reader, native, saved = await recorded(cast(Path, tmp_path))
    source = reader._interpret(saved, native)
    data = map_content(source.content, source.origin, reader.template)
    record = PlanRevision(
        company_id=data.company_id,
        plan_id=data.plan.plan_id,
        plan_revision_id=UUID(int=800),
        revision=2,
        sha256=canonical_sha256(data),
        payload=data,
        proposed_by=UUID(int=103),
        recorded_at=datetime.now(UTC),
    )
    now = [1_000_000]
    monkeypatch.setattr(clocks, "clock_us", lambda: now[0])

    @asynccontextmanager
    async def transaction(
        *args: object, **kwargs: object
    ) -> AsyncIterator[tuple[object, CompanyControl, datetime]]:
        yield object(), CompanyControl(company_id=data.company_id), datetime.now(UTC)
        now[0] = 2_000_000

    monkeypatch.setattr(module, "management_owner_transaction", transaction)
    monkeypatch.setattr(module, "require_plan_not_cancelled", AsyncMock())
    monkeypatch.setattr(module, "validate_plan", AsyncMock())
    monkeypatch.setattr(module, "propose_locked", AsyncMock(return_value=record))
    monkeypatch.setattr(module, "db_clock", AsyncMock(return_value=datetime.now(UTC)))
    monkeypatch.setattr(module, "is_full_transition", lambda *args: False)
    check = AsyncMock()
    monkeypatch.setattr(reader, "revalidate_locked", check)
    store = ManagementPlanStore(
        reader.factory,
        PlanAdmissionCatalog(
            company_id=data.company_id,
            models=planning_registry("openai"),
            admitted_profiles=frozenset({"routine"}),
            check_recipes=frozenset(),
        ),
        planning_reader=reader,
    )
    scope = CompanyControlScope(
        company_id=data.company_id,
        principal_id=UUID(int=103),
        operation_id=UUID(int=400),
        trace_id=UUID(int=401),
    )
    with pytest.raises(TimeoutError):
        await store.propose(
            scope,
            VerifiedIdentity(principal_id=scope.principal_id, workspace_id=UUID(int=2)),
            data,
            expected_current_revision_id=reader.template.base_plan.plan_revision_id,
            end_us=2_000_000,
        )
    assert check.await_count == 2
    assert [row.kwargs["end_us"] for row in check.await_args_list] == [2_000_000, 2_000_000]

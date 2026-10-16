"""Supplied native-row checks exercise CAS predicates, without claiming SQL qualification."""

from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.context import AssembledContext
from nexus.company.brain.model_context_check import BrainModelContextCheck
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.goals import GoalRevisionRef
from nexus.company.management.governance_models import ManagementGoalHead, ManagementGoalRevision
from nexus.company.management.plan_models import ManagementPlanHead
from nexus.company.management.planning_content import PlanningBinding, planning_schema
from nexus.company.management.planning_intent import PlanningIntentCheck, prepare_planning_request
from nexus.core.llm.company_adapter_contracts import CompanyModelRequest, request_hash
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.journal_models import CompanyControl, JournalAction
from nexus.harness.model_authorizer_contracts import ModelInputRecipe, model_action_parameters
from nexus.tests.unit.test_company_brain_model_context_check import inputs
from nexus.tests.unit.test_company_model_authorizer import recipe
from nexus.tests.unit.test_company_provider_conformance import request


def prepared_inputs() -> tuple[
    CompanyModelRequest,
    AssembledContext,
    PlanningBinding,
    BrainReadScope,
    ModelInputRecipe,
    ExecutionLease,
]:
    scope, context, lease = inputs()
    goal = GoalRevisionRef(
        company_id=scope.company_id,
        goal_id=UUID(int=20),
        revision_id=UUID(int=21),
        version="goal-v1",
        sha256="a" * 64,
    )
    binding = PlanningBinding(
        goal=goal,
        plan_id=UUID(int=22),
        expected_plan_revision_id=None,
        context_manifest_sha256=canonical_sha256(context.manifest),
    )
    call = request(
        task_id=lease.task_id,
        trace_id=lease.trace_id,
        actor_id=lease.actor_id,
        attempt_id=UUID(int=5),
        input_text=context.input_text,
        system_text=context.system_text,
        data_classification=context.manifest.data_classification,
        output_schema=planning_schema(binding, manifest=context.manifest),
    )
    return call, context, binding, scope, recipe(), lease


def test_preparation_freezes_schema_context_recipe_scope_and_request_hash() -> None:
    call, context, binding, scope, selected, _ = prepared_inputs()
    prepared = prepare_planning_request(call, context, binding, scope=scope, input_recipe=selected)
    assert prepared.request.output_schema == planning_schema(binding, manifest=context.manifest)
    assert prepared.binding == binding


def test_new_planning_schema_retains_complete_original_manifest_for_durable_review() -> None:
    import json

    _, context, binding, _, _, _ = prepared_inputs()
    schema = planning_schema(binding, manifest=context.manifest)
    annotation = json.loads(json.loads(schema.document)["$comment"])
    assert annotation["version"] == "nexus.company.planning-binding.v2"
    assert annotation["context_manifest"] == context.manifest.model_dump(mode="json")


@pytest.mark.parametrize("field", ["goal", "cas"])
def test_changed_server_reference_cannot_reuse_the_approved_request(field: str) -> None:
    call, context, binding, scope, selected, _ = prepared_inputs()
    if field == "goal":
        changed = binding.model_copy(
            update={"goal": binding.goal.model_copy(update={"revision_id": UUID(int=99)})}
        )
    else:
        changed = binding.model_copy(update={"expected_plan_revision_id": UUID(int=99)})
    with pytest.raises(ValueError):
        prepare_planning_request(call, context, changed, scope=scope, input_recipe=selected)
    rebound = call.model_copy(
        update={"output_schema": planning_schema(changed, manifest=context.manifest)}
    )
    assert request_hash(rebound) != request_hash(call)
    assert model_action_parameters(rebound, selected) != model_action_parameters(call, selected)
    prepare_planning_request(rebound, context, changed, scope=scope, input_recipe=selected)


@pytest.mark.parametrize(
    "splice", ["schema", "text", "digest", "goal", "scope", "recipe", "profile"]
)
def test_splice_is_denied_before_any_approval_or_model_call(splice: str) -> None:
    call, context, binding, scope, selected, _ = prepared_inputs()
    if splice == "schema":
        call = call.model_copy(update={"output_schema": None})
    elif splice == "text":
        call = call.model_copy(update={"input_text": "different"})
    elif splice == "digest":
        binding = binding.model_copy(update={"context_manifest_sha256": "f" * 64})
    elif splice == "goal":
        binding = binding.model_copy(
            update={"goal": binding.goal.model_copy(update={"company_id": UUID(int=99)})}
        )
    elif splice == "scope":
        scope = scope.model_copy(update={"task_id": UUID(int=99)})
    elif splice == "recipe":
        selected = selected.model_copy(update={"revision": "different"})
    else:
        selected = selected.model_copy(update={"profile": "different"})
    with pytest.raises(ValueError):
        prepare_planning_request(call, context, binding, scope=scope, input_recipe=selected)


@pytest.mark.parametrize(
    "mismatch",
    [None, "inactive", "goal-version", "goal-hash", "goal-id", "head", "work-goal", "foreign-plan"],
)
async def test_same_transaction_goal_and_cas_follow_actual_context_check(
    mismatch: str | None,
) -> None:
    call, context, binding, scope, selected, _ = prepared_inputs()
    prepared = prepare_planning_request(call, context, binding, scope=scope, input_recipe=selected)
    check = AsyncMock(spec=BrainModelContextCheck)
    check.context = context
    gate = PlanningIntentCheck(cast(BrainModelContextCheck, check), prepared)
    head = ManagementGoalHead(
        company_id=scope.company_id,
        goal_id=binding.goal.goal_id,
        current_revision_id=binding.goal.revision_id,
        active=True,
    )
    revision = ManagementGoalRevision(
        company_id=scope.company_id,
        goal_id=binding.goal.goal_id,
        revision_id=binding.goal.revision_id,
        version="goal-v1",
        sha256="a" * 64,
    )
    plan: ManagementPlanHead | None = None
    work = ExecutionWork(company_id=scope.company_id, task_id=call.task_id)
    # Snapshot is an existing native projection; supplied delivery is isolated here.
    if mismatch == "inactive":
        head.active = False
    elif mismatch == "goal-version":
        revision.version = "other"
    elif mismatch == "goal-hash":
        revision.sha256 = "b" * 64
    elif mismatch == "goal-id":
        revision.goal_id = UUID(int=99)
    elif mismatch == "head":
        head.current_revision_id = UUID(int=99)
    elif mismatch == "foreign-plan":
        plan = ManagementPlanHead(
            company_id=scope.company_id,
            plan_id=binding.plan_id,
            goal_id=UUID(int=99),
            current_revision_id=UUID(int=23),
        )
    session = AsyncMock(spec=AsyncSession)
    session.in_transaction.return_value = True
    session.get.side_effect = [head, revision, plan]
    from unittest.mock import patch

    with patch("nexus.company.management.planning_intent.snapshot") as native:
        native.return_value.registration.work.goal_id = (
            UUID(int=99) if mismatch == "work-goal" else binding.goal.goal_id
        )
        if mismatch is None:
            await gate.validate(
                cast(AsyncSession, session),
                CompanyControl(company_id=scope.company_id),
                work,
                JournalAction(),
                datetime.now(UTC),
            )
        else:
            with pytest.raises(ValueError):
                await gate.validate(
                    cast(AsyncSession, session),
                    CompanyControl(company_id=scope.company_id),
                    work,
                    JournalAction(),
                    datetime.now(UTC),
                )
    check.validate.assert_awaited_once()

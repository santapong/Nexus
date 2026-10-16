"""Actual request/whole-input proof construction with supplied context, no registered DB proof."""

from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from nexus.builder.contained_query import clock_us
from nexus.execution.planning_preparation import prepare_work
from nexus.harness.journal_contracts import LedgerScope
from nexus.tests.unit.test_planning_services import services


async def test_foreign_actor_cannot_claim_or_prepare(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured = services(tmp_path)
    claim = AsyncMock()
    monkeypatch.setattr(configured.execution, "claim", claim)
    with pytest.raises(ValueError, match="actor"):
        await prepare_work(
            configured,
            LedgerScope(
                company_id=UUID(int=1),
                principal_id=UUID(int=999),
                task_id=UUID(int=6),
                trace_id=UUID(int=7),
            ),
            end_us=clock_us() + 10_000_000,
        )
    claim.assert_not_awaited()


async def test_real_producer_orders_claim_context_save_pending_then_released_owner_wait(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime
    from decimal import Decimal

    from nexus.company.access import VerifiedIdentity
    from nexus.company.brain.base import BrainReadScope
    from nexus.company.brain.context import AssembledContext, ContextLimits, ContextSelection
    from nexus.company.brain.context_render import render_context
    from nexus.company.contracts.actions import ActionProposal
    from nexus.company.contracts.work import WorkItem
    from nexus.company.management.planning_intent import PreparedPlanningRequest
    from nexus.company.management.planning_prepared_contracts import (
        PlanningPreparedRef,
        descriptor_for,
        descriptor_reference,
        encode_prepared,
    )
    from nexus.core.llm.company_pricing import CostQuote, quote_cost
    from nexus.execution import planning_preparation as module
    from nexus.execution.planning_context import PlanningState
    from nexus.execution.planning_services import WORKFLOW, PlanningOperation
    from nexus.execution.runtime_contracts import (
        AttemptQuota,
        ExecutionLease,
        ExecutionRegistration,
        ExecutionSnapshot,
    )
    from nexus.harness.canonical import action_hash
    from nexus.harness.journal_contracts import ActionRecord
    from nexus.harness.lifecycle import ActionState
    from nexus.harness.limits import LoopCounters
    from nexus.harness.model_authorizer_contracts import model_action_parameters
    from nexus.tests.unit.test_company_brain_context_render import head, material
    from nexus.tests.unit.test_company_planning_intent import prepared_inputs

    configured = services(tmp_path)
    _, old, binding, scope, _, lease = prepared_inputs()
    events: list[str] = []
    authority = old.manifest.authority.model_copy(
        update={
            "model_recipe": configured.recipe.recipe_id,
            "model_recipe_revision": configured.recipe.revision,
        }
    )
    item = material()
    registered = ExecutionRegistration(
        work=WorkItem(
            company_id=scope.company_id,
            task_id=lease.task_id,
            trace_id=lease.trace_id,
            goal_id=binding.goal.goal_id,
            department="management",
            title="Registered planning",
            acceptance=("Review evidence",),
            budget_usd=Decimal(1),
        ),
        run_id=lease.run_id,
        workflow_name=WORKFLOW,
        workflow_version="v1",
        model_profile="engineering",
        model_registry_version="registry-1",
        quota=AttemptQuota(model_requests=1, tool_attempts=0, rework_rounds=0, plan_revisions=0),
    )
    state = ExecutionSnapshot(
        company_id=scope.company_id,
        registration=registered,
        workspace_id=lease.workspace_id,
        actor_id=lease.actor_id,
        parent_task_id=UUID(int=200),
        state="running",
        counters=LoopCounters(),
        delegated=LoopCounters(),
        fence=lease.fence,
        worker_id=lease.worker_id,
        lease_principal_id=lease.actor_id,
        expires_at=lease.expires_at,
        segment_number=1,
        segment_id=lease.segment_id,
        waiting_action_id=None,
    )

    async def claim(*args: object, **kwargs: object) -> ExecutionLease:
        events.append("claim")
        return lease

    async def initial(*args: object) -> PlanningState:
        return PlanningState(
            state,
            binding.goal,
            binding.plan_id,
            binding.expected_plan_revision_id,
            "policy-1",
            datetime.now(UTC),
            clock_us(),
        )

    async def assemble(
        actual_scope: BrainReadScope, identity: VerifiedIdentity, selection: ContextSelection
    ) -> AssembledContext:
        events.append("assemble")
        return render_context(
            actual_scope,
            authority,
            ContextLimits(policy_version="context-v1"),
            (item,),
            (head(item),),
            question="Private complete goal DATA",
        )

    async def save(
        actual_lease: ExecutionLease,
        identity: VerifiedIdentity,
        prepared: PreparedPlanningRequest,
        *,
        end_us: int,
    ) -> PlanningPreparedRef:
        events.append("save")
        assert actual_lease is lease and prepared.input_estimate is not None
        assert prepared.input_estimate.whole_request is not None
        _, body = encode_prepared(prepared)
        return descriptor_reference(
            descriptor_for(
                prepared,
                body,
                run_id=lease.run_id,
                registration_sha256="a" * 64,
                owner_id=UUID(int=99),
            )
        )[0]

    async def pending(
        operation: PlanningOperation,
        prepared: PreparedPlanningRequest,
        reference: PlanningPreparedRef,
    ) -> tuple[ActionRecord, CostQuote]:
        events.append("pending")
        quote = quote_cost(
            configured.management.catalog.models.models[0].price,
            prepared.request.bounds,
            now=datetime.now(UTC),
        )
        proposal = ActionProposal(
            company_id=scope.company_id,
            action_id=prepared.request.action_id,
            task_id=lease.task_id,
            trace_id=lease.trace_id,
            actor_id=lease.actor_id,
            revision=1,
            tool="model.request.v1",
            tool_version="v1",
            resource="model:fixture-a",
            parameters=model_action_parameters(prepared.request, configured.recipe),
            preconditions=(reference.condition,),
            policy_version="policy-1",
            price_version="prices-1",
            estimated_cost_usd=quote.amount_usd,
        )
        return ActionRecord(
            company_id=scope.company_id,
            proposal=proposal,
            proposal_hash=action_hash(proposal),
            state=ActionState.AWAITING_APPROVAL,
            approval=None,
            consumed_at=None,
        ), quote

    async def wait(
        actual_lease: ExecutionLease, identity: VerifiedIdentity, action_id: UUID
    ) -> ExecutionSnapshot:
        events.append("owner-wait")
        return state.model_copy(
            update={
                "state": "awaiting_approval",
                "worker_id": None,
                "lease_principal_id": None,
                "expires_at": None,
                "fence": lease.fence + 1,
                "waiting_action_id": action_id,
            }
        )

    monkeypatch.setattr(module, "clock_now", AsyncMock(return_value=datetime.now(UTC)))
    monkeypatch.setattr(configured.execution, "claim", claim)
    monkeypatch.setattr(module, "_initial", initial)
    monkeypatch.setattr(configured.contexts, "assemble", assemble)
    monkeypatch.setattr(configured.prepared, "save_worker", save)
    monkeypatch.setattr(module, "_pending", pending)
    monkeypatch.setattr(configured.execution, "await_approval", wait)
    release = AsyncMock(side_effect=AssertionError("Owner wait already revoked its real lease"))
    monkeypatch.setattr(configured.execution, "release", release)
    result = await prepare_work(
        configured,
        LedgerScope(
            company_id=scope.company_id,
            principal_id=lease.actor_id,
            task_id=lease.task_id,
            trace_id=lease.trace_id,
        ),
        end_us=clock_us() + 10_000_000,
    )
    assert events == ["claim", "assemble", "save", "pending", "owner-wait"]
    assert result.work.worker_id is None and result.action.approval is None
    assert "Private complete goal DATA" not in result.model_dump_json()
    release.assert_not_awaited()

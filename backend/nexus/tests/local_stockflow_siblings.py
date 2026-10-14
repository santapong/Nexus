"""Prepare genuine remaining parent slices by public owner revision; no new engine process."""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.contracts.work import WorkItem
from nexus.company.management.lifecycle import PlanRevision
from nexus.company.management.owner_view_store import ManagementOwnerViews
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plans import (
    ChildAllocation,
    PlanPayload,
    RunBinding,
    VerificationIntent,
)
from nexus.execution.runtime_contracts import AttemptQuota
from nexus.execution.runtime_store import ExecutionStore
from nexus.harness.journal_contracts import LedgerScope
from nexus.tests.integration.test_company_directory import ACTOR, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.local_stockflow_packet import ROOT, write_private
from nexus.tests.management_plan_support import VERIFIER
from nexus.tests.stockflow_packet_contracts import PreparedState


def next_payload(old: PlanPayload) -> PlanPayload:
    bindings = tuple(
        RunBinding.model_validate_json(
            old.children[0]
            .binding.model_copy(
                update={
                    "actor_id": actor,
                    "task_id": uuid4(),
                    "trace_id": uuid4(),
                    "run_id": uuid4(),
                }
            )
            .model_dump_json()
        )
        for actor in (ACTOR, VERIFIER)
    )
    quota = AttemptQuota(model_requests=0, tool_attempts=1, rework_rounds=0, plan_revisions=0)
    children = tuple(
        ChildAllocation(
            company_id=old.company_id,
            binding=bound,
            charter=old.children[0].charter,
            allocation_usd=Decimal("0.10"),
            quota=quota,
        )
        for bound in bindings
    )
    work = tuple(
        WorkItem(
            company_id=old.company_id,
            task_id=bound.task_id,
            trace_id=bound.trace_id,
            goal_id=old.goal.goal_id,
            department="research",
            title="Nominated-source local toolchain qualification",
            acceptance=(
                "actual offline resolution and bounded command outcomes; no engineering acceptance",
            ),
            budget_usd=Decimal("0.10"),
        )
        for bound in bindings
    )
    revised = old.model_copy(
        update={
            "plan": old.plan.model_copy(
                update={"revision": old.plan.revision + 1, "items": (*old.plan.items, *work)}
            ),
            "children": (*old.children, *children),
            "verification": (
                *old.verification,
                VerificationIntent(
                    company_id=old.company_id,
                    author_task_id=bindings[0].task_id,
                    verifier_task_id=bindings[1].task_id,
                    check_recipe=old.verification[0].check_recipe,
                ),
            ),
        }
    )
    return PlanPayload.model_validate_json(revised.model_dump_json(by_alias=True))


async def partition(
    factory: async_sessionmaker[AsyncSession],
    state: PreparedState,
    receipt_path: Path = ROOT / "sibling-revision-receipt.json",
) -> PlanRevision:
    views = ManagementOwnerViews(factory)
    company = await views.company(control(), identity(OWNER))
    if len(company.plans) != 1:
        raise ValueError("Exact qualification procedure plan is ambiguous")
    before = await views.plan(control(), identity(OWNER), company.plans[0].reference.plan_id)
    if before.state != "approved" or not before.is_current_head:
        raise ValueError("Qualification plan lacks actual current owner approval")
    old = before.declaration
    execution = ExecutionStore(factory)
    parent_scope = LedgerScope(
        company_id=old.company_id,
        task_id=old.procedure.binding.task_id,
        trace_id=old.procedure.binding.trace_id,
        principal_id=OWNER,
    )
    root_before = await execution.get(parent_scope, identity(OWNER))
    old_before = tuple(
        [
            await execution.get(
                LedgerScope(
                    company_id=old.company_id,
                    task_id=child.binding.task_id,
                    trace_id=child.binding.trace_id,
                    principal_id=OWNER,
                ),
                identity(OWNER),
            )
            for child in old.children
        ]
    )
    payload = next_payload(old)
    plans = ManagementPlanStore(factory, state.catalog)
    proposed = await plans.propose(
        control(),
        identity(OWNER),
        payload,
        expected_current_revision_id=before.reference.plan_revision_id,
    )
    approved = await plans.approve_and_register(
        control(),
        identity(OWNER),
        proposed.plan_revision_id,
        proposed.sha256,
        expected_current_revision_id=before.reference.plan_revision_id,
    )
    root_after = await execution.get(parent_scope, identity(OWNER))
    old_after = tuple(
        [
            await execution.get(
                LedgerScope(
                    company_id=old.company_id,
                    task_id=child.binding.task_id,
                    trace_id=child.binding.trace_id,
                    principal_id=OWNER,
                ),
                identity(OWNER),
            )
            for child in old.children
        ]
    )
    assert old_before == old_after and approved.payload.procedure == old.procedure
    assert root_before.registration == root_after.registration
    assert root_after.counters.plan_revisions == root_before.counters.plan_revisions + 1
    assert root_after.delegated.tool_attempts == root_before.delegated.tool_attempts + 2
    receipt = {
        "scope": "same procedure/goal owner revision; permanent partition, no commands",
        "before_plan": before.model_dump(mode="json"),
        "approved": approved.model_dump(mode="json"),
        "parent_before": root_before.model_dump(mode="json"),
        "parent_after": root_after.model_dump(mode="json"),
        "old_child_before": [row.model_dump(mode="json") for row in old_before],
        "old_child_after": [row.model_dump(mode="json") for row in old_after],
        "new_children": [row.model_dump(mode="json") for row in payload.children[-2:]],
        "project_processes": 0,
        "counter_resets": 0,
        "new_parent": False,
        "new_goal": False,
    }
    await asyncio.to_thread(
        write_private,
        receipt_path,
        json.dumps(receipt, indent=2).encode(),
    )
    return approved

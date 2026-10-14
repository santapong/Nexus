"""Permanent signed-owner intent is distinct from activity and preserves already-issued facts."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.contracts.results import ActionReceipt
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management.cancellation_contracts import CancellationCommand
from nexus.company.management.cancellation_models import WorkCancellation
from nexus.company.management.cancellation_store import WorkCancellationStore
from nexus.company.management.cancellation_support import cancellation_for_work
from nexus.company.management.lifecycle import PlanRevision
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plans import PlanPayload
from nexus.execution.effect_store import EffectStore
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt
from nexus.execution.runtime_store import ExecutionStore
from nexus.harness.canonical import action_hash
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import CostHold
from nexus.settings import settings
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.management_cancellation_support import cancellation_factory as cancellation_factory
from nexus.tests.management_plan_support import authorized_action, configured_plan


async def _approved(
    factory: async_sessionmaker[AsyncSession], root: Path
) -> tuple[ManagementPlanStore, PlanPayload, PlanRevision]:
    plans, payload = await configured_plan(factory, root)
    proposed = await plans.propose(
        control(), identity(OWNER), payload, expected_current_revision_id=None
    )
    await plans.approve_and_register(
        control(),
        identity(OWNER),
        proposed.plan_revision_id,
        proposed.sha256,
        expected_current_revision_id=proposed.plan_revision_id,
    )
    return plans, payload, proposed


async def test_exact_cancel_replay_distinct_intent_and_ancestry_are_not_inactivity(
    cancellation_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    _, payload, _ = await _approved(cancellation_factory, tmp_path)
    store = WorkCancellationStore(cancellation_factory)
    bound = payload.children[0].binding
    command = CancellationCommand(
        company_id=COMPANY, target=bound, reason="Owner stops this exact research task"
    )
    scope = control().model_copy(update={"operation_id": uuid4()})
    first = await store.cancel(scope, identity(OWNER), command)
    assert await store.cancel(scope, identity(OWNER), command) == first
    later_scope = scope.model_copy(update={"operation_id": uuid4()})
    later = await store.cancel(later_scope, identity(OWNER), command)
    assert later.cancellation_id != first.cancellation_id and later.target == first.target
    async with cancellation_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        result = await cancellation_for_work(session, COMPANY, bound.task_id)
        sibling = await cancellation_for_work(session, COMPANY, payload.children[1].binding.task_id)
        assert result is not None and not result.inherited and result.cancellation == first
        assert sibling is None
        assert await session.scalar(select(func.count()).select_from(WorkCancellation)) == 2
        assert await session.scalar(select(func.count()).select_from(ExecutionAttempt)) == 0
    parent = await store.cancel(
        scope.model_copy(update={"operation_id": uuid4()}),
        identity(OWNER),
        command.model_copy(update={"target": payload.procedure.binding}),
    )
    async with cancellation_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        direct = await cancellation_for_work(session, COMPANY, bound.task_id)
        sibling = await cancellation_for_work(session, COMPANY, payload.children[1].binding.task_id)
        assert direct is not None and direct.cancellation == first and not direct.inherited
        assert sibling is not None and sibling.inherited and sibling.cancellation == parent


@pytest.mark.parametrize(
    "failure",
    [
        "owner",
        "workspace",
        "task",
        "trace",
        "run",
        "actor",
        "profile",
        "replay_reason",
        "replay_audit",
    ],
)
async def test_wrong_owner_or_exact_native_target_cannot_cancel_or_rebind_operation(
    cancellation_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    failure: str,
) -> None:
    _, payload, _ = await _approved(cancellation_factory, tmp_path)
    store = WorkCancellationStore(cancellation_factory)
    scope = control().model_copy(update={"operation_id": uuid4()})
    bound = payload.children[0].binding
    command = CancellationCommand(company_id=COMPANY, target=bound, reason="Exact cancellation")
    if failure.startswith("replay"):
        await store.cancel(scope, identity(OWNER), command)
        if failure == "replay_reason":
            command = command.model_copy(update={"reason": "Different intent"})
        else:
            scope = scope.model_copy(update={"trace_id": uuid4()})
    elif failure not in {"owner", "workspace"}:
        field = {
            "task": "task_id",
            "trace": "trace_id",
            "run": "run_id",
            "actor": "actor_id",
            "profile": "model_profile",
        }[failure]
        command = command.model_copy(
            update={
                "target": bound.model_copy(
                    update={field: "unregistered-profile" if failure == "profile" else uuid4()}
                )
            }
        )
    with pytest.raises(ValueError):
        await store.cancel(
            control(ACTOR).model_copy(update={"operation_id": scope.operation_id})
            if failure == "owner"
            else scope,
            identity(ACTOR)
            if failure == "owner"
            else identity(OWNER).model_copy(update={"workspace_id": uuid4()})
            if failure == "workspace"
            else identity(OWNER),
            command,
        )


async def test_procedure_cancel_stops_every_descendant_and_cannot_be_reactivated_or_replanned(
    cancellation_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    plans, payload, _ = await _approved(cancellation_factory, tmp_path)
    parent = payload.procedure.binding
    record = await WorkCancellationStore(cancellation_factory).cancel(
        control().model_copy(update={"operation_id": uuid4()}),
        identity(OWNER),
        CancellationCommand(
            company_id=COMPANY, target=parent, reason="Stop the goal procedure permanently"
        ),
    )
    directory = PersistentCompanyDirectory(cancellation_factory)
    await directory.set_work_active(control(), task_id=parent.task_id, active=False)
    await directory.set_work_active(control(), task_id=parent.task_id, active=True)
    for child in payload.children:
        await directory.set_work_active(control(), task_id=child.binding.task_id, active=True)
        async with cancellation_factory() as session, session.begin():
            await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
            inherited = await cancellation_for_work(session, COMPANY, child.binding.task_id)
            assert (
                inherited is not None and inherited.inherited and inherited.cancellation == record
            )
        scope = LedgerScope(
            company_id=COMPANY,
            principal_id=child.binding.actor_id,
            task_id=child.binding.task_id,
            trace_id=child.binding.trace_id,
        )
        with pytest.raises(ValueError):
            await ExecutionStore(cancellation_factory, management_catalog=plans.catalog).claim(
                scope, identity(child.binding.actor_id), uuid4()
            )
    newer = payload.model_copy(
        update={"plan": payload.plan.model_copy(update={"plan_id": uuid4()})}
    )
    with pytest.raises(ValueError):
        await plans.propose(control(), identity(OWNER), newer, expected_current_revision_id=None)


async def test_cancel_preserves_issued_unknown_billing_and_allows_receipt_without_new_effect(
    cancellation_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    plans, payload, _ = await _approved(cancellation_factory, tmp_path)
    bound = payload.children[0].binding
    scope = LedgerScope(
        company_id=COMPANY,
        principal_id=bound.actor_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
    )
    execution = ExecutionStore(cancellation_factory, management_catalog=plans.catalog)
    effects = EffectStore(cancellation_factory, management_catalog=plans.catalog)
    lease = await execution.claim(scope, identity(bound.actor_id), uuid4())
    action = await authorized_action(cancellation_factory, bound)
    await effects.begin(lease, identity(bound.actor_id), action.action_id)
    await WorkCancellationStore(cancellation_factory).cancel(
        control().model_copy(update={"operation_id": uuid4()}),
        identity(OWNER),
        CancellationCommand(
            company_id=COMPANY, target=bound, reason="Stop after issued intent, retain facts"
        ),
    )
    receipt = ActionReceipt(
        company_id=COMPANY,
        receipt_id=uuid4(),
        action_id=action.action_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        proposal_hash=action_hash(action),
        outcome="succeeded",
        recorded_at=datetime.now(UTC),
    )
    await effects.record_receipt(lease, identity(bound.actor_id), receipt, actual_usd=None)
    assert not (
        await effects.begin(lease, identity(bound.actor_id), action.action_id)
    ).permit_external_call
    second = await authorized_action(cancellation_factory, bound)
    with pytest.raises(ValueError):
        await effects.begin(lease, identity(bound.actor_id), second.action_id)
    current = await execution.get(scope, identity(bound.actor_id))
    assert current.counters.tool_attempts == 1
    async with cancellation_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        hold = await session.get(CostHold, action.action_id)
        saved = await session.get(EffectIntent, (COMPANY, action.action_id))
        assert hold is not None and hold.state == "unknown" and hold.amount_usd == Decimal("0.03")
        assert saved is not None and saved.receipt_json == receipt.model_dump_json()


async def test_inactive_work_without_owner_cancel_has_no_invented_cancellation(
    cancellation_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    _, payload, _ = await _approved(cancellation_factory, tmp_path)
    bound = payload.children[0].binding
    await PersistentCompanyDirectory(cancellation_factory).set_work_active(
        control(), task_id=bound.task_id, active=False
    )
    async with cancellation_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await cancellation_for_work(session, COMPANY, bound.task_id) is None


async def test_separate_process_cannot_claim_reactivated_cancelled_descendant(
    cancellation_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    _, payload, _ = await _approved(cancellation_factory, tmp_path)
    bound = payload.children[0].binding
    await WorkCancellationStore(cancellation_factory).cancel(
        control().model_copy(update={"operation_id": uuid4()}),
        identity(OWNER),
        CancellationCommand(
            company_id=COMPANY,
            target=payload.procedure.binding,
            reason="Stop persists across worker process",
        ),
    )
    await PersistentCompanyDirectory(cancellation_factory).set_work_active(
        control(), task_id=bound.task_id, active=True
    )
    scope = LedgerScope(
        company_id=COMPANY,
        principal_id=bound.actor_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
    )
    url = (
        make_url(settings.company_test_database_url)
        .set(username="nexus_company_app")
        .render_as_string(hide_password=False)
    )
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "nexus.tests.management_cancellation_process",
        url,
        scope.model_dump_json(),
        identity(bound.actor_id).model_dump_json(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=15)
    except TimeoutError:
        process.kill()
        await process.communicate()
        raise
    assert process.returncode == 0, stderr.decode()
    # Application startup may log before the child's single explicit outcome.
    assert json.loads(stdout.splitlines()[-1]) == {"outcome": "durable_cancelled", "permit": False}

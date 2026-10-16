"""True actor preparation before owner wait; protected data cannot issue a model call."""

from __future__ import annotations

import asyncio
from typing import Literal
from uuid import uuid4

from sqlalchemy import select

from nexus.builder.contained_query import clock_us
from nexus.company.brain.base import BrainReadScope, ValueContract
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.coding_content import CodingBinding
from nexus.company.management.coding_intent import (
    PreparedCodingRequest,
)
from nexus.company.management.coding_prepared_contracts import CodingPreparedRef
from nexus.core.llm.company_pricing import CostQuote
from nexus.execution.coding_context import (
    CodingState,
    brain_scope,
    prepare_content,
    quote_locked,
    route_prepared,
    state_locked,
)
from nexus.execution.coding_operation import CodingOperation, CodingOperationRead, clock_now
from nexus.execution.coding_services import LEASE_SECONDS, CodingServices
from nexus.execution.runtime_contracts import ExecutionSnapshot
from nexus.execution.runtime_support import (
    db_now,
    execution_row,
    require_lease,
    runtime_transaction,
)
from nexus.harness.journal_contracts import ActionRecord, LedgerScope
from nexus.harness.journal_models import JournalAction
from nexus.harness.journal_submission import submit_pending_locked
from nexus.harness.model_authorizer_contracts import model_action_parameters


class PreparedCodingAction(ValueContract):
    """Committed descriptions; no prompt, approval, hold, permit or company completion."""

    action: ActionRecord
    reference: CodingPreparedRef
    work: ExecutionSnapshot
    quote: CostQuote
    company_completed: Literal[False] = False


async def _initial(
    operation: CodingOperation,
    scope: LedgerScope,
    brain: BrainReadScope,
) -> CodingState:
    credential = operation.credential
    assert credential is not None and operation.lease is not None
    async with runtime_transaction(operation.services.factory, scope, credential.identity) as (
        session,
        control,
        _,
    ):
        state = await state_locked(operation, session, control, brain, lease=operation.lease)
        if (
            await session.scalar(
                select(JournalAction.id)
                .where(
                    JournalAction.company_id == scope.company_id,
                    JournalAction.task_id == scope.task_id,
                )
                .limit(1)
            )
            is not None
        ):
            raise ValueError("Existing coding action requires its original review/history path")
        operation.require_admission()
    operation.require_current()
    return state


async def _pending(
    operation: CodingOperation,
    prepared: PreparedCodingRequest,
    reference: CodingPreparedRef,
) -> tuple[ActionRecord, CostQuote]:
    # Cohesion exception: save-to-pending current source/native/quote checks stay together.
    services, lease, credential = operation.services, operation.lease, operation.credential
    assert lease is not None and credential is not None
    scope = LedgerScope(
        company_id=lease.company_id,
        principal_id=lease.actor_id,
        task_id=lease.task_id,
        trace_id=lease.trace_id,
    )
    async with runtime_transaction(services.factory, scope, credential.identity) as (
        session,
        control,
        _,
    ):
        state = await state_locked(operation, session, control, prepared.scope, lease=lease)
        if (state.goal, state.plan_id, state.plan) != (
            prepared.binding.goal,
            prepared.binding.plan.plan_id,
            prepared.binding.plan,
        ):
            raise ValueError("Coding goal or head changed before pending publication")
        work = await execution_row(session, scope)
        resources = await services.contexts.revalidate_context(
            session,
            control,
            prepared.scope,
            credential.identity,
            prepared.context.manifest,
            await db_now(session),
        )
        selected = await quote_locked(
            services, session, control, work, prepared, await db_now(session)
        )
        proposal = ActionProposal(
            company_id=lease.company_id,
            action_id=prepared.request.action_id,
            task_id=lease.task_id,
            trace_id=lease.trace_id,
            actor_id=lease.actor_id,
            revision=1,
            tool="model.request.v1",
            tool_version="v1",
            resource=f"model:{services.registry_id}",
            parameters=model_action_parameters(prepared.request, services.recipe),
            preconditions=(*resources, reference.condition),
            policy_version=control.policy_version,
            price_version=control.price_version,
            estimated_cost_usd=selected.quote.amount_usd,
        )
        operation.require_admission()
        record = await submit_pending_locked(session, control, proposal, scope)
        await services.contexts.revalidate_context(
            session,
            control,
            prepared.scope,
            credential.identity,
            prepared.context.manifest,
            await db_now(session),
        )
        final = await state_locked(operation, session, control, prepared.scope, lease=lease)
        if (final.goal, final.plan_id, final.plan) != (state.goal, state.plan_id, state.plan):
            raise ValueError("Coding current goal/head changed before flush")
        anchor = clock_us()
        now = await db_now(session)
        credential.require_time(now)
        require_lease(work, lease, now, execute=True)
        operation.shorten(
            now,
            anchor,
            (
                lease.expires_at,
                credential.expires_at,
                *(
                    value.expires_at
                    for value in prepared.context.manifest.contributors
                    if value.expires_at is not None
                ),
                *(
                    value.fresh_until
                    for value in prepared.context.manifest.source_heads
                    if value.fresh_until is not None
                ),
            ),
        )
        if (
            route_prepared(services, prepared, work, control, selected.quote.amount_usd, now).quote
            != selected.quote
        ):
            raise ValueError("Coding quote expired before pending commit")
        operation.require_admission()
    operation.require_current()
    return record, selected.quote


async def prepare_read(
    services: CodingServices,
    scope: LedgerScope,
    *,
    end_us: int,
) -> CodingOperationRead[PreparedCodingAction]:
    """Actual actor claim, protected save, pending action and released owner wait.

    Cohesion exception: this bounded orchestration retains each actual task and first failure.
    """
    operation = CodingOperation(services, "prepare:" + str(uuid4()), end_us)
    result: PreparedCodingAction | None = None
    try:
        credential = await operation.call(services.identities.current())
        operation.credential = credential
        services.require_actor_scope(scope, credential)
        if scope.principal_id != credential.identity.principal_id:
            raise ValueError("Coding preparation requires its actual actor")
        now = await operation.call(clock_now(services))
        credential.require_time(now)
        ttl = min(
            LEASE_SECONDS,
            int((credential.expires_at - now).total_seconds()) - 1,
            (operation.end - clock_us()) // 1_000_000 - 1,
        )
        if ttl < 1:
            raise ValueError("Original coding witness/window cannot cover a lease")
        operation.require_admission()
        # Native claim precedes assembly/save; no pending action/hold exists yet.
        operation.lease_task = asyncio.create_task(
            services.execution.claim(
                scope, credential.identity, services.worker_id, ttl_seconds=ttl
            )
        )
        lease = await operation.call(operation.lease_task)
        operation.lease = lease
        brain = brain_scope(lease, uuid4())
        state = await operation.call(_initial(operation, scope, brain))
        context = await operation.call(
            services.contexts.assemble(brain, credential.identity, services.selection)
        )
        binding = CodingBinding(
            goal=state.goal,
            plan=state.plan,
            task_id=lease.task_id,
            trace_id=lease.trace_id,
            run_id=lease.run_id,
            actor_id=lease.actor_id,
            workspace_id=lease.workspace_id,
            source=services.repository_selection.source,
            source_files=tuple(row.file for row in services.code_sources),
            allowed_write_paths=services.repository_selection.allowed_write_paths,
            context_manifest_sha256=canonical_sha256(context.manifest),
        )
        prepared = prepare_content(services, lease, brain, context, binding)
        reference = await operation.call(
            operation.prepared.save_worker(lease, credential, prepared, end_us=operation.end)
        )
        record, quote = await operation.call(_pending(operation, prepared, reference))
        operation.waiting_task = asyncio.create_task(
            services.execution.await_approval(lease, credential.identity, record.proposal.action_id)
        )
        waiting = await operation.call(operation.waiting_task)
        if (
            waiting.state != "awaiting_approval"
            or waiting.waiting_action_id != record.proposal.action_id
            or waiting.worker_id is not None
        ):
            raise ValueError("Coding did not release into the exact owner wait")
        operation.released = True
        result = PreparedCodingAction(action=record, reference=reference, work=waiting, quote=quote)
        result.model_dump_json(by_alias=True)
        operation.require_current()
    except BaseException as first:
        operation.first = first
    try:
        await operation.retire()
    except BaseException as secondary:
        operation.first = operation.first or secondary
    operation.finish()
    if operation.first is not None:
        raise operation.first
    assert result is not None
    operation.require_current()
    return CodingOperationRead(result, operation.end)


async def prepare_work(
    services: CodingServices, scope: LedgerScope, *, end_us: int
) -> PreparedCodingAction:
    """Compatible direct caller value; owner HTTP uses prepare_read to retain its full cutoff."""
    return (await prepare_read(services, scope, end_us=end_us)).value

"""Exact dispatch reads and original-budget ownership for one qualification operation."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from nexus.builder.contained_query import clock_us
from nexus.company.access import VerifiedIdentity
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.core.llm.company_adapter_contracts import CompanyModelRequest
from nexus.core.llm.qualification_contracts import (
    PROFILE,
    VERSION,
    WORKFLOW,
    QualificationRecipe,
    qualification_request,
    recipe_hash,
    target_set_hash,
)
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.effect_support import effect_record
from nexus.execution.qualification_worker_services import (
    ACQUISITION_SECONDS,
    CLIENT_SECONDS,
    ENTRY_SECONDS,
    LEASE_SECONDS,
    RELEASE_SECONDS,
    QualificationWorkerServices,
)
from nexus.execution.runtime_contracts import AttemptQuota, EffectRecord, ExecutionLease
from nexus.execution.runtime_models import EffectIntent
from nexus.execution.runtime_recovery import dispatched_binding
from nexus.execution.runtime_support import db_now, execution_row, runtime_transaction, snapshot
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.qualification_client import QualificationClient
from nexus.harness.qualification_evidence import current


class QualificationOperation:
    """Caller-local owner of real tasks and any acquired lease, including failed preparation."""

    def __init__(self, services: QualificationWorkerServices) -> None:
        self.services = services
        self.started = clock_us()
        self.end = self.started + ENTRY_SECONDS * 1_000_000
        self.acquire_end = self.started + ACQUISITION_SECONDS * 1_000_000
        self.owners: list[asyncio.Task[object]] = []
        self.lease_task: asyncio.Task[ExecutionLease] | None = None
        self.lease: ExecutionLease | None = None
        self.identity: VerifiedIdentity | None = None
        self.client: QualificationClient | None = None
        self.first: BaseException | None = None
        self.released = False
        self.running = True

    def require_current(self) -> None:
        current(self.end)
        self.services.require_composition()

    async def call[T](self, value: Awaitable[T], *, end_us: int | None = None) -> T:
        """Shield the actual leaf; expiry/cancellation never destroys its settlement handle."""
        limit = min(self.end, end_us if end_us is not None else self.end)
        try:
            current(limit)
            self.services.require_composition()
        except BaseException:
            if inspect.iscoroutine(value):
                value.close()
            elif isinstance(value, asyncio.Task):
                self.owners.append(cast(asyncio.Task[object], value))
            raise
        task = asyncio.ensure_future(value)
        self.owners.append(cast(asyncio.Task[object], task))
        task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        async with asyncio.timeout(max(0, limit - clock_us()) / 1_000_000):
            result = await asyncio.shield(task)
        current(limit)
        self.services.require_composition()
        return result

    def pending_owners(self) -> tuple[asyncio.Task[object], ...]:
        return tuple(
            dict.fromkeys(
                (
                    *(task for task in self.owners if not task.done() or task.cancelled()),
                    *(self.client.pending_owners() if self.client is not None else ()),
                )
            )
        )

    async def settle(self) -> None:
        """Wait under the original end; preserve first cancellation and all original owners."""
        while self.pending_owners() and clock_us() < self.end:
            pending = self.pending_owners()
            if any(task.cancelled() for task in pending):
                return  # Cancelled wrappers cannot prove underlying resource settlement.
            try:
                await asyncio.wait(pending, timeout=max(0, self.end - clock_us()) / 1_000_000)
            except asyncio.CancelledError as error:
                self.first = self.first or error
        # Ownership adoption is permitted even when ordinary result adoption expired.
        if (
            self.lease_task is not None
            and self.lease_task.done()
            and not self.lease_task.cancelled()
            and self.lease_task.exception() is None
        ):
            self.lease = self.lease_task.result()


@dataclass(frozen=True, slots=True)
class QualificationContext:
    command: SegmentCommand
    scope: LedgerScope
    credential: AuthenticatedWorkerIdentity
    recipe: QualificationRecipe
    request: CompanyModelRequest
    proposal_hash: str
    issued: EffectRecord | None


async def read_context(
    operation: QualificationOperation, command: SegmentCommand, *, workflow_id: str
) -> QualificationContext:
    """Read actual owner/native family before considering fresh keys or issued recovery."""
    if workflow_id != command.workflow_id:
        raise ValueError("Qualification workflow differs from permanent dispatch")
    operation.require_current()
    services = operation.services
    credential = await operation.call(services.identities.current())
    if not isinstance(credential, AuthenticatedWorkerIdentity):
        raise ValueError("Qualification authenticated worker witness unavailable")
    identity = credential.identity
    if (identity.principal_id, identity.workspace_id) != (command.actor_id, command.workspace_id):
        raise ValueError("Qualification signed identity differs from dispatched actor")
    operation.identity = identity
    scope = LedgerScope(
        company_id=command.company_id,
        principal_id=identity.principal_id,
        task_id=command.task_id,
        trace_id=command.trace_id,
    )
    record = await operation.call(
        CompanyJournal(services.factory).get_action(scope, command.action_id)
    )
    recipe = services.preparation.recipe_for_action(command, record)
    from uuid import uuid5

    request = qualification_request(
        recipe,
        scope,
        action_id=command.action_id,
        request_id=uuid5(command.task_id, f"qualification-request:v1:{recipe_hash(recipe)}"),
    )
    value = await operation.call(
        _registered(operation, command, scope, credential, recipe, record.proposal_hash)
    )
    operation.require_current()
    return QualificationContext(
        command, scope, credential, recipe, request, record.proposal_hash, value
    )


async def _registered(
    operation: QualificationOperation,
    command: SegmentCommand,
    scope: LedgerScope,
    credential: AuthenticatedWorkerIdentity,
    recipe: QualificationRecipe,
    proposal_hash: str,
) -> EffectRecord | None:
    services, identity = operation.services, credential.identity
    async with runtime_transaction(
        services.factory, scope, identity, allow_paused=True, allow_inactive=True, owner_read=True
    ) as (session, control, _):
        work = await execution_row(session, scope)
        actual = await dispatched_binding(session, work, scope, command.segment_id)
        frozen = snapshot(work).registration
        if (
            actual != command
            or control.owner_id != identity.principal_id
            or (
                frozen.workflow_name,
                frozen.workflow_version,
                frozen.model_profile,
                frozen.model_registry_version,
                frozen.work.goal_id,
                frozen.work.acceptance,
            )
            != (
                WORKFLOW,
                VERSION,
                PROFILE,
                recipe.registry_revision,
                recipe.goal.goal_id,
                (
                    recipe.purpose,
                    "target-set:"
                    + target_set_hash(
                        recipe.registry_revision, recipe.qualification_target_sha256s
                    ),
                ),
            )
            or frozen.quota
            != AttemptQuota(model_requests=12, tool_attempts=0, rework_rounds=0, plan_revisions=0)
        ):
            raise ValueError("Qualification registered work differs from fixed server recipe")
        issued = await session.get(EffectIntent, (command.company_id, command.action_id))
        value = effect_record(issued) if issued is not None else None
        if value is not None and (
            value.task_id,
            value.trace_id,
            value.run_id,
            value.proposal_hash,
            value.attempt_kind,
        ) != (
            command.task_id,
            command.trace_id,
            command.run_id,
            proposal_hash,
            "model_requests",
        ):
            raise ValueError("Qualification native issuance differs from permanent action")
        credential.require_time(await db_now(session))
    operation.require_current()
    return value


async def clock_now(services: QualificationWorkerServices) -> datetime:
    """One owned actual database-clock read; never substitute a caller wall clock."""
    async with services.factory() as session:
        return await db_now(session)


async def acquire_context(operation: QualificationOperation, context: QualificationContext) -> int:
    """Recover only the same dispatch, never refresh credentials or advance a new action."""
    services = operation.services
    while True:
        current(operation.acquire_end)
        operation.lease_task = asyncio.create_task(
            services.execution.recover_dispatched(
                context.scope,
                context.credential.identity,
                services.worker_id,
                context.command.segment_id,
                ttl_seconds=LEASE_SECONDS,
            )
        )
        try:
            operation.lease = await operation.call(
                operation.lease_task, end_us=operation.acquire_end
            )
            break
        except asyncio.CancelledError:
            raise
        except Exception:
            from nexus.execution.runtime_contracts import ExecutionDeniedError

            if not operation.lease_task.done() or operation.lease_task.cancelled():
                raise
            if operation.lease_task.exception() is None:
                raise
            if not isinstance(operation.lease_task.exception(), ExecutionDeniedError):
                raise
            observed = await operation.call(
                services.execution.get(context.scope, context.credential.identity)
            )
            if observed.worker_id is None or observed.segment_id != context.command.segment_id:
                raise
            now = await operation.call(clock_now(services), end_us=operation.acquire_end)
            context.credential.require_time(now)
            if observed.expires_at is None or observed.expires_at <= now:
                raise
            await operation.call(asyncio.sleep(0.1), end_us=operation.acquire_end)
    # Anchor elapsed-time bounds before the DB clock await, conservatively.
    before = clock_us()
    now = await operation.call(clock_now(services))
    context.credential.require_time(now)
    assert operation.lease is not None
    remaining = min(
        (operation.lease.expires_at - now).total_seconds(),
        (context.credential.expires_at - now).total_seconds(),
        CLIENT_SECONDS,
    )
    client_end = min(
        operation.end - RELEASE_SECONDS * 1_000_000, before + int(remaining * 1_000_000)
    )
    current(client_end)
    operation.require_current()
    return client_end


async def refresh_issued(
    operation: QualificationOperation,
    context: QualificationContext,
) -> EffectRecord | None:
    """A previous exact worker may finish while acquisition waits; never then resolve SDK keys."""
    from nexus.execution.runtime_support import require_lease

    assert operation.lease is not None
    async with runtime_transaction(
        operation.services.factory,
        context.scope,
        context.credential.identity,
        allow_paused=True,
        allow_inactive=True,
    ) as (session, _, _):
        work = await execution_row(session, context.scope)
        require_lease(work, operation.lease, await db_now(session))
        row = await session.get(
            EffectIntent, (context.command.company_id, context.command.action_id)
        )
        value = effect_record(row) if row is not None else None
        if value is not None and (
            value.task_id,
            value.trace_id,
            value.run_id,
            value.action_id,
            value.attempt_kind,
            value.proposal_hash,
        ) != (
            context.command.task_id,
            context.command.trace_id,
            context.command.run_id,
            context.command.action_id,
            "model_requests",
            context.proposal_hash,
        ):
            raise ValueError("Qualification acquired issuance differs from actual dispatch")
        context.credential.require_time(await db_now(session))
    operation.require_current()
    return value


async def revalidate_history(
    operation: QualificationOperation, context: QualificationContext
) -> None:
    """Current owner/native READ after protected I/O, without current effect reauthorization."""
    actual = await _registered(
        operation,
        context.command,
        context.scope,
        context.credential,
        context.recipe,
        context.proposal_hash,
    )
    if actual is None or actual != context.issued:
        raise ValueError("Qualification native history changed during protected read")

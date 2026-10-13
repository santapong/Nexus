"""Immutable execution initialization and permanent parent-quota partitioning."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.directory_models import RegisteredWork
from nexus.execution.runtime_contracts import ExecutionDeniedError, ExecutionRegistration
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import KINDS, registration_digest


async def register_locked(
    session: AsyncSession,
    request: ExecutionRegistration,
    registered: RegisteredWork,
) -> ExecutionWork:
    """Derive ancestry from the registered work, never the request's chosen IDs."""
    work = request.work
    if (work.company_id, work.task_id, work.trace_id, work.budget_usd) != (
        registered.company_id,
        registered.task_id,
        registered.trace_id,
        registered.allocation_usd,
    ):
        raise ExecutionDeniedError(
            "Execution work disagrees with its registered identity/allocation"
        )
    existing = await session.scalar(
        select(ExecutionWork)
        .where(
            ExecutionWork.company_id == work.company_id,
            ExecutionWork.task_id == work.task_id,
        )
        .with_for_update()
    )
    digest = registration_digest(request)
    if existing is not None:
        if existing.registration_hash != digest:
            raise ExecutionDeniedError("Logical work already binds another run/version/quota")
        return existing
    parent = None
    if registered.parent_task_id is not None:
        parent = await session.scalar(
            select(ExecutionWork)
            .where(
                ExecutionWork.company_id == work.company_id,
                ExecutionWork.task_id == registered.parent_task_id,
            )
            .with_for_update()
        )
        if parent is None:
            raise ExecutionDeniedError("Registered parent execution quota is unavailable")
        for kind in KINDS:
            requested = getattr(request.quota, kind)
            available = (
                getattr(parent, f"{kind}_limit")
                - getattr(parent, f"{kind}_used")
                - getattr(parent, f"{kind}_delegated")
            )
            if requested > available:
                raise ExecutionDeniedError("Parent has insufficient undelegated lifetime quota")
        for kind in KINDS:
            setattr(
                parent,
                f"{kind}_delegated",
                getattr(parent, f"{kind}_delegated") + getattr(request.quota, kind),
            )
    row = ExecutionWork(
        company_id=work.company_id,
        task_id=work.task_id,
        trace_id=work.trace_id,
        actor_id=registered.actor_id,
        workspace_id=registered.workspace_id,
        parent_task_id=registered.parent_task_id,
        run_id=request.run_id,
        registration_json=request.model_dump_json(),
        registration_hash=digest,
        workflow_name=request.workflow_name,
        workflow_version=request.workflow_version,
        model_profile=request.model_profile,
        model_registry_version=request.model_registry_version,
        **{f"{kind}_limit": getattr(request.quota, kind) for kind in KINDS},
    )
    session.add(row)
    await session.flush()
    return row

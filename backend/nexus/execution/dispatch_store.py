"""Reserve stable application scheduling identity before touching the DBOS queue."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.dispatch_models import SegmentDispatch
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_store import next_segment_id
from nexus.execution.runtime_support import snapshot


async def reserve_dispatch(
    session: AsyncSession,
    command: SegmentCommand,
    *,
    workflow_name: str,
    workflow_version: str,
) -> None:
    """Caller holds CompanyControl first; command never supplies quota or resettable IDs."""
    row = await session.scalar(
        select(ExecutionWork)
        .where(
            ExecutionWork.company_id == command.company_id,
            ExecutionWork.task_id == command.task_id,
        )
        .with_for_update()
    )
    if row is None or (
        row.trace_id,
        row.actor_id,
        row.workspace_id,
        row.run_id,
        row.workflow_name,
        row.workflow_version,
    ) != (
        command.trace_id,
        command.actor_id,
        command.workspace_id,
        command.run_id,
        workflow_name,
        workflow_version,
    ):
        raise ValueError("Continuation binding does not match registered execution")
    existing = await session.get(SegmentDispatch, (command.company_id, command.action_id))
    if existing is not None:
        if existing.binding_json != command.model_dump_json():
            raise ValueError("Action already binds another permanent segment binding")
        return
    if row.worker_id is not None or row.state not in {"eligible", "awaiting_approval"}:
        raise ValueError("Continuation binding requires a released eligible segment")
    if command.segment_id != next_segment_id(snapshot(row)):
        raise ValueError("Continuation binding is not the next persistent execution segment")
    session.add(
        SegmentDispatch(
            company_id=command.company_id,
            action_id=command.action_id,
            task_id=command.task_id,
            run_id=command.run_id,
            segment_id=command.segment_id,
            workflow_id=command.workflow_id,
            binding_json=command.model_dump_json(),
        )
    )
    await session.flush()

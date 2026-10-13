"""Transaction-bound scheduling for the registered company segment workflow.

DBOS 3.2's SQL enqueue preserves an existing workflow ID without checking its
original inputs. This adapter checks the immutable binding after enqueue, while
the caller still owns the company mutex/transaction. It never commits, launches
a worker, calls a provider or treats queue deduplication as action authorization.
"""

from __future__ import annotations

import json

from sqlalchemy import select, text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.contracts.actions import ActionProposal
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.dispatch_store import reserve_dispatch
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import JournalAction
from nexus.harness.lifecycle import ActionState

WORKFLOW_NAME = "company.action.segment.v1"
QUEUE_NAME = "company.actions.v1"
APPLICATION_NAME = "nexus-company"
APPLICATION_VERSION = "company-v0.2-m1"

_ENQUEUE = text("""
SELECT dbos.enqueue_workflow(
    workflow_name => :workflow_name, queue_name => :queue_name,
    positional_args => ARRAY[CAST(:payload AS json)],
    workflow_id => :workflow_id, app_version => :version,
    application_name => :application_name
)
""")

_BINDING = text("""
SELECT ws.name, ws.queue_name, ws.application_version, ws.application_name,
       ws.serialization, wi.inputs
FROM dbos.workflow_status ws
LEFT JOIN dbos.workflow_input wi ON wi.workflow_uuid = ws.workflow_uuid
WHERE ws.workflow_uuid = :workflow_id
FOR UPDATE OF ws
""")


async def _require_authorized(
    session: AsyncSession, command: SegmentCommand, scope: LedgerScope
) -> None:
    row = await session.scalar(
        select(JournalAction).where(
            JournalAction.company_id == scope.company_id,
            JournalAction.task_id == scope.task_id,
            JournalAction.trace_id == scope.trace_id,
            JournalAction.id == command.action_id,
        )
    )
    if row is None or row.state != ActionState.AUTHORIZED or row.consumed_at is None:
        raise ValueError("Continuation requires an authorized exact action")
    if ActionProposal.model_validate_json(row.proposal_json).actor_id != command.actor_id:
        raise ValueError("Continuation actor does not own the authorized action")


def _require_binding(row: RowMapping | None, payload: str) -> None:
    """Validate the SQLAlchemy result and its stored portable JSON against exact inputs."""
    if row is None or (
        row["name"],
        row["queue_name"],
        row["application_version"],
        row["application_name"],
        row["serialization"],
    ) != (WORKFLOW_NAME, QUEUE_NAME, APPLICATION_VERSION, APPLICATION_NAME, "portable_json"):
        raise ValueError("Existing DBOS workflow binding conflicts with this segment")
    try:
        inputs = json.loads(row["inputs"])
    except (TypeError, ValueError) as exc:
        raise ValueError("Existing DBOS input binding is unreadable") from exc
    if inputs != {"positionalArgs": [payload], "namedArgs": {}}:
        raise ValueError("Existing DBOS input binding conflicts with this segment")


async def enqueue_authorized_segment(
    session: AsyncSession, command: SegmentCommand, scope: LedgerScope
) -> str:
    """Enqueue within the caller's authorization transaction or roll back together.

    This trusted internal adapter is not a public intake endpoint. The caller
    must hold CompanyControl first and validate current registered identity,
    resource revisions and persistent runtime run/segment binding before use.
    """
    command = SegmentCommand.model_validate(command.model_dump())
    command.require_scope(scope)
    if not session.in_transaction():
        raise ValueError("Scheduling requires the caller's authorization transaction")
    await _require_authorized(session, command, scope)
    await reserve_dispatch(
        session,
        command,
        workflow_name=WORKFLOW_NAME,
        workflow_version=APPLICATION_VERSION,
    )
    payload = command.model_dump_json()
    parameters = {
        "workflow_name": WORKFLOW_NAME,
        "queue_name": QUEUE_NAME,
        "payload": json.dumps(payload),
        "workflow_id": command.workflow_id,
        "version": APPLICATION_VERSION,
        "application_name": APPLICATION_NAME,
    }
    result = await session.scalar(_ENQUEUE, parameters)
    binding = await session.execute(_BINDING, {"workflow_id": command.workflow_id})
    _require_binding(binding.mappings().one_or_none(), payload)
    if result != command.workflow_id:
        raise ValueError("DBOS returned another workflow identity")
    return command.workflow_id

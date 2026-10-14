"""TEST-only actual body-free native/SDK history export, never synthetic authority or billing."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID

from sqlalchemy import func, select, text

from nexus.company.brain.source_models import BrainSourceHead
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.base import ValueContract
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.transactions import management_owner_transaction
from nexus.company.notifications.dispatch_contracts import NotificationProviderObservation
from nexus.company.notifications.dispatch_models import NotificationDispatchRow
from nexus.company.notifications.observation_models import NotificationObservationRow
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.dispatch_models import SegmentDispatch
from nexus.execution.effect_support import require_receipt_binding
from nexus.execution.notification_dispatch_read import (
    NotificationQueueRecord,
    require_issued_binding,
    require_notification_command,
    require_queue_identity,
)
from nexus.execution.notification_worker_observation import require_observation_mirrors
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt, ExecutionWork
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import CostHold, JournalAction
from nexus.tests.integration.test_company_directory import control
from nexus.tests.notification_durable_pg_fixture import DurableNotificationCase
from nexus.tests.notification_worker_enqueue_pg_fixture import AtomicNotificationDatabases


class DurableNotificationProof(ValueContract):
    """All metadata comes from actual native or SDK rows, without draft/private source bodies."""

    queue_status: str
    sdk_output: str
    step_names: tuple[str, ...]
    queue_binding_sha256: str
    command_sha256: str
    registration_sha256: str
    intent_sha256: str
    intent_fence: int
    slot_intent_fence: int
    slot_sha256: str
    receipt: ActionReceipt
    observation: NotificationProviderObservation
    hold: tuple[str, str | None, str]
    native_counts: tuple[int, ...]
    counters: tuple[tuple[UUID, int, int], ...]
    model_requests: int
    tool_attempts: int
    current_fence: int
    lease_released: bool
    source_action_state: str
    database: str
    role: str


async def durable_queued_window(
    databases: AtomicNotificationDatabases,
    case: DurableNotificationCase,
) -> dict[str, object]:
    """Actual initial source and original credential windows; no deadline refresh or fake clock."""
    async with management_owner_transaction(
        databases.app, control(), case.atomic.credential.identity
    ) as (session, _, _):
        heads = tuple((await session.scalars(select(BrainSourceHead))).all())
        now = await db_now(session)
        deadlines = [h.fresh_until for h in heads if h.fresh_until is not None]
        assert deadlines and all(h.availability == "available" for h in heads)
        assert min((d - now).total_seconds() for d in deadlines) >= 180
        assert (case.atomic.credential.expires_at - now).total_seconds() >= 40
        return {
            "db_now": now.isoformat(),
            "head_pins": [
                {
                    "source_id": str(h.source_id),
                    "revision_id": str(h.current_revision_id),
                    "generation": h.generation,
                    "fresh_until": h.fresh_until.isoformat() if h.fresh_until else None,
                }
                for h in heads
            ],
            "credential_issued_at": case.atomic.credential.issued_at.isoformat(),
            "credential_expires_at": case.atomic.credential.expires_at.isoformat(),
            "worker_registration_file_sha256": case.atomic.snapshot.sha256,
        }


async def durable_notification_proof(
    databases: AtomicNotificationDatabases,
    case: DurableNotificationCase,
    command: SegmentCommand,
) -> DurableNotificationProof:
    """Actual original issuance and SDK output must share exact command/receipt/observation pins."""
    # Cohesive snapshot exception: original slot/receipt/observation and retained
    # native attempts/hold are read together; a separate SDK query proves actual durable output.
    atomic = case.atomic
    async with management_owner_transaction(
        databases.app, control(), atomic.credential.identity
    ) as (session, _, _):
        work = await session.get(ExecutionWork, (command.company_id, command.task_id))
        intent = await session.get(EffectIntent, (command.company_id, command.action_id))
        slot = await session.get(
            NotificationDispatchRow, (command.company_id, atomic.selection.draft_id)
        )
        action = await session.get(JournalAction, command.action_id)
        hold = await session.get(CostHold, command.action_id)
        dispatch = await session.get(SegmentDispatch, (command.company_id, command.action_id))
        source = await session.get(JournalAction, atomic.source_action_id)
        assert all(x is not None for x in (work, intent, slot, action, hold, dispatch, source))
        assert work is not None and intent is not None and slot is not None and action is not None
        assert hold is not None and dispatch is not None and source is not None
        assert (
            dispatch.binding_json == command.model_dump_json()
            and dispatch.workflow_id == command.workflow_id
        )
        from nexus.company.contracts.actions import ActionProposal

        proposal = ActionProposal.model_validate_json(action.proposal_json)
        params = require_notification_command(
            atomic.snapshot.value.registration.sender,
            proposal,
            command,
            atomic.services.dispatcher.resource_symbol,
        )
        require_issued_binding(work, proposal, params, intent, slot)
        assert intent.receipt_json is not None
        receipt = ActionReceipt.model_validate_json(intent.receipt_json)
        require_receipt_binding(intent, receipt)
        rows = tuple(
            (
                await session.scalars(
                    select(NotificationObservationRow).where(
                        NotificationObservationRow.company_id == command.company_id,
                        NotificationObservationRow.draft_id == slot.draft_id,
                        NotificationObservationRow.observation_kind == "submission",
                    )
                )
            ).all()
        )
        assert len(rows) == 1
        observation = NotificationProviderObservation.model_validate_json(rows[0].record_json)
        require_observation_mirrors(rows[0], observation)
        assert observation.receipt_sha256 == canonical_sha256(receipt)
        assert observation.submission is not None
        assert observation.submission.response_sha256 == case.requests[0].response_sha256
        assert slot.idempotency_key == case.requests[0].idempotency_key
        assert slot.payload_sha256 == case.requests[0].body_sha256
        counts = []
        for table in (
            EffectIntent,
            ExecutionAttempt,
            NotificationDispatchRow,
            NotificationObservationRow,
        ):
            count = await session.scalar(select(func.count()).select_from(table))
            assert isinstance(count, int)
            counts.append(count)
        works = tuple(
            (await session.scalars(select(ExecutionWork).order_by(ExecutionWork.task_id))).all()
        )
        database = await session.scalar(text("SELECT current_database()"))
        role = await session.scalar(text("SELECT current_user"))
        assert isinstance(database, str) and isinstance(role, str)
        intent_data = {
            name: getattr(intent, name)
            for name in (
                "company_id",
                "action_id",
                "task_id",
                "trace_id",
                "run_id",
                "proposal_hash",
                "intent_fence",
                "attempt_kind",
                "state",
                "created_at",
                "receipt_json",
                "verification_json",
            )
        }
        slot_data = {c.name: getattr(slot, c.name) for c in slot.__table__.columns}
        money = (
            str(hold.amount_usd),
            str(hold.actual_usd) if hold.actual_usd is not None else None,
            hold.state,
        )
    async with databases.admin() as session:
        saved = (
            (
                await session.execute(
                    text(
                        "SELECT ws.name,ws.queue_name,ws.application_version,ws.application_name,"
                        "ws.serialization,ws.status,wi.inputs,wo.output,wo.error "
                        "FROM dbos.workflow_status ws JOIN dbos.workflow_input wi "
                        "ON wi.workflow_uuid=ws.workflow_uuid "
                        "JOIN dbos.workflow_output wo ON wo.workflow_uuid=ws.workflow_uuid "
                        "WHERE ws.workflow_uuid=:workflow_id"
                    ),
                    {"workflow_id": command.workflow_id},
                )
            )
            .mappings()
            .one()
        )
        assert saved["error"] is None and isinstance(saved["output"], str)
        queue = NotificationQueueRecord.model_validate(
            {
                key: saved[key]
                for key in (
                    "name",
                    "queue_name",
                    "application_version",
                    "application_name",
                    "serialization",
                    "status",
                    "inputs",
                )
            }
        )
        require_queue_identity(queue, command, issued=True)
        output = json.loads(saved["output"])
        assert isinstance(output, str)
        steps = tuple(
            (
                await session.scalars(
                    text(
                        "SELECT function_name FROM dbos.operation_outputs "
                        "WHERE workflow_uuid=:workflow_id "
                        "ORDER BY function_id"
                    ),
                    {"workflow_id": command.workflow_id},
                )
            ).all()
        )
        assert all(isinstance(x, str) for x in steps)
    return DurableNotificationProof(
        queue_status=queue.status,
        sdk_output=output,
        step_names=steps,
        queue_binding_sha256=canonical_sha256(queue),
        command_sha256=canonical_sha256(command),
        registration_sha256=work.registration_hash,
        intent_sha256=hashlib.sha256(
            json.dumps(intent_data, sort_keys=True, default=str).encode()
        ).hexdigest(),
        slot_sha256=hashlib.sha256(
            json.dumps(slot_data, sort_keys=True, default=str).encode()
        ).hexdigest(),
        intent_fence=intent.intent_fence,
        slot_intent_fence=slot.intent_fence,
        receipt=receipt,
        observation=observation,
        hold=money,
        native_counts=tuple(counts),
        counters=tuple((x.task_id, x.model_requests_used, x.tool_attempts_used) for x in works),
        model_requests=work.model_requests_used,
        tool_attempts=work.tool_attempts_used,
        current_fence=work.fence,
        lease_released=all(
            getattr(work, n) is None
            for n in ("worker_id", "lease_principal_id", "lease_until", "lease_mode")
        ),
        source_action_state=source.state,
        database=database,
        role=role,
    )

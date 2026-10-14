"""In-memory transaction ordering only; native database/queue authority remains unproven."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.contracts.actions import ApprovalDecision
from nexus.company.management.native_profile_admission import ledger_scope
from nexus.company.management.plan_support import CurrentPlanBinding
from nexus.company.management.scheduling_contracts import ScheduledWork
from nexus.company.management.scheduling_projection import projection
from nexus.company.management.scheduling_support import SchedulingCandidate
from nexus.company.notifications import worker_enqueue
from nexus.company.notifications.dispatch_store import NotificationTransportConfiguration
from nexus.company.notifications.managed_admission import ManagedNotificationAdmission
from nexus.company.notifications.managed_contracts import NativeNotificationSelection
from nexus.company.notifications.managed_preparation import ManagedNotificationPreparation
from nexus.company.notifications.worker_config import WorkerRegistrationSnapshot
from nexus.company.notifications.worker_consumer import WorkerSenderFinalGuard
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.company.notifications.worker_services import WorkerSenderAdmission
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.dispatch_models import SegmentDispatch
from nexus.execution.notification_worker_services import NotificationDispatchWorkerServices
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CompanyControl, JournalAction
from nexus.harness.journal_submission import pending_action_record
from nexus.tests.notification_rule_fixtures import declared_draft
from nexus.tests.notification_worker_phase3_unit_fixture import dispatch_services
from nexus.tests.unit.test_company_notification_native_profiles import notification_plan
from nexus.tests.unit.test_company_notification_worker_services import guarded_services


@dataclass(frozen=True)
class EnqueueFlow:
    services: NotificationDispatchWorkerServices
    selection: NativeNotificationSelection
    credential: AuthenticatedWorkerIdentity
    snapshot: WorkerRegistrationSnapshot
    command: SegmentCommand
    events: list[str]
    queue: AsyncMock


async def enqueue_flow(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str = "none",
) -> EnqueueFlow:
    # Cohesive >50-line fixture exception: actual typed bindings/witness and one
    # nominated in-memory transaction share the same mock session. This is not PG proof.
    value = dispatch_services(root)
    _, guard = await guarded_services(root)
    value.dispatcher.worker_enabled = True
    value.dispatcher.configuration = NotificationTransportConfiguration(
        enabled=True,
        api_key=SecretStr("synthetic-unused-no-request"),
    )
    services = replace(value, enabled=True)
    binding, now = guard.registration.sender, datetime.now(UTC)
    work = ExecutionWork(
        company_id=binding.company_id,
        task_id=binding.task_id,
        trace_id=binding.trace_id,
        actor_id=binding.actor_id,
        workspace_id=binding.workspace_id,
        run_id=binding.run_id,
        state="eligible",
        worker_id=None,
        lease_until=None,
        waiting_action_id=None,
    )
    draft = declared_draft()
    recipient = draft.recipient_policy.model_copy(
        update={
            "owner_id": binding.actor_id,
            "registered_at": now - timedelta(minutes=1),
            "expires_at": now + timedelta(hours=1),
        }
    )
    draft = draft.model_copy(update={"recipient_policy": recipient})
    selection = NativeNotificationSelection(
        company_id=binding.company_id,
        draft_id=draft.draft_id,
        sender_task_id=binding.task_id,
        plan=guard.registration.plan,
    )
    _, payload = notification_plan()
    native = CurrentPlanBinding(
        company_id=binding.company_id,
        plan=selection.plan,
        child=payload.children[0].model_copy(update={"binding": binding}),
        work=payload.plan.items[0],
        work_sha256="a" * 64,
        procedure_id=UUID(int=840),
    )
    admitted = ManagedNotificationAdmission(
        native,
        draft,
        payload,
        (now + timedelta(seconds=5),),
    )
    action = services.reads.preparation._proposal(selection.plan, work, draft, "p1", "p1")
    decision = ApprovalDecision(
        company_id=binding.company_id,
        decision_id=UUID(int=841),
        action_id=action.action_id,
        action_revision=1,
        action_hash=action_hash(action),
        approver_id=binding.actor_id,
        decision="approved",
        issued_at=now - timedelta(seconds=1),
        expires_at=now + timedelta(hours=1),
    )
    row = JournalAction(
        id=action.action_id,
        company_id=binding.company_id,
        task_id=binding.task_id,
        trace_id=binding.trace_id,
        proposal_json=action.model_dump_json(),
        proposal_hash=action_hash(action),
        state="awaiting_approval",
        approval_json=decision.model_dump_json(),
        consumed_at=None,
    )
    command = SegmentCommand(
        company_id=binding.company_id,
        task_id=binding.task_id,
        trace_id=binding.trace_id,
        actor_id=binding.actor_id,
        workspace_id=binding.workspace_id,
        run_id=binding.run_id,
        action_id=action.action_id,
        segment_id=UUID(int=842),
    )
    session = MagicMock(spec=AsyncSession)
    events: list[str] = []
    session.flush = AsyncMock()

    def stored_scalar(statement: object, *args: object) -> str | None:
        if "dbos.workflow_status" in str(statement):
            events.append("status_checked")
            return "CANCELLED" if fault == "terminal" else "ENQUEUED"
        return None

    session.scalar = AsyncMock(side_effect=stored_scalar)
    scalar_rows = MagicMock()
    scalar_rows.all.return_value = (row.id,)
    session.scalars = AsyncMock(return_value=scalar_rows)
    prior = (
        SegmentDispatch(binding_json=command.model_dump_json())
        if fault in {"replay", "terminal"}
        else None
    )
    session.get = AsyncMock(
        side_effect=lambda model, key: (
            row if model is JournalAction else prior if model is SegmentDispatch else None
        )
    )
    control = CompanyControl(company_id=binding.company_id, owner_id=binding.actor_id)
    _install_transaction(monkeypatch, session, control, events, now)

    async def qualify(
        preparation: ManagedNotificationPreparation, *args: object
    ) -> ManagedNotificationAdmission:
        assert args[0] is session
        assert isinstance(preparation.operation_guard, WorkerSenderFinalGuard)
        preparation.operation_guard.capture(
            WorkerSenderAdmission(native, payload, work, admitted.deadlines)
        )
        events.append("qualified")
        return admitted

    async def authorize(*args: object) -> object:
        assert args[0] is session
        events.append("authorized")
        row.state, row.consumed_at = "authorized", now
        return pending_action_record(row)

    queue = _install_queue(monkeypatch, native, command, events, fault)
    monkeypatch.setattr(worker_enqueue, "execution_row", AsyncMock(return_value=work))
    monkeypatch.setattr(worker_enqueue, "current_prepared_admission", qualify)
    monkeypatch.setattr(worker_enqueue, "authorize_registered_pending_locked", authorize)
    monkeypatch.setattr(
        worker_enqueue,
        "inspect_task",
        AsyncMock(
            return_value=SchedulingCandidate(
                work,
                native,
                projection(work, native, "eligible", "ready"),
                row,
                guard.witness.identity,
                ledger_scope(binding),
            )
        ),
    )
    actual = (
        command.model_copy(update={"action_id": UUID(int=843)}) if fault == "command" else command
    )
    monkeypatch.setattr(worker_enqueue, "dispatched_binding", AsyncMock(return_value=actual))
    monkeypatch.setattr(worker_enqueue, "require_effect_authority", AsyncMock(return_value=row))
    monkeypatch.setattr(worker_enqueue, "db_now", _clock(now, guard.witness, events, fault))
    return EnqueueFlow(services, selection, guard.witness, guard.snapshot, command, events, queue)


def _install_transaction(
    monkeypatch: pytest.MonkeyPatch,
    session: AsyncSession,
    control: CompanyControl,
    events: list[str],
    now: datetime,
) -> None:
    @asynccontextmanager
    async def transaction(
        *args: object, **kwargs: object
    ) -> AsyncIterator[tuple[AsyncSession, CompanyControl, datetime]]:
        events.append("begin")
        try:
            yield session, control, now
        except BaseException:
            events.append("rollback")
            raise
        else:
            events.append("commit")

    monkeypatch.setattr(worker_enqueue, "runtime_transaction", transaction)


def _install_queue(
    monkeypatch: pytest.MonkeyPatch,
    native: CurrentPlanBinding,
    command: SegmentCommand,
    events: list[str],
    fault: str,
) -> AsyncMock:
    result = ScheduledWork.model_validate(
        projection(
            MagicMock(company_id=command.company_id),
            native,
            "eligible",
            "ready",
        ).model_dump()
        | {
            "action_id": command.action_id,
            "dispatch": "enqueued",
            "segment_id": command.segment_id,
            "workflow_id": command.workflow_id,
        }
    )

    async def enqueue(*args: object) -> ScheduledWork:
        events.append("queued")
        if fault == "queue":
            raise ValueError("Synthetic queue failure")
        return result

    queue = AsyncMock(side_effect=enqueue)
    monkeypatch.setattr(worker_enqueue, "enqueue_candidate", queue)
    return queue


def _clock(
    now: datetime,
    credential: AuthenticatedWorkerIdentity,
    events: list[str],
    fault: str,
) -> AsyncMock:
    async def clock(*args: object) -> datetime:
        if "queued" in events:
            if fault == "source":
                return now + timedelta(seconds=6)
            if fault == "credential":
                return credential.expires_at
        return now

    return AsyncMock(side_effect=clock)

"""Pure current signed witness/command fixtures; no native DB, queue, HTTP or SDK proof."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr

from nexus.company.management.native_profile_admission import ledger_scope
from nexus.company.notifications.dispatch_store import NotificationTransportConfiguration
from nexus.company.notifications.worker_guard import NotificationOperationGuard
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.notification_worker_services import NotificationDispatchWorkerServices
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.harness.journal_contracts import LedgerScope
from nexus.tests.notification_worker_phase3_unit_fixture import dispatch_services
from nexus.tests.unit.test_company_notification_worker_services import guarded_services


@dataclass(frozen=True)
class RecoveryInputs:
    services: NotificationDispatchWorkerServices
    guard: NotificationOperationGuard
    command: SegmentCommand
    scope: LedgerScope
    lease: ExecutionLease
    recover: AsyncMock
    release: AsyncMock


async def recovery_inputs(root: Path, monkeypatch: pytest.MonkeyPatch) -> RecoveryInputs:
    """One actual sealed synthetic credential, with mocked acquisition methods only."""
    value = dispatch_services(root)
    _, original = await guarded_services(root)
    guard = NotificationOperationGuard(
        original.witness, original.snapshot, value.reads.registrations
    )
    value.dispatcher.worker_enabled = True
    value.dispatcher.configuration = NotificationTransportConfiguration(
        enabled=True,
        api_key=SecretStr("synthetic-unused-durable-only"),
    )
    services = replace(value, enabled=True)
    binding = guard.registration.sender
    from uuid import UUID

    command = SegmentCommand(
        company_id=binding.company_id,
        task_id=binding.task_id,
        trace_id=binding.trace_id,
        actor_id=binding.actor_id,
        workspace_id=binding.workspace_id,
        run_id=binding.run_id,
        action_id=UUID(int=882),
        segment_id=UUID(int=883),
    )
    lease = ExecutionLease(
        company_id=command.company_id,
        task_id=command.task_id,
        trace_id=command.trace_id,
        actor_id=command.actor_id,
        workspace_id=command.workspace_id,
        run_id=command.run_id,
        workflow_version="v1",
        segment_id=command.segment_id,
        worker_id=services.worker_id,
        fence=2,
        expires_at=datetime.now(UTC) + timedelta(seconds=60),
        mode="reconcile",
    )
    recover, release = AsyncMock(return_value=lease), AsyncMock()
    monkeypatch.setattr(services.execution, "recover_dispatched", recover)
    monkeypatch.setattr(services.execution, "release", release)
    return RecoveryInputs(services, guard, command, ledger_scope(binding), lease, recover, release)

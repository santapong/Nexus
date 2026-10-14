"""Issued native records suppress POST; exception reporting cannot replace native history."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from dbos._registrations import get_dbos_func_name

from nexus.execution import notification_worker as worker
from nexus.execution import notification_worker_effect as effect
from nexus.execution.notification_worker_context import NotificationContext
from nexus.execution.notification_worker_contracts import NotificationSegmentResult
from nexus.execution.notification_worker_observation import NotificationNativeHistory
from nexus.execution.runtime_contracts import ExecutionDeniedError
from nexus.tests.notification_durable_unit_fixture import RecoveryInputs, recovery_inputs
from nexus.tests.unit.test_notification_durable_dispatch_read import notification_action


def test_fixed_sdk_procedure_names_match_reviewed_workflow_and_nonretry_step() -> None:
    assert get_dbos_func_name(worker.notification_segment) == "internal.owner-notification"
    assert get_dbos_func_name(worker.notification_effect_step) == "nexus.notification.effect.v1"


def context(value: RecoveryInputs, *, execute: bool = False) -> NotificationContext:
    action = notification_action().model_copy(update={"action_id": value.command.action_id})
    return NotificationContext(
        value.command,
        value.guard.registration.sender,
        action,
        UUID(int=30),
        value.guard.witness.identity,
        value.guard.witness,
        value.guard,
        value.lease.model_copy(update={"mode": "execute"}) if execute else value.lease,
    )


@pytest.mark.parametrize("state", ["intent", "outcome_unknown", "succeeded", "failed"])
async def test_any_actual_issued_basis_prevents_a_new_dispatch_even_on_execute_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    state: str,
) -> None:
    value = await recovery_inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(
        effect,
        "read_notification_history",
        AsyncMock(return_value=NotificationNativeHistory(state, None, None, datetime.now(UTC))),
    )
    dispatch = AsyncMock()
    monkeypatch.setattr(value.services.dispatcher, "dispatch_with_credential", dispatch)
    await effect.run_notification_effect(value.services, context(value, execute=True))
    dispatch.assert_not_awaited()


async def test_unissued_execute_calls_only_the_existing_sealed_dispatcher_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = await recovery_inputs(tmp_path, monkeypatch)
    current = context(value, execute=True)
    monkeypatch.setattr(
        effect,
        "read_notification_history",
        AsyncMock(return_value=NotificationNativeHistory(None, None, None, datetime.now(UTC))),
    )
    dispatch = AsyncMock()
    monkeypatch.setattr(value.services.dispatcher, "dispatch_with_credential", dispatch)
    await effect.run_notification_effect(value.services, current)
    dispatch.assert_awaited_once_with(
        current.lease, current.credential, current.draft_id, current.command.action_id
    )


async def test_unissued_reconcile_mode_never_receives_fresh_effect_permission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = await recovery_inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(
        effect,
        "read_notification_history",
        AsyncMock(return_value=NotificationNativeHistory(None, None, None, datetime.now(UTC))),
    )
    dispatch = AsyncMock()
    monkeypatch.setattr(value.services.dispatcher, "dispatch_with_credential", dispatch)
    with pytest.raises(ExecutionDeniedError):
        await effect.run_notification_effect(value.services, context(value))
    dispatch.assert_not_awaited()


async def test_after_receipt_adapter_failure_observer_result_preserves_known_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = await recovery_inputs(tmp_path, monkeypatch)
    current = context(value)
    known = NotificationSegmentResult(
        company_id=current.command.company_id,
        command=current.command,
        status="submitted",
        receipt_id=current.command.action_id,
        receipt_sha256="a" * 64,
        observed_at=datetime.now(UTC),
    )
    monkeypatch.setattr(worker, "prepare_notification_context", AsyncMock(return_value=current))
    monkeypatch.setattr(
        worker,
        "run_notification_effect",
        AsyncMock(side_effect=ValueError("observation append failed")),
    )
    observe = AsyncMock(return_value=known)
    monkeypatch.setattr(worker, "observe_notification_segment", observe)
    result = await worker.execute_notification_segment(
        value.services, current.command, workflow_id=current.command.workflow_id
    )
    assert result == known
    assert observe.await_args is not None
    assert observe.await_args.kwargs["failure_kind"] == "ValueError"
    value.release.assert_awaited_once_with(current.lease, current.identity)


async def test_missing_current_history_permission_propagates_after_releasing_acquired_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = await recovery_inputs(tmp_path, monkeypatch)
    current = context(value)
    monkeypatch.setattr(worker, "prepare_notification_context", AsyncMock(return_value=current))
    monkeypatch.setattr(worker, "run_notification_effect", AsyncMock())
    monkeypatch.setattr(
        worker,
        "observe_notification_segment",
        AsyncMock(side_effect=ExecutionDeniedError("current owner denied")),
    )
    with pytest.raises(ExecutionDeniedError):
        await worker.execute_notification_segment(
            value.services, current.command, workflow_id=current.command.workflow_id
        )
    value.release.assert_awaited_once_with(current.lease, current.identity)


async def test_unexpected_programming_failure_propagates_after_exact_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = await recovery_inputs(tmp_path, monkeypatch)
    current = context(value)
    monkeypatch.setattr(worker, "prepare_notification_context", AsyncMock(return_value=current))
    monkeypatch.setattr(
        worker, "run_notification_effect", AsyncMock(side_effect=RuntimeError("bug"))
    )
    observe = AsyncMock()
    monkeypatch.setattr(worker, "observe_notification_segment", observe)
    with pytest.raises(RuntimeError, match="bug"):
        await worker.execute_notification_segment(
            value.services, current.command, workflow_id=current.command.workflow_id
        )
    observe.assert_not_awaited()
    value.release.assert_awaited_once_with(current.lease, current.identity)

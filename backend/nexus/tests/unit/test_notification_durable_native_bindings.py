"""Native metadata comparisons reject crossed receipts, slots and immutable observation mirrors."""

import json
from uuid import UUID

import pytest

from nexus.company.notifications.dispatch_models import NotificationDispatchRow
from nexus.company.notifications.ledger_rules import stable_idempotency_key
from nexus.company.notifications.observation_support import observation_row
from nexus.execution.notification_dispatch_read import (
    NotificationQueueRecord,
    require_issued_binding,
    require_notification_command,
    require_queue_identity,
)
from nexus.execution.notification_worker_observation import require_observation_mirrors
from nexus.execution.runtime_contracts import ExecutionDeniedError
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.harness.canonical import action_hash
from nexus.tests.unit.test_company_notification_worker_config import registration
from nexus.tests.unit.test_notification_durable_dispatch_read import (
    native_command,
    notification_action,
)
from nexus.tests.unit.test_notification_durable_observation import observation, receipt


def issued_rows() -> tuple[ExecutionWork, EffectIntent, NotificationDispatchRow]:
    command, action = native_command(), notification_action()
    params = require_notification_command(
        registration().sender, action, command, "owner.notification"
    )
    work = ExecutionWork(
        company_id=command.company_id,
        task_id=command.task_id,
        trace_id=command.trace_id,
        run_id=command.run_id,
        actor_id=command.actor_id,
        registration_hash="f" * 64,
        fence=10,
    )
    intent = EffectIntent(
        company_id=command.company_id,
        task_id=command.task_id,
        trace_id=command.trace_id,
        run_id=command.run_id,
        action_id=action.action_id,
        proposal_hash=action_hash(action),
        intent_fence=1,
        attempt_kind="tool_attempts",
    )
    slot = NotificationDispatchRow(
        company_id=command.company_id,
        task_id=command.task_id,
        trace_id=command.trace_id,
        run_id=command.run_id,
        action_id=action.action_id,
        proposal_sha256=action_hash(action),
        registration_sha256=work.registration_hash,
        intent_fence=1,
        attempt_kind="tool_attempts",
        draft_id=params.draft_id,
        payload_sha256=params.payload_sha256,
        recipient_policy_sha256=params.recipient_policy_sha256,
        issued_by=command.actor_id,
        operation_id=action.action_id,
        audit_trace_id=command.trace_id,
        idempotency_key=stable_idempotency_key(command.company_id, params.draft_id),
    )
    return work, intent, slot


def test_original_issued_fence_does_not_become_new_current_lease_fence() -> None:
    work, intent, slot = issued_rows()
    require_issued_binding(
        work,
        notification_action(),
        require_notification_command(
            registration().sender, notification_action(), native_command(), "owner.notification"
        ),
        intent,
        slot,
    )
    assert work.fence != slot.intent_fence


@pytest.mark.parametrize(
    "field,value",
    [
        ("intent_fence", 10),
        ("idempotency_key", "other"),
        ("operation_id", UUID(int=991)),
        ("audit_trace_id", UUID(int=991)),
        ("recipient_policy_sha256", "0" * 64),
        ("proposal_sha256", "0" * 64),
        ("run_id", UUID(int=991)),
        ("issued_by", UUID(int=991)),
    ],
)
def test_crossed_immutable_slot_cannot_support_historical_audit(field: str, value: object) -> None:
    work, intent, slot = issued_rows()
    setattr(slot, field, value)
    with pytest.raises(ExecutionDeniedError):
        require_issued_binding(
            work,
            notification_action(),
            require_notification_command(
                registration().sender, notification_action(), native_command(), "owner.notification"
            ),
            intent,
            slot,
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("record_sha256", "0" * 64),
        ("receipt_id", UUID(int=997)),
        ("outcome", "rejected"),
        ("recorded_by", UUID(int=997)),
        ("record_json", "{}"),
    ],
)
def test_json_and_native_column_mirrors_must_both_match(field: str, value: object) -> None:
    original = observation(receipt(), "accepted")
    row = observation_row(original)
    require_observation_mirrors(row, original)
    setattr(row, field, value)
    with pytest.raises(ExecutionDeniedError):
        require_observation_mirrors(row, original)


@pytest.mark.parametrize(
    "queue,issued,allowed",
    [
        ("nexus.notifications.v1", False, True),
        (None, False, False),
        (None, True, True),
        ("foreign.queue", True, False),
    ],
)
def test_cleared_queue_is_exact_issued_history_exception_only(
    queue: str | None, issued: bool, allowed: bool
) -> None:
    command = native_command()
    value = NotificationQueueRecord(
        name="internal.owner-notification",
        queue_name=queue,
        application_version="v1",
        application_name="nexus-owner-notifications",
        serialization="portable_json",
        status="PENDING",
        inputs=json.dumps({"positionalArgs": [command.model_dump_json()], "namedArgs": {}}),
    )
    if allowed:
        require_queue_identity(value, command, issued=issued)
    else:
        with pytest.raises(ExecutionDeniedError):
            require_queue_identity(value, command, issued=issued)

"""Real post-SQL deadline crossing rolls back unissued native and DBOS state together."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from nexus.company.notifications.worker_enqueue import authorize_and_enqueue_prepared_notification
from nexus.company.notifications.worker_identity import WorkerIdentityDeniedError
from nexus.execution.runtime_contracts import ExecutionDeniedError
from nexus.tests.notification_worker_enqueue_pg_fixture import (
    AtomicNotificationDatabases,
    atomic_notification_databases,
)
from nexus.tests.notification_worker_postqueue_expiry_support import (
    PostQueueCapture,
    deadline_case,
    native_unissued_ledger,
    observe_sql_then_cross_deadline,
)
from nexus.tests.notification_worker_postqueue_fixture import staged_atomic_case

__all__ = ["atomic_notification_databases"]


@pytest.mark.parametrize("boundary", ["sender_read", "credential", "approval"])
async def test_actual_deadline_after_sql_enqueue_rolls_back_all_unissued_state(
    atomic_notification_databases: AtomicNotificationDatabases,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    case = await staged_atomic_case(atomic_notification_databases.app, tmp_path)
    witness, expiry = await deadline_case(case, boundary)
    before = await native_unissued_ledger(atomic_notification_databases, case)
    assert before.action_state == "awaiting_approval" and before.consumed_at is None
    assert before.reservations == (0, 0, 0) and before.effects == (0, 0, 0, 0)
    captures: list[PostQueueCapture] = []
    observe_sql_then_cross_deadline(monkeypatch, case, expiry, captures)
    expected = WorkerIdentityDeniedError if boundary == "credential" else ExecutionDeniedError
    with pytest.raises(expected):
        await authorize_and_enqueue_prepared_notification(
            case.services,
            case.selection,
            witness,
            case.snapshot,
        )
    assert len(captures) == 1 and captures[0].before < expiry <= captures[0].after
    assert captures[0].hold == ("0.010000", None, "held")
    assert captures[0].action_state == "authorized" and captures[0].consumed_at is not None
    assert captures[0].queue_status == "ENQUEUED" and captures[0].canonical_binding
    after = await native_unissued_ledger(atomic_notification_databases, case)
    assert after == before and not case.http_calls
    assert len(after.counters) == 5 and all(model == tool == 0 for _, model, tool in after.counters)
    receipt = {
        "scope": "Actual postqueue deadline and same transaction rollback only; no worker/provider",
        "boundary": boundary,
        "expiry": expiry.isoformat(),
        "before": before.model_dump(mode="json"),
        "after": after.model_dump(mode="json"),
        "capture": captures[0].model_dump(mode="json"),
        "hook_count": len(captures),
        "credential_dates": {
            "issued_at": witness.issued_at.isoformat(),
            "expires_at": witness.expires_at.isoformat(),
        },
    }
    await asyncio.to_thread(
        (tmp_path / "postqueue-expiry-proof.json").write_text,
        json.dumps(receipt, indent=2) + "\n",
    )

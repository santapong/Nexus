"""Actual SQL enqueue and exact replay; no DBOS worker, HTTP or provider execution."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from nexus.company.notifications.worker_enqueue import authorize_and_enqueue_prepared_notification
from nexus.tests.notification_worker_enqueue_pg_fixture import (
    AtomicNotificationDatabases,
    atomic_notification_case,
    atomic_notification_databases,
    enqueue_ledger,
)

__all__ = ["atomic_notification_databases"]


async def test_actual_owner_decision_atomic_enqueue_and_exact_replay_without_effects(
    atomic_notification_databases: AtomicNotificationDatabases,
    tmp_path: Path,
) -> None:
    case = await atomic_notification_case(atomic_notification_databases.app, tmp_path)
    first = await authorize_and_enqueue_prepared_notification(
        case.services,
        case.selection,
        case.credential,
        case.snapshot,
    )
    assert first.disposition == "enqueued"
    observed = await enqueue_ledger(atomic_notification_databases, case, first.command)
    assert observed.action_state == "authorized" and observed.consumed_at is not None
    assert observed.decision_sha256 == case.decision_sha256
    assert observed.hold == ("0.010000", None, "held")
    assert observed.dispatch_count == observed.workflow_count == 1
    assert observed.queue_status == "ENQUEUED"
    assert observed.canonical_binding and observed.effect_counts == (0, 0, 0, 0)
    assert len(observed.counters) == 5
    assert all(model == tool == 0 for _, model, tool in observed.counters)
    assert observed.source_action_state == "awaiting_approval" and not case.http_calls
    second = await authorize_and_enqueue_prepared_notification(
        case.services,
        case.selection,
        case.credential,
        case.snapshot,
    )
    assert second.disposition == "existing" and second.command == first.command
    assert await enqueue_ledger(atomic_notification_databases, case, second.command) == observed
    assert not case.http_calls
    receipt = {
        "scope": "Actual atomic SQL enqueue/exact replay only; no worker or provider",
        "command": first.command.model_dump(mode="json"),
        "first": first.model_dump(mode="json"),
        "second": second.model_dump(mode="json"),
        "native": observed.model_dump(mode="json"),
    }
    await asyncio.to_thread(
        (tmp_path / "atomic-enqueue-proof.json").write_text,
        json.dumps(receipt, indent=2) + "\n",
    )

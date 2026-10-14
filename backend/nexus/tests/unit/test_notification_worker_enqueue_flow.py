"""Mocked same-session ordering and late-window failures; not native persistence proof."""

from __future__ import annotations

from pathlib import Path

import pytest

from nexus.company.notifications.worker_enqueue import authorize_and_enqueue_prepared_notification
from nexus.tests.notification_worker_enqueue_unit_fixture import enqueue_flow


@pytest.mark.parametrize("fault", ["none", "replay"])
async def test_atomic_composition_returns_only_after_same_transaction_final_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    case = await enqueue_flow(tmp_path, monkeypatch, fault)
    value = await authorize_and_enqueue_prepared_notification(
        case.services,
        case.selection,
        case.credential,
        case.snapshot,
    )
    assert value.command == case.command
    assert value.disposition == ("existing" if fault == "replay" else "enqueued")
    assert case.events == [
        "begin",
        "qualified",
        "authorized",
        "qualified",
        "queued",
        "status_checked",
        "qualified",
        "commit",
    ]
    case.queue.assert_awaited_once()


@pytest.mark.parametrize("fault", ["queue", "command", "source", "credential"])
async def test_queue_or_late_saved_window_and_command_failure_cannot_return_committed_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    case = await enqueue_flow(tmp_path, monkeypatch, fault)
    with pytest.raises(ValueError):
        await authorize_and_enqueue_prepared_notification(
            case.services,
            case.selection,
            case.credential,
            case.snapshot,
        )
    assert "authorized" in case.events and "queued" in case.events
    assert case.events[-1] == "rollback" and "commit" not in case.events
    case.queue.assert_awaited_once()

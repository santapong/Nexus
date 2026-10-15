"""Bounded two-phase source composition tests; markers cannot prove PostgreSQL rollback."""

from unittest.mock import MagicMock

import pytest

from nexus.company.notifications.worker_identity import WorkerIdentityDeniedError
from nexus.tests.unit.strategy_publication_flow_fixture import PublicationFlow, publication_flow


async def publish(case: PublicationFlow) -> None:
    await case.store.publish_author(
        case.lease,
        case.source.credential.identity,
        case.prepared.action_id,
        case.prepared,
        credential=case.source.credential,
    )


async def test_two_graphs_share_one_original_intent_and_both_blob_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = publication_flow(monkeypatch)
    await publish(case)
    assert case.markers == ["enter", "commit", "enter", "commit"]
    assert case.store.blobs.save.await_count == 2  # type: ignore[attr-defined]
    assert case.writer.await_count == 1
    args = case.writer.await_args
    assert args is not None and args.args[2] == case.prepared
    assert case.work.tool_attempts_used == 1 and case.work.model_requests_used == 0
    assert (
        case.work.fence == 1
        and case.prepared.compiled.prepared.inputs == case.source.original.inputs
    )


@pytest.mark.parametrize("deadline", ["initial_reader", "credential", "approval", "lease"])
async def test_last_clock_conserves_initial_windows_even_if_current_gate_drops_them(
    monkeypatch: pytest.MonkeyPatch, deadline: str
) -> None:
    case = publication_flow(monkeypatch)
    expires = (
        case.first.read.grants[0].expires_at
        if deadline == "initial_reader"
        else case.source.credential.expires_at
        if deadline == "credential"
        else case.first.approval.expires_at
        if deadline == "approval"
        else case.lease.expires_at
    )
    assert expires is not None

    async def last_flush() -> None:
        case.source.clock["now"] = expires

    case.session.flush.side_effect = last_flush
    with pytest.raises((ValueError, WorkerIdentityDeniedError)):
        await publish(case)
    assert case.markers == ["enter", "commit", "enter", "rollback"]
    assert case.writer.await_count == 1
    assert case.work.tool_attempts_used == 1 and case.work.model_requests_used == 0


async def test_partial_existing_graph_denies_before_any_blob_or_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = publication_flow(monkeypatch)
    presence = iter([MagicMock(), None])
    case.session.scalar.side_effect = lambda statement: (
        False if "pg_roles" in str(statement) else next(presence)
    )
    with pytest.raises(ValueError):
        await publish(case)
    case.store.blobs.save.assert_not_awaited()  # type: ignore[attr-defined]
    case.writer.assert_not_awaited()
    assert case.markers == ["enter", "rollback"]


async def test_exact_existing_graph_replays_without_blob_or_row_append(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = publication_flow(monkeypatch)
    case.session.scalar.side_effect = lambda statement: (
        False if "pg_roles" in str(statement) else MagicMock()
    )
    await publish(case)
    case.store.blobs.save.assert_not_awaited()  # type: ignore[attr-defined]
    case.writer.assert_not_awaited()
    assert case.markers == ["enter", "commit"]


async def test_final_actual_fence_change_denies_after_graph_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = publication_flow(monkeypatch)

    async def last_flush() -> None:
        case.work.fence = 2

    case.session.flush.side_effect = last_flush
    with pytest.raises(ValueError):
        await publish(case)
    assert case.markers[-1] == "rollback"
    assert case.work.tool_attempts_used == 1

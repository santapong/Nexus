"""Actual history/worker coordinator over supplied native READ, never a lease or credential."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.notifications.worker_identity import NotificationWorkerIdentities
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.dispatch_models import SegmentDispatch
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.harness.journal_models import CompanyControl, JournalAction
from nexus.tests.unit.nexus_intent_fixture import boundary
from nexus.tests.unit.nexus_report_fixture import services


@pytest.mark.parametrize("fault", ["none", "crossed-intent", "crossed-dispatch"])
async def test_known_issued_worker_reads_native_metadata_without_new_lease_or_authentication(
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    from nexus.execution import native_report_worker as worker
    from nexus.execution import nexus_report_history as history
    from nexus.tests.unit.nexus_cycle_fixture import key

    value = boundary(3)
    configured = services(value, value.install(monkeypatch))
    value.known()
    command = SegmentCommand(
        company_id=value.work.company_id,
        task_id=value.work.task_id,
        trace_id=value.work.trace_id,
        actor_id=value.work.actor_id,
        workspace_id=value.work.workspace_id,
        run_id=value.work.run_id,
        action_id=value.action.id,
        segment_id=value.lease.segment_id,
    )
    dispatch = SegmentDispatch(
        company_id=command.company_id,
        action_id=command.action_id,
        task_id=command.task_id,
        run_id=command.run_id,
        segment_id=command.segment_id,
        workflow_id=command.workflow_id,
        binding_json=command.model_dump_json(),
    )
    if fault == "crossed-intent":
        assert value.previous is not None
        value.previous.run_id = key("foreign-run")
    if fault == "crossed-dispatch":
        dispatch.binding_json = command.model_copy(
            update={"actor_id": key("foreign-actor")}
        ).model_dump_json()
    mock = MagicMock(spec=AsyncSession)
    session = cast(AsyncSession, mock)
    mock.__aenter__ = AsyncMock(return_value=session)
    mock.__aexit__ = AsyncMock(return_value=False)
    mock.begin = MagicMock(
        return_value=MagicMock(__aenter__=AsyncMock(), __aexit__=AsyncMock(return_value=False))
    )
    mock.execute = AsyncMock()

    async def get(model: type[object], selector: object) -> object | None:
        if model is ExecutionWork:
            return value.work
        if model is SegmentDispatch:
            return dispatch
        if model is EffectIntent:
            return value.previous
        if model is JournalAction:
            return value.action
        raise AssertionError("Unexpected current READ")

    mock.get = AsyncMock(side_effect=get)
    cast(MagicMock, configured.factory).return_value = session

    @asynccontextmanager
    async def transaction(
        *args: object, **kwargs: object
    ) -> AsyncIterator[tuple[AsyncSession, CompanyControl, MagicMock]]:
        yield session, value.control, MagicMock()

    monkeypatch.setattr(history, "runtime_transaction", transaction)
    claim = AsyncMock(side_effect=AssertionError("No known-history lease"))
    authenticate = AsyncMock(side_effect=AssertionError("No known-history credential refresh"))
    fresh = AsyncMock(side_effect=AssertionError("No fresh native context"))
    monkeypatch.setattr(configured.execution, "recover_dispatched", claim)
    monkeypatch.setattr(NotificationWorkerIdentities, "current", authenticate)
    monkeypatch.setattr(worker, "prepare_context", fresh)
    if fault == "none":
        result = await worker.execute_native_report(
            configured, command, workflow_id=command.workflow_id
        )
        assert result.status == "outcome_unknown" and "no_new_call" in result.limitations
        assert value.work.tool_attempts_used == 1 and value.hold.state == "unknown"
    else:
        with pytest.raises(ValueError):
            await history.read_nexus_report_history(configured, command)
    claim.assert_not_awaited()
    authenticate.assert_not_awaited()
    fresh.assert_not_awaited()

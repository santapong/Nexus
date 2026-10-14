"""Only exact prior lease acquisition waits; no effect/credential/segment is retried."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.execution import notification_lease_recovery as module
from nexus.execution.runtime_contracts import ExecutionDeniedError
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.journal_models import CompanyControl
from nexus.tests.notification_durable_unit_fixture import recovery_inputs


async def test_actual_live_prior_descriptor_waits_then_acquires_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = await recovery_inputs(tmp_path, monkeypatch)
    prior = AsyncMock(side_effect=[datetime.now(UTC) + timedelta(seconds=10), None])
    monkeypatch.setattr(module, "prior_live_deadline", prior)
    monkeypatch.setattr(module, "wait_prior", AsyncMock())
    monkeypatch.setattr(module, "require_current_credential", AsyncMock())
    result = await module.recover_notification_lease(
        value.services, value.scope, value.guard.witness, value.guard, value.command
    )
    assert result == value.lease and prior.await_count == 2 and value.recover.await_count == 1
    value.release.assert_not_awaited()


async def test_permanent_preflight_failure_never_acquires_or_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = await recovery_inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(
        module,
        "prior_live_deadline",
        AsyncMock(side_effect=ExecutionDeniedError("exact prior denied")),
    )
    with pytest.raises(ExecutionDeniedError):
        await module.recover_notification_lease(
            value.services, value.scope, value.guard.witness, value.guard, value.command
        )
    value.recover.assert_not_awaited()


@pytest.mark.parametrize("failure", [ValueError("expired"), asyncio.CancelledError()])
async def test_newly_acquired_lease_is_released_if_final_credential_or_cancellation_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: BaseException,
) -> None:
    value = await recovery_inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(module, "prior_live_deadline", AsyncMock(return_value=None))
    monkeypatch.setattr(module, "require_current_credential", AsyncMock(side_effect=failure))
    with pytest.raises(type(failure)):
        await module.recover_notification_lease(
            value.services, value.scope, value.guard.witness, value.guard, value.command
        )
    value.release.assert_awaited_once_with(value.lease, value.guard.witness.identity)


async def test_total_wait_is_bounded_without_effect_or_acquisition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = await recovery_inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(module, "MAX_ACQUISITION_SECONDS", 0.01)
    monkeypatch.setattr(
        module,
        "prior_live_deadline",
        AsyncMock(return_value=datetime.now(UTC) + timedelta(seconds=10)),
    )
    with pytest.raises(ExecutionDeniedError, match="bounded acquisition"):
        await module.recover_notification_lease(
            value.services, value.scope, value.guard.witness, value.guard, value.command
        )
    value.recover.assert_not_awaited()


async def test_internal_database_timeout_is_not_the_total_wait_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = await recovery_inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(
        module, "prior_live_deadline", AsyncMock(side_effect=TimeoutError("database"))
    )
    with pytest.raises(TimeoutError, match="database"):
        await module.recover_notification_lease(
            value.services, value.scope, value.guard.witness, value.guard, value.command
        )
    value.recover.assert_not_awaited()


@pytest.mark.parametrize("expired", [False, True])
async def test_outer_preflight_uses_qualified_final_clock_without_a_later_awaited_clock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, expired: bool
) -> None:
    value = await recovery_inputs(tmp_path, monkeypatch)
    final = value.guard.witness.expires_at if expired else datetime.now(UTC)
    work = ExecutionWork(
        worker_id=value.services.worker_id,
        segment_id=value.command.segment_id,
        lease_until=final + timedelta(seconds=30),
    )
    control = CompanyControl(owner_id=value.command.actor_id)

    @asynccontextmanager
    async def transaction(
        *args: object, **kwargs: object
    ) -> AsyncIterator[tuple[AsyncSession, CompanyControl, object]]:
        yield MagicMock(spec=AsyncSession), control, None

    monkeypatch.setattr(module, "runtime_transaction", transaction)
    monkeypatch.setattr(module, "execution_row", AsyncMock(return_value=work))
    monkeypatch.setattr(module, "dispatched_binding", AsyncMock(return_value=value.command))
    # Admission's own current-window checks are tested separately; this nominates
    # the outer operation's actual final returned-clock seam without native SQL.
    monkeypatch.setattr(module, "require_wait_admission", AsyncMock(return_value=final))
    later_clock = AsyncMock(side_effect=AssertionError("unqualified later clock"))
    monkeypatch.setattr(module, "db_now", later_clock)
    if expired:
        with pytest.raises(ValueError):
            await module.prior_live_deadline(
                value.services, value.scope, value.guard.witness, value.guard, value.command
            )
    else:
        assert (
            await module.prior_live_deadline(
                value.services, value.scope, value.guard.witness, value.guard, value.command
            )
            == work.lease_until
        )
    later_clock.assert_not_awaited()

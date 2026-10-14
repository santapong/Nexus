"""Mocked native read ordering only; real SQL/source and process proof remain separate."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.builder import native_state as module
from nexus.builder.contained_spawn_window import SpawnWindow
from nexus.builder.source_guard import BuilderSourceGuard
from nexus.company.access import VerifiedIdentity
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CompanyControl
from nexus.tests.builder_support import described_binding, described_job


@pytest.mark.parametrize("requested", [False, True])
@pytest.mark.parametrize("fault", [None, "expired", "intent"])
async def test_source_window_is_anchored_before_actual_final_clock_and_default_stays_none(
    monkeypatch: pytest.MonkeyPatch,
    requested: bool,
    fault: str | None,
) -> None:
    job = described_job()
    action, lease, _ = described_binding(job)
    now = datetime.now(UTC)
    lease = lease.model_copy(update={"expires_at": now + timedelta(seconds=10)})
    identity = VerifiedIdentity(principal_id=job.actor_id, workspace_id=job.workspace_id)
    order: list[str] = []
    session = MagicMock(spec=AsyncSession)
    session.get = AsyncMock(
        return_value=SimpleNamespace(
            state="outcome_unknown" if fault == "intent" else "intent",
            intent_fence=lease.fence,
            run_id=lease.run_id,
            proposal_hash=action_hash(action),
        )
    )

    def validate_time(actual: datetime) -> None:
        order.append("validate_time")
        if fault == "expired":
            raise ValueError("source expired")

    guard = cast(
        BuilderSourceGuard,
        SimpleNamespace(
            validate=AsyncMock(side_effect=lambda *a: order.append("source")),
            validate_time=validate_time,
            deadlines=(lease.expires_at,),
        ),
    )

    @asynccontextmanager
    async def transaction(
        *args: object, **kwargs: object
    ) -> AsyncIterator[tuple[AsyncSession, CompanyControl, None]]:
        yield session, CompanyControl(), None
        order.append("transaction_exit")

    async def db_clock(actual: AsyncSession) -> datetime:
        order.append("db_clock")
        return now

    def mono() -> int:
        order.append("monotonic_anchor")
        return 1_000_000

    monkeypatch.setattr(module, "runtime_transaction", transaction)
    monkeypatch.setattr(
        module, "execution_row", AsyncMock(return_value=SimpleNamespace(company_id=job.company_id))
    )
    monkeypatch.setattr(module, "require_lease", lambda *a, **k: None)
    monkeypatch.setattr(module, "require_effect_authority", AsyncMock(return_value=object()))
    monkeypatch.setattr(module, "db_now", db_clock)
    monkeypatch.setattr(module, "clock_us", mono)
    factory = MagicMock()
    if fault is not None:
        with pytest.raises(ValueError):
            await module.current_source(
                factory,
                lease,
                identity,
                action,
                guard,
                issued=True,
                operation_end_us=9_000_000 if requested else None,
            )
        if fault == "intent":
            assert "source" not in order and "monotonic_anchor" not in order
        return
    result = await module.current_source(
        factory,
        lease,
        identity,
        action,
        guard,
        issued=True,
        operation_end_us=9_000_000 if requested else None,
    )
    assert order[-1] == "transaction_exit"
    if requested:
        assert isinstance(result, SpawnWindow)
        assert order.index("monotonic_anchor") < len(order) - 3
        assert order[-4:-1] == ["monotonic_anchor", "db_clock", "validate_time"]
        assert result.end_us == 9_000_000
    else:
        assert result is None
        assert "monotonic_anchor" not in order

"""Independent declared-price expiry after the M1 hook but before the final managed intent."""

from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx2
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import nexus.execution.effect_store as effects
import nexus.tests.integration.test_company_managed_model as gateway
from nexus.execution.management_checks import require_management_execution
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.harness.journal_models import CostHold
from nexus.harness.model_authorizer import PersistentModelCallAuthorizer
from nexus.harness.model_intent import ModelIntentCheck
from nexus.tests.integration.test_company_directory import COMPANY
from nexus.tests.integration.test_company_managed_model import (
    managed_model_factory as managed_model_factory,
)


async def test_declared_price_expiring_after_managed_checks_issues_no_wire(
    managed_model_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}
    wires: list[datetime] = []
    real_validate = ModelIntentCheck.validate
    real_managed = require_management_execution
    real_transport = httpx2.MockTransport

    async def validate_short_price(self: ModelIntentCheck, *args: Any, **kwargs: Any) -> None:
        # Declare one immutable shortened validity before the real first price/quote check.
        deadline = observed.setdefault("deadline", datetime.now(UTC) + timedelta(seconds=0.3))
        models = tuple(
            model.model_copy(
                update={"price": model.price.model_copy(update={"valid_until": deadline})}
            )
            if model.price
            else model
            for model in self.registry.models
        )
        self.registry = self.registry.model_copy(update={"models": models})
        await real_validate(self, *args, **kwargs)
        observed["price_check_passed"] = True

    async def delayed_managed(session: AsyncSession, *args: Any, **kwargs: Any) -> None:
        await real_managed(session, *args, **kwargs)
        await session.execute(select(func.pg_sleep(0.6)))
        observed["managed_delay_finished"] = True

    def capture_transport(
        handler: Callable[[httpx2.Request], httpx2.Response],
    ) -> httpx2.MockTransport:
        def captured(wire: httpx2.Request) -> httpx2.Response:
            wires.append(datetime.now(UTC))
            return handler(wire)

        return real_transport(captured)

    monkeypatch.setattr(ModelIntentCheck, "validate", validate_short_price)
    monkeypatch.setattr(effects, "require_management_execution", delayed_managed)
    monkeypatch.setattr(gateway, "DiagnosticAuthorizer", PersistentModelCallAuthorizer)
    monkeypatch.setattr(httpx2, "MockTransport", capture_transport)
    # The root positive helper expects a response; retain real initial-check/delay proof.
    with suppress(AssertionError):
        await gateway.test_managed_gateway_preserves_current_plan_and_m1_one_request_boundary(
            managed_model_factory, tmp_path, "configured"
        )
    assert observed.get("price_check_passed") is True
    assert observed.get("managed_delay_finished") is True
    async with managed_model_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.scalar(select(func.count()).select_from(EffectIntent)) == 0
        work = (await session.scalars(select(ExecutionWork))).all()
        assert all(row.model_requests_used == 0 for row in work)
        holds = (await session.scalars(select(CostHold))).all()
        assert len(holds) == 1 and holds[0].state == "held" and holds[0].actual_usd is None
    assert not wires, f"Wire issued at {wires} after declared price expiry {observed['deadline']}"

"""Final transition clock follows actual owner membership; supplied observations are not permits."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, patch

import pytest

from nexus.company.access import CompanyControlScope
from nexus.company.brain.scope_support import require_brain_scope
from nexus.company.management.strategy_transition import finish_transition_locked
from nexus.company.management.strategy_transition_observation import StrategyTransitionObservation
from nexus.company.notifications.worker_identity import WorkerIdentityDeniedError
from nexus.tests.unit.strategy_current_proof_fixture import proof_case


async def test_original_credential_expiring_in_last_owner_await_is_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = proof_case(monkeypatch)
    proof = (
        await case.read()
    )  # Real current proof reader over the existing native mocked SQL fixture.
    assert proof.acceptance == case.record
    now = case.base.source.clock["now"]
    assert now < case.credential.expires_at
    calls: list[str] = []

    class Observation:
        # This narrow object is an orchestration observation, never fed to the authority reader.
        admission = SimpleNamespace(window=SimpleNamespace(require_same_scope=lambda other: None))

        def require_same_proof(self, other: object) -> None:
            calls.append("same-proof")

        def require_time(self, instant: datetime) -> None:
            calls.append("time")
            case.credential.require_time(instant)

    async def membership(*args: object, **kwargs: object) -> object:
        result = await require_brain_scope(*args, **kwargs)  # type: ignore[arg-type]
        calls.append("membership")
        # Delegate actual membership; nominate the final clock in this mocked SQL boundary test.
        case.base.source.clock["now"] = case.credential.expires_at + timedelta(microseconds=1)
        return result

    scope = CompanyControlScope(
        company_id=case.scope.company_id,
        principal_id=case.scope.principal_id,
        operation_id=case.scope.operation_id,
        trace_id=case.scope.trace_id,
    )
    with (
        patch(
            "nexus.company.management.strategy_transition.require_brain_scope",
            AsyncMock(side_effect=membership),
        ),
        patch(
            "nexus.company.management.strategy_transition.db_clock",
            AsyncMock(side_effect=lambda session: case.base.source.clock["now"]),
        ),
        pytest.raises(WorkerIdentityDeniedError),
    ):
        await finish_transition_locked(
            case.session,
            case.base.source.control,
            scope,
            case.credential.identity,
            cast(StrategyTransitionObservation, Observation()),
            cast(StrategyTransitionObservation, Observation()),
        )
    assert calls == ["same-proof", "membership", "time"]

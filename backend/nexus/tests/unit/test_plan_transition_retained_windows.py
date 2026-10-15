"""Final owner await retains both supplied full-plan windows; actual SQL is separate."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from nexus.company.access import CompanyControlScope
from nexus.company.management.strategy_transition import finish_transition_locked
from nexus.company.management.transactions import ManagementDeniedError
from nexus.tests.unit.strategy_transition_observation_fixture import transition_case


@pytest.mark.parametrize("which", ["first", "current"])
async def test_final_clock_checks_both_original_and_current_full_plan_expiry(which: str) -> None:
    case = transition_case()
    first = case.expiring("plan") if which == "first" else case.observation
    current = case.expiring("plan") if which == "current" else case.observation
    now = case.now
    first.require_time(now)
    current.require_time(now)
    scope = CompanyControlScope(
        company_id=case.payload.company_id,
        principal_id=case.proof.initial.sources.credential.identity.principal_id,
        operation_id=UUID(int=990),
        trace_id=UUID(int=991),
    )
    later = (
        first.admission.window.grants[0].expires_at
        if which == "first"
        else current.admission.window.grants[0].expires_at
    )
    assert later is not None
    calls: list[str] = []

    async def membership(*args: object, **kwargs: object) -> object:
        calls.append("membership")
        return object()

    async def clock(*args: object) -> object:
        calls.append("clock")
        return later

    with (
        patch(
            "nexus.company.management.strategy_transition.require_brain_scope",
            AsyncMock(side_effect=membership),
        ),
        patch(
            "nexus.company.management.strategy_transition.db_clock", AsyncMock(side_effect=clock)
        ),
        pytest.raises(ManagementDeniedError),
    ):
        await finish_transition_locked(
            MagicMock(),
            MagicMock(),
            scope,
            case.proof.initial.sources.credential.identity,
            first,
            current,
        )
    assert calls == ["membership", "clock"]

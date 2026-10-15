"""The current configured strategy DB connection must actually enforce company RLS."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.management.acceptance_errors import AcceptanceDeniedError
from nexus.company.strategy.application_role import require_strategy_application_role


@pytest.mark.parametrize("privileged", [True, None, 0, 1, "false"])
async def test_missing_or_privileged_database_role_is_not_literal_restricted_false(
    privileged: object,
) -> None:
    session = MagicMock(spec=AsyncSession)
    session.in_transaction.return_value = True
    session.scalar = AsyncMock(return_value=privileged)
    with pytest.raises(AcceptanceDeniedError):
        await require_strategy_application_role(session)


async def test_actual_restricted_role_query_is_same_session_and_read_only() -> None:
    session = MagicMock(spec=AsyncSession)
    session.in_transaction.return_value = True
    session.scalar = AsyncMock(return_value=False)
    await require_strategy_application_role(session)
    statement = session.scalar.await_args.args[0]
    assert "current_user" in str(statement) and "rolsuper OR rolbypassrls" in str(statement)
    session.commit.assert_not_called()


async def test_role_gate_cannot_run_outside_the_callers_transaction() -> None:
    session = MagicMock(spec=AsyncSession)
    session.in_transaction.return_value = False
    session.scalar = AsyncMock(return_value=False)
    with pytest.raises(AcceptanceDeniedError):
        await require_strategy_application_role(session)
    session.scalar.assert_not_awaited()

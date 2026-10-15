"""Privileged current-session role must deny before concrete protected strategy materialization."""

from unittest.mock import AsyncMock

import pytest

from nexus.tests.unit.strategy_publication_reader_fixture import reader_case


async def test_concrete_original_reader_denies_actual_privileged_session_role_before_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = reader_case(monkeypatch)
    case.source.session.scalar = AsyncMock(return_value=True)
    with pytest.raises(ValueError):
        await case.reader.load_original_locked(
            case.source.session,
            case.source.control,
            case.source.scope,
            case.source.credential.identity,
            case.prepared.action_id,
            credential=case.source.credential,
        )
    case.row_get.assert_not_awaited()
    case.source.session.scalar.assert_awaited_once()
    query = str(case.source.session.scalar.await_args.args[0])
    assert "pg_roles" in query and "current_user" in query

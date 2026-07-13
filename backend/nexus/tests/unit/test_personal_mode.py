"""Tests for PERSONAL_MODE workspace resolution and the "Co" persona seed.

ADR-087: in personal mode, unauthenticated requests fall back to the single
owner workspace; a valid JWT workspace claim always wins; with the flag off
behavior is identical to before (401 for anonymous callers).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from litestar.exceptions import NotAuthorizedException

from nexus.api.auth import (
    create_access_token,
    reset_personal_workspace_cache,
    resolve_workspace_id,
)
from nexus.settings import settings


@pytest.fixture(autouse=True)
def _jwt_secret_and_cache_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        settings,
        "jwt_secret_key",
        "test-secret-key-with-at-least-32-bytes-of-length",
    )
    reset_personal_workspace_cache()


def _make_request(authorization_header: str | None = None) -> MagicMock:
    request = MagicMock()
    headers: dict[str, str] = {}
    if authorization_header is not None:
        headers["authorization"] = authorization_header
    request.headers.get.side_effect = lambda key, default="": headers.get(key.lower(), default)
    return request


def _make_db_session(workspace_id: str | None) -> AsyncMock:
    """DB session whose workspace-by-slug lookup returns a row or None."""
    session = AsyncMock()
    result = MagicMock()
    if workspace_id is None:
        result.scalar_one_or_none.return_value = None
    else:
        workspace = MagicMock()
        workspace.id = workspace_id
        result.scalar_one_or_none.return_value = workspace
    session.execute.return_value = result
    return session


@pytest.mark.asyncio
async def test_jwt_claim_wins_even_in_personal_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "personal_mode", True)
    token = create_access_token(user_id="u1", workspace_id="ws-jwt", email="o@x.io")
    db = _make_db_session("ws-personal")

    resolved = await resolve_workspace_id(_make_request(f"Bearer {token}"), db)

    assert resolved == "ws-jwt"
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_anonymous_401_when_personal_mode_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "personal_mode", False)
    db = _make_db_session("ws-personal")

    with pytest.raises(NotAuthorizedException):
        await resolve_workspace_id(_make_request(None), db)
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_personal_mode_falls_back_to_owner_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "personal_mode", True)
    db = _make_db_session("ws-personal")

    resolved = await resolve_workspace_id(_make_request(None), db)

    assert resolved == "ws-personal"


@pytest.mark.asyncio
async def test_personal_mode_caches_workspace_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "personal_mode", True)
    db = _make_db_session("ws-personal")

    first = await resolve_workspace_id(_make_request(None), db)
    second = await resolve_workspace_id(_make_request(None), db)

    assert first == second == "ws-personal"
    assert db.execute.await_count == 1  # second call served from cache


@pytest.mark.asyncio
async def test_personal_mode_401_when_workspace_not_seeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "personal_mode", True)
    db = _make_db_session(None)

    with pytest.raises(NotAuthorizedException):
        await resolve_workspace_id(_make_request(None), db)


# ─── Co persona seed ─────────────────────────────────────────────────────────


def test_co_prompt_preserves_decomposition_contract() -> None:
    """CEOAgent._decompose_task parses a JSON array with role/instruction/
    depends_on — the Co persona prompt must keep that contract intact."""
    from nexus.db.seed import CO_SYSTEM_PROMPT

    assert "JSON array" in CO_SYSTEM_PROMPT
    for key in ('"role"', '"instruction"', '"depends_on"'):
        assert key in CO_SYSTEM_PROMPT
    for role in ("engineer", "analyst", "writer"):
        assert role in CO_SYSTEM_PROMPT
    assert "Co" in CO_SYSTEM_PROMPT


class _FakeSeedSession:
    """Dispatches the three queries _seed_co_persona makes, in order:
    (1) CEO prompt v2 lookup, (2) other active CEO prompts, (3) agent rows."""

    def __init__(
        self,
        *,
        existing_v2: Any,
        other_active_prompts: list[Any],
        agent_rows: list[Any],
    ) -> None:
        self._results = [existing_v2, other_active_prompts, agent_rows]
        self._call = 0
        self.added: list[Any] = []

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def execute(self, _stmt: Any) -> MagicMock:
        payload = self._results[self._call]
        self._call += 1
        result = MagicMock()
        if isinstance(payload, list):
            result.scalars.return_value.all.return_value = payload
        else:
            result.scalar_one_or_none.return_value = payload
        return result


@pytest.mark.asyncio
async def test_seed_co_persona_creates_v2_and_rebrands_agent() -> None:
    from nexus.db.seed import CO_SYSTEM_PROMPT, _seed_co_persona

    v1 = MagicMock(version=1, is_active=True)
    agent = MagicMock()
    session = _FakeSeedSession(existing_v2=None, other_active_prompts=[v1], agent_rows=[agent])

    await _seed_co_persona(session)  # type: ignore[arg-type]

    assert len(session.added) == 1  # v2 prompt inserted
    added = session.added[0]
    assert added.agent_role == "ceo"
    assert added.version == 2
    assert added.is_active is True
    assert added.content == CO_SYSTEM_PROMPT
    assert v1.is_active is False  # old version deactivated
    assert agent.system_prompt == CO_SYSTEM_PROMPT
    assert agent.name == "Co"


@pytest.mark.asyncio
async def test_seed_co_persona_is_idempotent_when_v2_exists() -> None:
    from nexus.db.seed import CO_SYSTEM_PROMPT, _seed_co_persona

    existing_v2 = MagicMock(version=2, is_active=True)
    agent = MagicMock()
    session = _FakeSeedSession(existing_v2=existing_v2, other_active_prompts=[], agent_rows=[agent])

    await _seed_co_persona(session)  # type: ignore[arg-type]

    assert session.added == []  # nothing re-inserted
    assert agent.name == "Co"
    assert agent.system_prompt == CO_SYSTEM_PROMPT

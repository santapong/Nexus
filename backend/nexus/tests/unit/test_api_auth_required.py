"""Verify anonymous callers cannot reach workspace-scoped endpoints.

Tasks, approvals, and workspace endpoints previously fell through to a
"no workspace_id filter" branch when JWT was absent, leaking data across
tenants. These tests prove `require_auth_user` now raises 401 instead.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from litestar.exceptions import NotAuthorizedException


@pytest.fixture(autouse=True)
def _set_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure JWT signing has a key long enough for HS256."""
    from nexus.settings import settings

    monkeypatch.setattr(
        settings,
        "jwt_secret_key",
        "test-secret-key-with-at-least-32-bytes-of-length",
    )


def _make_request(authorization_header: str | None = None) -> MagicMock:
    """Build a minimal MagicMock request with controllable auth header."""
    request = MagicMock()
    headers: dict[str, str] = {}
    if authorization_header is not None:
        headers["authorization"] = authorization_header
    request.headers.get.side_effect = lambda key, default="": headers.get(
        key.lower(), default
    )
    return request


def test_require_auth_user_raises_when_header_missing() -> None:
    from nexus.api.auth import require_auth_user

    request = _make_request(authorization_header=None)
    with pytest.raises(NotAuthorizedException):
        require_auth_user(request)


def test_require_auth_user_raises_on_malformed_header() -> None:
    from nexus.api.auth import require_auth_user

    request = _make_request(authorization_header="Basic abc123")
    with pytest.raises(NotAuthorizedException):
        require_auth_user(request)


def test_require_auth_user_raises_on_invalid_token() -> None:
    from nexus.api.auth import require_auth_user

    request = _make_request(authorization_header="Bearer not.a.real.jwt")
    with pytest.raises(NotAuthorizedException):
        require_auth_user(request)


def test_require_auth_user_returns_user_on_valid_token() -> None:
    from nexus.api.auth import create_access_token, require_auth_user

    token = create_access_token(
        user_id="user-1",
        workspace_id="ws-1",
        email="alice@example.com",
    )
    request = _make_request(authorization_header=f"Bearer {token}")
    user = require_auth_user(request)
    assert user.user_id == "user-1"
    assert user.workspace_id == "ws-1"
    assert user.email == "alice@example.com"


def test_tasks_require_workspace_id_raises_when_anonymous() -> None:
    """Tasks list/get/create must refuse anonymous callers.

    Previously the endpoint silently returned tasks across all workspaces
    when no JWT was present.
    """
    from nexus.api.tasks import _require_workspace_id

    request = _make_request(authorization_header=None)
    with pytest.raises(NotAuthorizedException):
        _require_workspace_id(request)


def test_tasks_require_workspace_id_raises_on_token_without_workspace() -> None:
    """A JWT with an empty workspace_id claim is still 401, not all-tenant."""
    from nexus.api.auth import create_access_token
    from nexus.api.tasks import _require_workspace_id

    token = create_access_token(
        user_id="user-1",
        workspace_id="",  # malformed token (no workspace assigned)
        email="alice@example.com",
    )
    request = _make_request(authorization_header=f"Bearer {token}")
    with pytest.raises(NotAuthorizedException):
        _require_workspace_id(request)

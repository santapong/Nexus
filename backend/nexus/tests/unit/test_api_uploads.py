"""Unit tests for the uploads endpoint (ADR-089).

Uses a real Litestar test client for the multipart round trip — this
deliberately proves that Litestar's native multipart parsing works for the
endpoint (no extra dependency needed) — with the DB session and workspace
resolution mocked out.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from litestar import Litestar
from litestar.di import Provide
from litestar.testing import TestClient

from nexus.api.uploads import AttachmentRef, UploadController, _storage_path_for
from nexus.settings import settings


def _make_fake_session() -> MagicMock:
    """AsyncSession-spec'd mock that assigns ids on flush, like the ORM.

    Litestar validates injected dependencies against the handler's type
    annotation, so the mock must pass isinstance(x, AsyncSession) — a
    spec'd MagicMock does via __class__ spoofing.
    """
    from sqlalchemy.ext.asyncio import AsyncSession

    session = MagicMock(spec=AsyncSession)
    session.added = []
    session.committed = False
    session.add = MagicMock(side_effect=session.added.append)

    async def _flush() -> None:
        for obj in session.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid4()

    async def _commit() -> None:
        session.committed = True

    session.flush = AsyncMock(side_effect=_flush)
    session.commit = AsyncMock(side_effect=_commit)
    return session


@pytest.fixture()
def upload_client(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> tuple[TestClient[Litestar], MagicMock]:
    monkeypatch.setattr(settings, "upload_storage_path", str(tmp_path))

    fake_session = _make_fake_session()

    async def _fake_resolve(request: Any, db_session: Any) -> str:
        return "ws-owner"

    monkeypatch.setattr("nexus.api.uploads.resolve_workspace_id", _fake_resolve)

    async def _provide_session() -> MagicMock:
        return fake_session

    app = Litestar(
        route_handlers=[UploadController],
        dependencies={"db_session": Provide(_provide_session)},
    )
    return TestClient(app=app), fake_session


def test_upload_txt_parses_and_persists(
    upload_client: tuple[TestClient[Litestar], MagicMock],
) -> None:
    client, fake_session = upload_client

    with client:
        response = client.post(
            "/uploads",
            files={"data": ("notes.txt", b"meeting notes: buy milk", "text/plain")},
        )

    assert response.status_code == 201, response.text
    body = response.json()
    ref = AttachmentRef(**body)
    assert ref.filename == "notes.txt"
    assert ref.parse_status == "parsed"
    assert ref.size_bytes == len(b"meeting notes: buy milk")

    assert fake_session.committed
    attachment = fake_session.added[0]
    assert attachment.workspace_id == "ws-owner"
    assert attachment.task_id is None
    assert attachment.parsed_text == "meeting notes: buy milk"
    # Raw bytes stored under {workspace}/{attachment_id} — id-keyed path.
    assert attachment.storage_path.endswith(str(attachment.id))


def test_upload_rejects_empty_file(
    upload_client: tuple[TestClient[Litestar], MagicMock],
) -> None:
    client, _ = upload_client
    with client:
        response = client.post("/uploads", files={"data": ("empty.txt", b"", "text/plain")})
    assert response.status_code == 400


def test_upload_rejects_oversize_file(
    upload_client: tuple[TestClient[Litestar], MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = upload_client
    monkeypatch.setattr(settings, "upload_max_bytes", 10)
    with client:
        response = client.post("/uploads", files={"data": ("big.txt", b"x" * 11, "text/plain")})
    assert response.status_code == 400


def test_upload_unsupported_type_is_stored_with_status(
    upload_client: tuple[TestClient[Litestar], MagicMock],
) -> None:
    client, fake_session = upload_client
    with client:
        response = client.post(
            "/uploads", files={"data": ("archive.zip", b"PK\x03\x04", "application/zip")}
        )
    assert response.status_code == 201
    assert response.json()["parse_status"] == "unsupported"
    assert fake_session.added[0].parsed_text is None


def test_storage_path_ignores_user_filename() -> None:
    """Paths are keyed by server ids only — filename can't traverse."""
    path = _storage_path_for("ws-1", "att-1")
    assert path.parts[-2:] == ("ws-1", "att-1")


def test_upload_401_when_unauthenticated_and_personal_mode_off(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "upload_storage_path", str(tmp_path))
    monkeypatch.setattr(settings, "personal_mode", False)

    fake_session = _make_fake_session()

    async def _provide_session() -> MagicMock:
        return fake_session

    app = Litestar(
        route_handlers=[UploadController],
        dependencies={"db_session": Provide(_provide_session)},
    )
    with TestClient(app=app) as client:
        response = client.post("/uploads", files={"data": ("notes.txt", b"hi", "text/plain")})
    assert response.status_code == 401

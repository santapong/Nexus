"""Unit tests for the VoiceFactory and voice endpoints (ADR-088)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from litestar import Litestar
from litestar.di import Provide
from litestar.testing import TestClient

from nexus.api.voice import VoiceController
from nexus.core.voice import (
    BrowserBackendIsClientSideError,
    VoiceBackendNotImplementedError,
    get_stt_provider,
    get_tts_provider,
)
from nexus.settings import settings

# ─── Factory resolution ──────────────────────────────────────────────────────


def test_browser_stt_is_client_side_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "voice_stt_backend", "browser")
    with pytest.raises(BrowserBackendIsClientSideError):
        get_stt_provider()


def test_browser_tts_is_client_side_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "voice_tts_backend", "browser")
    with pytest.raises(BrowserBackendIsClientSideError):
        get_tts_provider()


def test_known_future_backends_raise_not_implemented() -> None:
    with pytest.raises(VoiceBackendNotImplementedError):
        get_stt_provider("whisper")
    with pytest.raises(VoiceBackendNotImplementedError):
        get_tts_provider("elevenlabs")
    with pytest.raises(VoiceBackendNotImplementedError):
        get_tts_provider("piper")


def test_unknown_backend_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Unknown STT backend"):
        get_stt_provider("carrier-pigeon")
    with pytest.raises(ValueError, match="Unknown TTS backend"):
        get_tts_provider("carrier-pigeon")


def test_override_beats_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "voice_stt_backend", "browser")
    with pytest.raises(VoiceBackendNotImplementedError):
        get_stt_provider("deepgram")


# ─── Endpoints — API contract frozen for Phase C ─────────────────────────────


@pytest.fixture()
def voice_client(monkeypatch: pytest.MonkeyPatch) -> TestClient[Litestar]:
    async def _fake_resolve(request: Any, db_session: Any) -> str:
        return "ws-owner"

    monkeypatch.setattr("nexus.api.voice.resolve_workspace_id", _fake_resolve)

    from sqlalchemy.ext.asyncio import AsyncSession

    async def _provide_session() -> MagicMock:
        return MagicMock(spec=AsyncSession)

    app = Litestar(
        route_handlers=[VoiceController],
        dependencies={"db_session": Provide(_provide_session)},
    )
    return TestClient(app=app)


def test_transcribe_501_for_browser_backend(
    voice_client: TestClient[Litestar], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "voice_stt_backend", "browser")
    with voice_client as client:
        response = client.post(
            "/voice/transcribe", files={"data": ("clip.webm", b"\x1aE", "audio/webm")}
        )
    assert response.status_code == 501
    assert "client-side" in response.json()["detail"]


def test_speak_501_for_browser_backend(
    voice_client: TestClient[Litestar], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "voice_tts_backend", "browser")
    with voice_client as client:
        response = client.post("/voice/speak", json={"text": "hello"})
    assert response.status_code == 501


def test_speak_501_for_unimplemented_backend(
    voice_client: TestClient[Litestar], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "voice_tts_backend", "elevenlabs")
    with voice_client as client:
        response = client.post("/voice/speak", json={"text": "hello"})
    assert response.status_code == 501
    assert "not implemented" in response.json()["detail"]


def test_speak_400_for_unknown_backend(
    voice_client: TestClient[Litestar], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "voice_tts_backend", "carrier-pigeon")
    with voice_client as client:
        response = client.post("/voice/speak", json={"text": "hello"})
    assert response.status_code == 400

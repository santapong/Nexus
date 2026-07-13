"""Voice endpoints — server-side STT/TTS for non-browser backends (ADR-088).

The API contract is frozen for Phase C: POST /api/voice/transcribe and
POST /api/voice/speak. With the default `browser` backend these return 501
with a hint that the work happens client-side; cloud/local providers drop
into the VoiceFactory later without any route changes.
"""

from __future__ import annotations

from typing import Annotated, Any

import structlog
from litestar import Controller, Request, post
from litestar.datastructures import UploadFile
from litestar.enums import RequestEncodingType
from litestar.exceptions import ClientException, HTTPException
from litestar.params import Body
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.api.auth import resolve_workspace_id
from nexus.core.voice import (
    BrowserBackendIsClientSideError,
    VoiceBackendNotImplementedError,
    get_stt_provider,
    get_tts_provider,
)

logger = structlog.get_logger()


class TranscribeResponse(BaseModel):
    text: str


class SpeakRequest(BaseModel):
    text: str


class VoiceController(Controller):
    path = "/voice"

    @post("/transcribe")
    async def transcribe(
        self,
        data: Annotated[UploadFile, Body(media_type=RequestEncodingType.MULTI_PART)],
        request: Request[Any, Any, Any],
        db_session: AsyncSession,
    ) -> TranscribeResponse:
        """Transcribe uploaded audio to text (non-browser backends only)."""
        await resolve_workspace_id(request, db_session)
        try:
            provider = get_stt_provider()
        except BrowserBackendIsClientSideError as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc
        except VoiceBackendNotImplementedError as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc
        except ValueError as exc:
            raise ClientException(detail=str(exc)) from exc

        audio = await data.read()
        text = await provider.transcribe(
            audio, mime_type=data.content_type or "application/octet-stream"
        )
        return TranscribeResponse(text=text)

    @post("/speak")
    async def speak(
        self,
        data: SpeakRequest,
        request: Request[Any, Any, Any],
        db_session: AsyncSession,
    ) -> dict[str, str]:
        """Synthesize text to audio (non-browser backends only)."""
        await resolve_workspace_id(request, db_session)
        try:
            get_tts_provider()
        except BrowserBackendIsClientSideError as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc
        except VoiceBackendNotImplementedError as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc
        except ValueError as exc:
            raise ClientException(detail=str(exc)) from exc

        # Unreachable in MVP-1 (no server-side provider ships yet); Phase C
        # returns audio bytes here.
        return {"detail": "TTS provider resolved"}

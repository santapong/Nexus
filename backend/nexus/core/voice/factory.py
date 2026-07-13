"""VoiceFactory — prefix-registry STT/TTS provider resolution (ADR-088).

Same shape as core/llm/factory.py: an ordered prefix registry maps backend
names to lazy resolver functions, so cloud (whisper/deepgram/elevenlabs/…)
and local (faster-whisper/piper) backends drop in later without touching
API routes or callers. MVP-1 ships only the `browser` marker backend.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

import structlog

from nexus.settings import settings

logger = structlog.get_logger()


class VoiceBackendNotImplementedError(Exception):
    """Raised for a known backend whose provider is not yet shipped."""


class BrowserBackendIsClientSideError(Exception):
    """The `browser` backend runs in the frontend (Web Speech API).

    Raised when server code asks for a provider while the browser backend
    is configured — the correct behavior is to tell the client to do the
    work locally (API responds 501 with that hint).
    """


class STTProvider(Protocol):
    """Speech-to-text provider contract."""

    async def transcribe(self, audio: bytes, *, mime_type: str) -> str:
        """Transcribe audio bytes to text."""
        ...


class TTSProvider(Protocol):
    """Text-to-speech provider contract."""

    async def synthesize(self, text: str) -> bytes:
        """Synthesize text to audio bytes (webm/opus unless noted)."""
        ...


def _resolve_browser_stt(_backend: str) -> STTProvider:
    raise BrowserBackendIsClientSideError(
        "voice backend 'browser' runs client-side via the Web Speech API; "
        "no server transcription call is needed"
    )


def _resolve_browser_tts(_backend: str) -> TTSProvider:
    raise BrowserBackendIsClientSideError(
        "voice backend 'browser' runs client-side via speechSynthesis; "
        "no server synthesis call is needed"
    )


def _stt_not_implemented(backend: str) -> STTProvider:
    raise VoiceBackendNotImplementedError(
        f"voice backend '{backend}' is planned (Phase C) but not implemented in MVP-1"
    )


def _tts_not_implemented(backend: str) -> TTSProvider:
    raise VoiceBackendNotImplementedError(
        f"voice backend '{backend}' is planned (Phase C) but not implemented in MVP-1"
    )


# Ordered prefix registries — first match wins (mirrors _PROVIDER_RESOLVERS
# in core/llm/factory.py). Phase C adds: whisper/deepgram STT;
# elevenlabs/openai/google TTS; faster-whisper/piper local.
_STT_RESOLVERS: list[tuple[str, Callable[[str], STTProvider]]] = [
    ("browser", _resolve_browser_stt),
    ("whisper", _stt_not_implemented),
    ("deepgram", _stt_not_implemented),
    ("faster-whisper", _stt_not_implemented),
]

_TTS_RESOLVERS: list[tuple[str, Callable[[str], TTSProvider]]] = [
    ("browser", _resolve_browser_tts),
    ("elevenlabs", _tts_not_implemented),
    ("openai", _tts_not_implemented),
    ("google", _tts_not_implemented),
    ("piper", _tts_not_implemented),
]


def get_stt_provider(override: str | None = None) -> STTProvider:
    """Resolve the configured speech-to-text provider.

    Args:
        override: Backend name overriding settings.voice_stt_backend.

    Returns:
        A provider implementing STTProvider.

    Raises:
        BrowserBackendIsClientSideError: Browser backend configured.
        VoiceBackendNotImplementedError: Known backend without a provider yet.
        ValueError: Unknown backend name.
    """
    backend = (override or settings.voice_stt_backend).strip().lower()
    for prefix, resolver in _STT_RESOLVERS:
        if backend.startswith(prefix):
            return resolver(backend)
    raise ValueError(f"Unknown STT backend: {backend}")


def get_tts_provider(override: str | None = None) -> TTSProvider:
    """Resolve the configured text-to-speech provider.

    Args:
        override: Backend name overriding settings.voice_tts_backend.

    Returns:
        A provider implementing TTSProvider.

    Raises:
        BrowserBackendIsClientSideError: Browser backend configured.
        VoiceBackendNotImplementedError: Known backend without a provider yet.
        ValueError: Unknown backend name.
    """
    backend = (override or settings.voice_tts_backend).strip().lower()
    for prefix, resolver in _TTS_RESOLVERS:
        if backend.startswith(prefix):
            return resolver(backend)
    raise ValueError(f"Unknown TTS backend: {backend}")

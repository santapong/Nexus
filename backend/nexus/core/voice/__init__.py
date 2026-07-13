"""Voice (STT/TTS) provider abstraction for the Co assistant (ADR-088).

Mirrors the LLM ModelFactory pattern: agent/API code never names a
concrete provider — backends are selected via settings.voice_stt_backend /
settings.voice_tts_backend. The default `browser` backend is an explicit
client-side marker (Web Speech API runs in the frontend; the server has
nothing to do).
"""

from nexus.core.voice.factory import (
    BrowserBackendIsClientSideError,
    STTProvider,
    TTSProvider,
    VoiceBackendNotImplementedError,
    get_stt_provider,
    get_tts_provider,
)

__all__ = [
    "BrowserBackendIsClientSideError",
    "STTProvider",
    "TTSProvider",
    "VoiceBackendNotImplementedError",
    "get_stt_provider",
    "get_tts_provider",
]

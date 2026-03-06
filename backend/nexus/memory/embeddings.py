from __future__ import annotations

import structlog
import httpx

from nexus.settings import settings

logger = structlog.get_logger()

# Google embedding-001 dimension
EMBEDDING_DIMENSION = 1536


async def generate_embedding(text: str) -> list[float] | None:
    """Generate an embedding using Google embedding-001 via Gemini API.

    Returns None on failure (embedding is non-blocking).
    """
    if not settings.google_api_key:
        logger.warning("embedding_skipped", reason="no_google_api_key")
        return None

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://generativelanguage.googleapis.com/v1/models/embedding-001:embedContent",
                params={"key": settings.google_api_key},
                json={
                    "model": "models/embedding-001",
                    "content": {"parts": [{"text": text}]},
                },
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()
            return data["embedding"]["values"]  # type: ignore[no-any-return]
    except Exception as exc:
        logger.error("embedding_generation_failed", error=str(exc))
        return None

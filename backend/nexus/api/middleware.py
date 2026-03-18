"""API rate limiting and request validation middleware.

Rate limits:
- Per-user (authenticated): 100 requests/minute
- Per-IP (unauthenticated): 20 requests/minute
- Task creation: 10/minute per user
"""

from __future__ import annotations

import re
import time

import structlog
from litestar import Request, Response
from litestar.middleware import AbstractMiddleware
from litestar.types import ASGIApp, Receive, Scope, Send
from pydantic import BaseModel

from nexus.core.redis.clients import redis_cache
from nexus.settings import settings

logger = structlog.get_logger()

_RATE_LIMITS = {
    "authenticated": 100,  # requests per minute
    "unauthenticated": 20,
    "task_create": 10,
}


async def check_api_rate_limit(identifier: str, limit: int) -> tuple[bool, int]:
    """Check rate limit for an API identifier.

    Args:
        identifier: Unique key (user_id or IP).
        limit: Max requests per minute.

    Returns:
        Tuple of (allowed, remaining).
    """
    window = int(time.time() // 60)
    key = f"ratelimit:api:{identifier}:{window}"
    try:
        current = await redis_cache.incr(key)
        if current == 1:
            await redis_cache.expire(key, 120)
        remaining = max(0, limit - current)
        return current <= limit, remaining
    except Exception as exc:
        logger.warning("api_rate_limit_check_failed", error=str(exc))
        return True, limit  # Allow on Redis failure


# ─── Prompt injection detection ──────────────────────────────────────────────

_MAX_INSTRUCTION_LENGTH = 10_000

_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore\s+(all\s+|any\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+", re.IGNORECASE),
    re.compile(r"(reveal|show|print|output)\s+(your\s+)?(system\s+prompt|instructions)", re.IGNORECASE),
    re.compile(r"<\|[^|]*\|>"),  # special token patterns
    re.compile(r"\[INST\]|\[/INST\]|<<SYS>>|<</SYS>>", re.IGNORECASE),  # Llama tokens
]


class InstructionValidationResult(BaseModel):
    """Result of task instruction validation."""

    valid: bool
    error: str | None = None


def validate_instruction(instruction: str) -> InstructionValidationResult:
    """Validate a task instruction for length and injection patterns.

    Args:
        instruction: The raw user instruction.

    Returns:
        Validation result with error message if invalid.
    """
    if not instruction or not instruction.strip():
        return InstructionValidationResult(valid=False, error="Instruction cannot be empty")

    if len(instruction) > _MAX_INSTRUCTION_LENGTH:
        return InstructionValidationResult(
            valid=False,
            error=f"Instruction too long ({len(instruction)} chars, max {_MAX_INSTRUCTION_LENGTH})",
        )

    for pattern in _INJECTION_PATTERNS:
        if pattern.search(instruction):
            logger.warning(
                "prompt_injection_detected",
                pattern=pattern.pattern[:50],
                instruction_preview=instruction[:100],
            )
            return InstructionValidationResult(
                valid=False,
                error="Instruction contains disallowed patterns",
            )

    return InstructionValidationResult(valid=True)


def sandbox_instruction(instruction: str) -> str:
    """Wrap user instruction with delimiters to prevent prompt injection.

    The system prompt instructs the LLM to treat content between these
    delimiters as user input only — not as system-level instructions.

    Args:
        instruction: Raw user instruction.

    Returns:
        Sandboxed instruction with clear delimiters.
    """
    return (
        "<user_instruction>\n"
        f"{instruction}\n"
        "</user_instruction>"
    )

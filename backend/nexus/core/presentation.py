"""Typed presentation output for the Co personal assistant (ADR-091).

The Director's synthesis emits a fenced JSON presentation block
({format, content, speech_text}); this module parses it (with a markdown
fallback that never fails) and sanitizes HTML server-side with nh3 before
it is published. The result consumer re-sanitizes at the choke point every
user-visible output passes through, so no future producer can ship
unsanitized markup to the dashboard (stored-XSS defense in depth).
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

import nh3
import structlog
from pydantic import BaseModel

logger = structlog.get_logger()

# Keep the whole presentation comfortably under AgentBase._MAX_OUTPUT_SIZE
# (100KB) so output validation never truncates mid-tag.
_MAX_CONTENT_CHARS = 60_000
_MAX_SPEECH_CHARS = 2_000

_ALLOWED_TAGS = {
    "p",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "ul",
    "ol",
    "li",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "strong",
    "em",
    "b",
    "i",
    "u",
    "s",
    "code",
    "pre",
    "a",
    "img",
    "div",
    "span",
    "blockquote",
    "hr",
    "br",
}

_ALLOWED_ATTRIBUTES = {
    "a": {"href", "title"},
    "img": {"src", "alt", "title", "width", "height"},
    "th": {"colspan", "rowspan"},
    "td": {"colspan", "rowspan"},
}

# https only — no javascript:, data:, or relative URLs in agent output.
_ALLOWED_URL_SCHEMES = {"https"}

_FENCED_JSON_RE = re.compile(
    r"```(?:json)?\s*(\{[^`]*\"format\"[^`]*\})\s*```",
    re.DOTALL,
)

_TAG_STRIP_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


class Presentation(BaseModel):
    """User-facing rich output attached to a task result."""

    format: Literal["html", "markdown", "mermaid"] = "markdown"
    content: str = ""
    speech_text: str = ""


def _derive_speech_text(text: str) -> str:
    """Plain-text summary for TTS: strip markup, collapse whitespace."""
    plain = _TAG_STRIP_RE.sub(" ", text)
    plain = plain.replace("#", " ").replace("*", " ").replace("|", " ").replace("`", " ")
    plain = _WHITESPACE_RE.sub(" ", plain).strip()
    return plain[:_MAX_SPEECH_CHARS]


def sanitize_presentation(raw: dict[str, Any] | Presentation) -> Presentation:
    """Validate + sanitize a presentation payload. Never raises.

    HTML content is cleaned with an allow-list (tags, attributes, https-only
    URLs; scripts/handlers/styles stripped). Markdown/mermaid are size-capped
    only — the frontend renders them escaped, never as raw HTML.
    """
    try:
        presentation = raw if isinstance(raw, Presentation) else Presentation(**raw)
    except Exception as exc:
        logger.warning("presentation_invalid_shape", error=str(exc))
        return Presentation(format="markdown", content="", speech_text="")

    content = presentation.content[:_MAX_CONTENT_CHARS]
    if presentation.format == "html":
        content = nh3.clean(
            content,
            tags=_ALLOWED_TAGS,
            attributes=_ALLOWED_ATTRIBUTES,
            url_schemes=_ALLOWED_URL_SCHEMES,
            link_rel="noopener noreferrer",
        )

    speech = presentation.speech_text.strip()[:_MAX_SPEECH_CHARS]
    if not speech:
        speech = _derive_speech_text(content)

    return Presentation(format=presentation.format, content=content, speech_text=speech)


def extract_presentation_from_llm_output(text: str) -> tuple[str, Presentation]:
    """Split an LLM synthesis into (clean_text, sanitized presentation).

    Looks for the fenced JSON presentation block the Director prompt
    requests. On any parse failure, falls back to wrapping the whole text
    as markdown with a derived speech_text — this function never fails.

    Returns:
        (text with the presentation block removed, sanitized Presentation)
    """
    match = _FENCED_JSON_RE.search(text)
    if match:
        try:
            payload = json.loads(match.group(1))
            clean_text = (text[: match.start()] + text[match.end() :]).strip()
            presentation = sanitize_presentation(payload)
            if presentation.content:
                if not clean_text:
                    clean_text = presentation.content
                return clean_text, presentation
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("presentation_block_parse_failed", error=str(exc))

    clean_text = text.strip()
    fallback = Presentation(
        format="markdown",
        content=clean_text[:_MAX_CONTENT_CHARS],
        speech_text=_derive_speech_text(clean_text[:600]),
    )
    return clean_text, sanitize_presentation(fallback)


# Prompt fragment the Director appends to its synthesis instructions.
PRESENTATION_PROMPT_INSTRUCTIONS = (
    "\n## Presentation output (required)\n"
    "After the synthesized output, append a fenced JSON block describing how "
    "to present the result to the owner:\n"
    "```json\n"
    '{"format": "html", "content": "<h1>...</h1><p>...</p>", '
    '"speech_text": "One or two spoken-style sentences summarizing the result."}\n'
    "```\n"
    "- format: 'html' for rich results (reports, tables), 'markdown' for "
    "simple text, 'mermaid' for a diagram.\n"
    "- content: the full presentation body in that format. For html use only "
    "basic tags (headings, paragraphs, lists, tables, code) — no scripts or styles.\n"
    "- speech_text: a concise plain-text summary that reads well aloud.\n"
)

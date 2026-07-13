"""Unit tests for the presentation model, sanitizer, and extractor (ADR-091)."""

from __future__ import annotations

import json

from nexus.core.presentation import (
    PRESENTATION_PROMPT_INSTRUCTIONS,
    Presentation,
    extract_presentation_from_llm_output,
    sanitize_presentation,
)

# ─── sanitize_presentation — XSS matrix ──────────────────────────────────────


def test_script_tags_stripped() -> None:
    p = sanitize_presentation(
        {"format": "html", "content": "<p>hi</p><script>alert(1)</script>", "speech_text": "hi"}
    )
    assert "<script" not in p.content
    assert "alert(1)" not in p.content
    assert "<p>hi</p>" in p.content


def test_event_handlers_stripped() -> None:
    p = sanitize_presentation(
        {"format": "html", "content": '<img src="https://x/y.png" onerror="alert(1)">'}
    )
    assert "onerror" not in p.content
    assert "https://x/y.png" in p.content


def test_javascript_urls_stripped() -> None:
    p = sanitize_presentation(
        {"format": "html", "content": '<a href="javascript:alert(1)">click</a>'}
    )
    assert "javascript:" not in p.content


def test_http_urls_stripped_https_kept() -> None:
    p = sanitize_presentation(
        {
            "format": "html",
            "content": '<a href="http://insecure">a</a><a href="https://ok">b</a>',
        }
    )
    assert "http://insecure" not in p.content
    assert "https://ok" in p.content


def test_iframe_and_style_stripped() -> None:
    p = sanitize_presentation(
        {
            "format": "html",
            "content": '<iframe src="https://evil"></iframe><div style="color:red">x</div>',
        }
    )
    assert "<iframe" not in p.content
    assert "style=" not in p.content
    assert "x" in p.content


def test_allowed_tags_survive() -> None:
    html = (
        "<h1>Title</h1><p>Text</p><ul><li>item</li></ul>"
        "<table><thead><tr><th>A</th></tr></thead><tbody><tr><td>1</td></tr></tbody></table>"
        "<pre><code>x = 1</code></pre><blockquote>q</blockquote>"
    )
    p = sanitize_presentation({"format": "html", "content": html})
    for tag in ("<h1>", "<p>", "<ul>", "<li>", "<table>", "<th>", "<td>", "<pre>", "<code>"):
        assert tag in p.content


def test_content_capped_at_60kb() -> None:
    p = sanitize_presentation({"format": "markdown", "content": "y" * 100_000})
    assert len(p.content) <= 60_000


def test_markdown_not_html_sanitized_but_capped() -> None:
    # Markdown is rendered escaped client-side; the sanitizer only caps it.
    p = sanitize_presentation({"format": "markdown", "content": "# Title <script>x</script>"})
    assert p.format == "markdown"
    assert "# Title" in p.content


def test_speech_text_derived_when_missing() -> None:
    p = sanitize_presentation({"format": "html", "content": "<h1>Big News</h1><p>All good.</p>"})
    assert "Big News" in p.speech_text
    assert "<" not in p.speech_text


def test_invalid_shape_degrades_to_empty() -> None:
    p = sanitize_presentation({"format": "carrier-pigeon", "content": 42})  # type: ignore[dict-item]
    assert p == Presentation(format="markdown", content="", speech_text="")


# ─── extract_presentation_from_llm_output ────────────────────────────────────


def test_extracts_fenced_presentation_block() -> None:
    block = json.dumps(
        {
            "format": "html",
            "content": "<h2>Report</h2><p>Done.</p>",
            "speech_text": "The report is done.",
        }
    )
    text = f"Here is the synthesis.\n\n```json\n{block}\n```\n"

    clean, presentation = extract_presentation_from_llm_output(text)

    assert clean == "Here is the synthesis."
    assert presentation.format == "html"
    assert "<h2>Report</h2>" in presentation.content
    assert presentation.speech_text == "The report is done."


def test_extracted_block_is_sanitized() -> None:
    block = json.dumps(
        {"format": "html", "content": "<p>ok</p><script>alert(1)</script>", "speech_text": "ok"}
    )
    _, presentation = extract_presentation_from_llm_output(f"x\n```json\n{block}\n```")
    assert "<script" not in presentation.content


def test_malformed_block_falls_back_to_markdown() -> None:
    text = 'Synthesis text.\n```json\n{"format": "html", "content": broken\n```'
    _clean, presentation = extract_presentation_from_llm_output(text)
    assert presentation.format == "markdown"
    assert "Synthesis text." in presentation.content
    assert presentation.speech_text  # derived, non-empty


def test_no_block_falls_back_to_markdown_with_speech() -> None:
    clean, presentation = extract_presentation_from_llm_output("Plain answer only.")
    assert clean == "Plain answer only."
    assert presentation.format == "markdown"
    assert presentation.content == "Plain answer only."
    assert "Plain answer" in presentation.speech_text


def test_prompt_instructions_mention_contract() -> None:
    for needle in ('"format"', '"content"', '"speech_text"', "```json"):
        assert needle in PRESENTATION_PROMPT_INSTRUCTIONS

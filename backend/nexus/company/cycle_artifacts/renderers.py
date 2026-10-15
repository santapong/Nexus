"""Deterministic safe local human views from closed typed draft descriptions."""

from html import escape

from pydantic import TypeAdapter

from nexus.company.cycle_artifacts.payloads import PresentationBrief, SupportDraft
from nexus.company.management.base import SHA256

FACT_TEXT = (
    "Source and patch identities are limited to the nominated isolated engineering work.",
    "The supplied registered engineering evidence records baseline command success.",
    "The supplied registered engineering evidence records post-change command success.",
    "The supplied independent engineering check reports all seven mechanical criteria passed.",
)
STEP_TEXT = (
    "Review the nominated source revision and its dates.",
    "Inspect the protected patch and its bounded change scope.",
    "Inspect author/verifier receipts and the independent engineering check.",
    "Ask the owner to review unresolved deployment and customer-readiness questions.",
)
ANSWER_TEXT = (
    "The referenced isolated engineering work has a supplied passing mechanical check.",
    "The deployed product version and this customer's behavior have not been observed.",
    "Please provide the actual application version and CSV column headers.",
    "Please provide the error message and a sanitized reproduction without sensitive records.",
    "Owner review is required before any response or production action.",
)


def presentation_html(value: PresentationBrief, json_sha256: str) -> bytes:
    """Text is escaped; only fixed local anchors/style exist, with no executable input."""
    TypeAdapter(SHA256).validate_python(json_sha256)
    value = PresentationBrief.model_validate(value.model_dump(warnings=False))
    basis, engine = value.basis, value.basis.engineering
    facts = "".join(
        f'<li>{escape(text)} <a href="#engineering-evidence">Evidence</a></li>'
        for text in FACT_TEXT
    )
    steps = "".join(f"<li>{escape(text)}</li>" for text in STEP_TEXT)
    quotes = "".join(
        f"<section><h3>Source quote {i + 1}</h3><pre>{escape(row.quote)}</pre>"
        f"<p>Evidence {row.evidence_id}; {escape(row.source_event.precision)}: "
        f"{escape(row.source_event.value or 'unknown')}; span {row.span_sha256}</p></section>"
        for i, row in enumerate(basis.citations)
    )
    evidence = (
        f"Acceptance: {engine.acceptance.acceptance_id}\n"
        f"Author receipt: {engine.author_receipt.receipt_id}\n"
        f"Verifier receipt: {engine.verifier_receipt.receipt_id}\n"
        f"Independent check: {engine.check.artifact_revision_id} SHA256 {engine.check.sha256}\n"
        f"Source: {engine.source.repository_symbol}@{engine.source.commit}\n"
        f"Patch SHA256: {engine.patch_sha256}"
    )
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta http-equiv="Content-Security-Policy" '
        "content=\"default-src 'none'; style-src 'unsafe-inline'\">"
        "<title>StockFlow CSV engineering review</title><style>"
        "body{font:18px system-ui;max-width:56rem;margin:3rem auto;padding:1rem;line-height:1.6}"
        "section{margin:3rem 0}pre{white-space:pre-wrap;overflow-wrap:anywhere}a{color:#174f80}"
        "</style><body><h1>StockFlow CSV engineering review</h1>"
        "<p>Internal review draft. Original observed time: "
        f"{escape(basis.observed_at.isoformat())}.</p>"
        "<p>Deployment: not observed. Customer readiness: not assessed. "
        "Specific CSV cases: not observed.</p>"
        f"<section><h2>Engineering scope</h2><ul>{facts}</ul></section>"
        f"<section><h2>Proposed manual review steps</h2><ol>{steps}</ol></section>"
        '<section id="engineering-evidence"><h2>Engineering evidence references</h2>'
        f"<pre>{escape(evidence)}</pre></section>"
        f"{quotes}<p>Canonical draft SHA256: {escape(json_sha256)}</p>"
        "<p>Mechanical draft only. Business readiness unproven. "
        "Owner review required.</p></body></html>"
    ).encode()


def support_markdown(value: SupportDraft, json_sha256: str) -> bytes:
    """Source text is an indented literal block, never a model/source-controlled link or HTML."""
    TypeAdapter(SHA256).validate_python(json_sha256)
    value = SupportDraft.model_validate(value.model_dump(warnings=False))
    engine = value.basis.engineering
    answers = "\n".join(f"- {text}" for text in ANSWER_TEXT)
    quotes = "\n\n".join(
        f"Evidence {row.evidence_id}, span SHA256 {row.span_sha256}:\n\n"
        + _literal_markdown_quote(row.quote)
        for row in value.basis.citations
    )
    return (
        "# StockFlow support draft\n\nHypothetical CSV case. "
        "Internal draft; owner review required.\n\n"
        f"{value.hypothetical_problem}\n\n{answers}\n\n"
        "Deployment: not observed. Customer readiness: not assessed. "
        "Specific behavior cases: not observed.\n\n"
        f"Acceptance: {engine.acceptance.acceptance_id}\n\n"
        f"Author receipt: {engine.author_receipt.receipt_id}\n\n"
        f"Verifier receipt: {engine.verifier_receipt.receipt_id}\n\n"
        f"Independent check: {engine.check.artifact_revision_id}, SHA256 {engine.check.sha256}\n\n"
        f"{quotes}\n\nCanonical draft SHA256: {json_sha256}\n\n"
        "Mechanical draft only. Business readiness unproven. Owner review required.\n"
    ).encode()


def _literal_markdown_quote(text: str) -> str:
    """Prefix every CommonMark physical line; preserve original text in the typed JSON basis."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join("    " + line for line in normalized.split("\n"))

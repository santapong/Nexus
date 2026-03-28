"""PII detection and output sanitization.

Scans agent outputs for personally identifiable information (PII) and
sensitive data patterns before publishing results. Enterprise-grade
data protection that prevents agents from leaking sensitive information
in their outputs.

Patterns detected:
- API keys and tokens (AWS, GitHub, Slack, etc.)
- Email addresses
- Phone numbers
- Credit card numbers
- Social security numbers
- IP addresses (private ranges)
- JWT tokens
- Private keys
- Database connection strings
"""

from __future__ import annotations

import re
from typing import Any

import structlog

logger = structlog.get_logger()


# ─── Pattern definitions ────────────────────────────────────────────────────

_PII_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    # API keys and tokens
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED:AWS_KEY]"),
    ("github_token", re.compile(r"gh[ps]_[A-Za-z0-9_]{36,}"), "[REDACTED:GITHUB_TOKEN]"),
    ("github_pat", re.compile(r"github_pat_[A-Za-z0-9_]{22,}"), "[REDACTED:GITHUB_PAT]"),
    ("slack_token", re.compile(r"xox[bpors]-[A-Za-z0-9-]{10,}"), "[REDACTED:SLACK_TOKEN]"),
    ("anthropic_key", re.compile(r"sk-ant-[A-Za-z0-9-]{20,}"), "[REDACTED:ANTHROPIC_KEY]"),
    ("openai_key", re.compile(r"sk-[A-Za-z0-9]{20,}"), "[REDACTED:API_KEY]"),
    ("bearer_token", re.compile(r"Bearer\s+[A-Za-z0-9._-]{20,}"), "[REDACTED:BEARER]"),
    ("generic_api_key", re.compile(r"(?i)api[_-]?key[\s:=]+['\"]?[A-Za-z0-9_-]{20,}"), "[REDACTED:API_KEY]"),

    # Cryptographic material
    ("private_key", re.compile(r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----"), "[REDACTED:PRIVATE_KEY]"),
    ("ssh_private", re.compile(r"-----BEGIN\s+OPENSSH\s+PRIVATE\s+KEY-----"), "[REDACTED:SSH_KEY]"),

    # PII
    ("email", re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"), "[REDACTED:EMAIL]"),
    ("phone_us", re.compile(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b"), "[REDACTED:PHONE]"),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED:SSN]"),
    ("credit_card", re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"), "[REDACTED:CC]"),

    # Infrastructure
    ("jwt_token", re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"), "[REDACTED:JWT]"),
    ("db_connection", re.compile(r"(?i)(?:postgres|mysql|mongodb)(?:\+\w+)?://[^\s]+"), "[REDACTED:DB_URL]"),
    ("redis_url", re.compile(r"redis://[^\s]+"), "[REDACTED:REDIS_URL]"),
    ("private_ip", re.compile(r"\b(?:10|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d{1,3}\.\d{1,3}\b"), "[REDACTED:PRIVATE_IP]"),
]


class SanitizationResult:
    """Result of a sanitization scan."""

    def __init__(self) -> None:
        self.detections: list[dict[str, str]] = []
        self.sanitized_text: str = ""
        self.has_pii: bool = False

    @property
    def detection_count(self) -> int:
        """Number of PII patterns detected."""
        return len(self.detections)


def scan_text(text: str) -> SanitizationResult:
    """Scan text for PII patterns and return sanitized version.

    Args:
        text: The text to scan for PII.

    Returns:
        SanitizationResult with detections and sanitized text.
    """
    result = SanitizationResult()
    sanitized = text

    for pattern_name, pattern, replacement in _PII_PATTERNS:
        matches = pattern.findall(sanitized)
        if matches:
            result.has_pii = True
            for match in matches:
                result.detections.append({
                    "type": pattern_name,
                    "preview": match[:8] + "***" if len(match) > 8 else "***",
                })
            sanitized = pattern.sub(replacement, sanitized)

    result.sanitized_text = sanitized
    return result


def sanitize_output(output: Any, *, task_id: str = "", agent_id: str = "") -> Any:
    """Sanitize agent output by redacting PII patterns.

    Handles string, dict, and list outputs recursively.

    Args:
        output: The agent output to sanitize.
        task_id: For logging context.
        agent_id: For logging context.

    Returns:
        Sanitized version of the output.
    """
    if output is None:
        return output

    if isinstance(output, str):
        result = scan_text(output)
        if result.has_pii:
            logger.warning(
                "pii_detected_in_output",
                task_id=task_id,
                agent_id=agent_id,
                detection_count=result.detection_count,
                types=[d["type"] for d in result.detections],
            )
        return result.sanitized_text

    if isinstance(output, dict):
        return {
            k: sanitize_output(v, task_id=task_id, agent_id=agent_id)
            for k, v in output.items()
        }

    if isinstance(output, list):
        return [
            sanitize_output(item, task_id=task_id, agent_id=agent_id)
            for item in output
        ]

    return output

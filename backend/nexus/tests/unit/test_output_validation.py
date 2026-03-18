"""Unit tests for AgentBase._validate_output guardrail."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from nexus.agents.base import AgentBase
from nexus.db.models import AgentRole
from nexus.kafka.schemas import AgentResponse


class FakeAgent(AgentBase):
    """Minimal concrete agent for testing."""

    async def handle_task(self, message, session):
        pass  # pragma: no cover


def _make_agent() -> FakeAgent:
    return FakeAgent(
        role=AgentRole.ENGINEER,
        agent_id="test-agent",
        subscribe_topics=["agent.commands"],
        group_id="test-group",
        llm_agent=MagicMock(),
        db_session_factory=MagicMock(),
    )


def _make_response(
    status: str = "success",
    output: dict | None = None,
) -> AgentResponse:
    return AgentResponse(
        task_id=uuid4(),
        trace_id=uuid4(),
        agent_id="test-agent",
        payload={},
        status=status,
        output=output,
        tokens_used=100,
    )


# ─── Empty output tests ──────────────────────────────────────────────────────


def test_empty_output_on_success_downgrades_to_partial() -> None:
    """Success with no output should be downgraded to 'partial'."""
    agent = _make_agent()
    response = _make_response(status="success", output=None)

    result = agent._validate_output(response)

    assert result.status == "partial"


def test_empty_output_on_failed_stays_failed() -> None:
    """Failed status with no output should NOT be changed."""
    agent = _make_agent()
    response = _make_response(status="failed", output=None)

    result = agent._validate_output(response)

    assert result.status == "failed"


def test_nonempty_output_on_success_stays_success() -> None:
    """Success with output should remain 'success'."""
    agent = _make_agent()
    response = _make_response(status="success", output={"result": "hello"})

    result = agent._validate_output(response)

    assert result.status == "success"


# ─── Secret detection tests ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "pattern",
    [
        "sk-proj-abc123",
        "AKIAIOSFODNN7EXAMPLE",
        "Bearer eyJhbGciOiJ...",
        "ghp_xxxxxxxxxxxx",
        "gho_yyyyyyyyyyyy",
        "github_pat_zzzz",
        "xoxb-token-here",
        "xoxp-another-token",
        "-----BEGIN PRIVATE KEY",
    ],
)
def test_secret_pattern_detected(pattern: str) -> None:
    """Each secret pattern should trigger redaction."""
    agent = _make_agent()
    response = _make_response(
        status="success",
        output={"result": f"Here is the key: {pattern}"},
    )

    result = agent._validate_output(response)

    # The response should still be returned (not blocked)
    assert result is not None


def test_no_false_positive_on_clean_output() -> None:
    """Clean output without secret patterns should not be modified."""
    agent = _make_agent()
    output = {"result": "This is perfectly normal output with no secrets."}
    response = _make_response(status="success", output=output)

    result = agent._validate_output(response)

    assert result.status == "success"
    assert result.output == output


# ─── Size limit tests ────────────────────────────────────────────────────────


def test_large_output_gets_truncation_flag() -> None:
    """Output exceeding MAX_OUTPUT_SIZE should get _truncated flag."""
    agent = _make_agent()
    large_text = "x" * 150_000
    response = _make_response(
        status="success",
        output={"result": large_text},
    )

    result = agent._validate_output(response)

    assert result.output is not None
    assert result.output.get("_truncated") is True
    assert result.output.get("_original_size", 0) > AgentBase._MAX_OUTPUT_SIZE


def test_normal_size_output_no_truncation() -> None:
    """Output within size limit should not have truncation flags."""
    agent = _make_agent()
    response = _make_response(
        status="success",
        output={"result": "short output"},
    )

    result = agent._validate_output(response)

    assert result.output is not None
    assert "_truncated" not in result.output

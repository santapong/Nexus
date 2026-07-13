"""Behavior test: presentation flows Director → QA → result consumer (ADR-091).

Covers the full pass-through chain with deterministic mocks:
- The Director extracts + sanitizes the presentation from LLM synthesis and
  puts it on the QA command payload.
- QA copies it into its final outputs without touching it.
- The result consumer re-sanitizes at the choke point before the DB write
  and the WebSocket broadcast, so dirty markup can never reach the
  dashboard even if a future producer skips sanitization.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from nexus.core.kafka.result_consumer import _handle_response
from nexus.core.presentation import extract_presentation_from_llm_output


def _make_response_raw(output: dict[str, Any]) -> dict[str, Any]:
    return {
        "message_id": str(uuid4()),
        "task_id": str(uuid4()),
        "trace_id": str(uuid4()),
        "agent_id": "test-qa",
        "timestamp": datetime.now(UTC).isoformat(),
        "payload": {},
        "status": "success",
        "output": output,
        "error": None,
        "tokens_used": 100,
    }


def _make_session_factory(mock_task: MagicMock) -> MagicMock:
    mock_session = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()
    # Query order on the direct-task path: (1) _check_is_subtask selects
    # parent_task_id — must be None so we do NOT take the subtask/CEO
    # branch; (2) _update_task_in_db selects the Task row itself.
    mock_session.execute = AsyncMock(
        side_effect=[
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
            MagicMock(scalar_one_or_none=MagicMock(return_value=mock_task)),
        ]
    )
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=cm)


def test_director_synthesis_to_qa_payload_shape() -> None:
    """What the Director extracts is exactly what QA passes through."""
    block = json.dumps(
        {
            "format": "html",
            "content": "<h2>Result</h2><script>alert(1)</script><p>Done.</p>",
            "speech_text": "The result is done.",
        }
    )
    synthesized_raw = f"The final answer.\n```json\n{block}\n```"

    clean, presentation = extract_presentation_from_llm_output(synthesized_raw)

    # Director-side sanitization already stripped the script.
    assert clean == "The final answer."
    payload_presentation = presentation.model_dump()
    assert "<script" not in payload_presentation["content"]
    assert payload_presentation["speech_text"] == "The result is done."
    # This dict shape is what rides qa_command.payload["presentation"] and
    # is copied verbatim into QA's TaskResult/AgentResponse outputs.
    assert set(payload_presentation) == {"format", "content", "speech_text"}


@pytest.mark.asyncio
async def test_result_consumer_resanitizes_and_broadcasts_presentation() -> None:
    """Dirty presentation reaching the consumer is sanitized before DB + WS."""
    dirty = {
        "format": "html",
        "content": '<p>ok</p><script>alert(1)</script><a href="javascript:x">l</a>',
        "speech_text": "ok",
    }
    raw = _make_response_raw({"qa_review": "{}", "original_output": "ok", "presentation": dirty})
    mock_task = MagicMock()
    mock_task.parent_task_id = None  # direct task → full publish path
    mock_task.assigned_agent_id = "test-qa"
    session_factory = _make_session_factory(mock_task)

    published: list[Any] = []
    redis_events: list[str] = []
    redis_mock = AsyncMock()
    redis_mock.publish = AsyncMock(side_effect=lambda _ch, msg: redis_events.append(msg))

    with (
        patch(
            "nexus.core.kafka.result_consumer.check_idempotency",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "nexus.core.kafka.result_consumer.publish",
            new_callable=AsyncMock,
            side_effect=lambda _t, msg, key=None: published.append(msg),
        ),
        patch("nexus.core.kafka.result_consumer.redis_pubsub", redis_mock),
    ):
        await _handle_response(raw, session_factory)

    # Task marked completed; output on the task row is sanitized.
    assert mock_task.status == "completed"
    task_presentation = mock_task.output["presentation"]
    assert "<script" not in task_presentation["content"]
    assert "javascript:" not in task_presentation["content"]
    assert "<p>ok</p>" in task_presentation["content"]

    # TaskResult published to task.results carries the sanitized version.
    assert published, "expected a TaskResult publish"
    result_presentation = published[0].output["presentation"]
    assert "<script" not in result_presentation["content"]

    # WebSocket broadcast event carries the sanitized version too.
    assert redis_events, "expected a Redis pub/sub broadcast"
    event = json.loads(redis_events[0])
    assert event["event"] == "task_result"
    assert "<script" not in event["output"]["presentation"]["content"]
    assert event["output"]["presentation"]["speech_text"] == "ok"

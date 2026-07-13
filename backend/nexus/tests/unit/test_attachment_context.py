"""Unit tests for attachment context loading in AgentBase (ADR-089/090)."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nexus.agents.base import AgentBase
from nexus.core.kafka.schemas import AgentCommand
from nexus.db.models import AgentRole
from nexus.settings import settings


class _StubAgent:
    """Bare object carrying just what _load_attachments needs."""

    _load_attachments = AgentBase._load_attachments
    _attachment_context_block = AgentBase._attachment_context_block

    def __init__(self) -> None:
        self.agent_id = "stub-agent"
        self.role = AgentRole.ENGINEER


def _command(payload: dict[str, Any] | None = None) -> AgentCommand:
    return AgentCommand(
        task_id=uuid4(),
        trace_id=uuid4(),
        agent_id="ceo",
        payload=payload or {},
        target_role="engineer",
        instruction="do the thing",
    )


def _session_returning(rows: list[Any]) -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    session.execute = AsyncMock(return_value=result)
    return session


def _attachment(filename: str, text: str) -> MagicMock:
    att = MagicMock()
    att.filename = filename
    att.mime_type = "text/plain"
    att.parsed_text = text
    return att


@pytest.mark.asyncio
async def test_loads_attachments_for_direct_task() -> None:
    agent = cast(AgentBase, _StubAgent())
    session = _session_returning([_attachment("a.txt", "alpha")])

    loaded = await agent._load_attachments(session, _command())

    assert loaded == [{"filename": "a.txt", "mime_type": "text/plain", "parsed_text": "alpha"}]


@pytest.mark.asyncio
async def test_subtask_queries_parent_task_id_too() -> None:
    agent = cast(AgentBase, _StubAgent())
    session = _session_returning([])
    parent_id = str(uuid4())

    await agent._load_attachments(session, _command({"parent_task_id": parent_id}))

    # The IN clause must include both the subtask id and the parent id.
    stmt = session.execute.await_args.args[0]
    params = stmt.compile().params
    in_values: set[str] = set()
    for value in params.values():
        if isinstance(value, list):
            in_values.update(str(v) for v in value)
        else:
            in_values.add(str(value))
    assert parent_id in in_values


@pytest.mark.asyncio
async def test_char_budget_truncates_across_attachments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = cast(AgentBase, _StubAgent())
    monkeypatch.setattr(settings, "attachment_context_char_budget", 8)
    session = _session_returning(
        [_attachment("a.txt", "12345"), _attachment("b.txt", "67890"), _attachment("c.txt", "x")]
    )

    loaded = await agent._load_attachments(session, _command())

    assert loaded[0]["parsed_text"] == "12345"  # 5 chars, 3 left
    assert loaded[1]["parsed_text"] == "678"  # truncated to remaining budget
    assert len(loaded) == 2  # budget exhausted — third attachment dropped


@pytest.mark.asyncio
async def test_empty_result_returns_empty_list() -> None:
    agent = cast(AgentBase, _StubAgent())
    session = _session_returning([])
    assert await agent._load_attachments(session, _command()) == []


def test_attachment_context_block_formats_sections() -> None:
    agent = cast(AgentBase, _StubAgent())
    agent._memory_context = {
        "attachments": [
            {"filename": "r.pdf", "mime_type": "application/pdf", "parsed_text": "profits up"}
        ]
    }
    block = agent._attachment_context_block()
    assert block is not None
    assert "Attached documents" in block
    assert "### r.pdf (application/pdf)" in block
    assert "profits up" in block


def test_attachment_context_block_none_when_absent() -> None:
    agent = cast(AgentBase, _StubAgent())
    agent._memory_context = {}
    assert agent._attachment_context_block() is None

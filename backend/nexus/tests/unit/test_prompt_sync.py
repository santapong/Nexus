"""Unit tests for prompt versioning, sync, and rollback."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nexus.api.prompts import _sync_agent_prompt, _to_response


# ─── _sync_agent_prompt ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_agent_prompt_updates_matching_agents() -> None:
    """_sync_agent_prompt should update system_prompt for all agents of a role."""
    session = AsyncMock()

    agent1 = MagicMock()
    agent1.system_prompt = "old prompt"
    agent2 = MagicMock()
    agent2.system_prompt = "old prompt"

    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [agent1, agent2]
    mock_result.scalars.return_value = mock_scalars
    session.execute = AsyncMock(return_value=mock_result)

    await _sync_agent_prompt(session, "engineer", "new prompt content")

    assert agent1.system_prompt == "new prompt content"
    assert agent2.system_prompt == "new prompt content"


@pytest.mark.asyncio
async def test_sync_agent_prompt_no_agents() -> None:
    """_sync_agent_prompt should handle no matching agents gracefully."""
    session = AsyncMock()

    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_result.scalars.return_value = mock_scalars
    session.execute = AsyncMock(return_value=mock_result)

    # Should not raise
    await _sync_agent_prompt(session, "nonexistent_role", "new content")


# ─── _to_response ────────────────────────────────────────────────────────────


def test_to_response_maps_fields() -> None:
    """_to_response should correctly map Prompt fields to PromptResponse."""
    prompt = MagicMock()
    prompt.id = uuid4()
    prompt.agent_role = "engineer"
    prompt.version = 3
    prompt.content = "You are an engineer..."
    prompt.benchmark_score = 0.85
    prompt.is_active = True
    prompt.authored_by = "human"
    prompt.notes = "Improved reasoning"
    prompt.created_at = "2026-03-14T10:00:00"
    prompt.approved_at = "2026-03-14T11:00:00"

    result = _to_response(prompt)

    assert result.id == str(prompt.id)
    assert result.agent_role == "engineer"
    assert result.version == 3
    assert result.content == "You are an engineer..."
    assert result.benchmark_score == 0.85
    assert result.is_active is True
    assert result.authored_by == "human"
    assert result.notes == "Improved reasoning"


def test_to_response_handles_none_approved_at() -> None:
    """_to_response should handle None approved_at."""
    prompt = MagicMock()
    prompt.id = uuid4()
    prompt.agent_role = "ceo"
    prompt.version = 1
    prompt.content = "You are the CEO..."
    prompt.benchmark_score = None
    prompt.is_active = False
    prompt.authored_by = "prompt_creator_agent"
    prompt.notes = None
    prompt.created_at = "2026-03-14T10:00:00"
    prompt.approved_at = None

    result = _to_response(prompt)

    assert result.approved_at is None
    assert result.benchmark_score is None
    assert result.notes is None

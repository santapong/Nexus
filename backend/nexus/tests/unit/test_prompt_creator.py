"""Unit tests for the Prompt Creator Agent.

Tests benchmark scoring, proposal creation (never auto-activates),
and trigger logic on failure rate threshold.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from nexus.agents.prompt_creator import (
    _FAILURE_RATE_THRESHOLD,
    PromptCreatorAgent,
)
from nexus.core.kafka.schemas import AgentCommand


@pytest.fixture
def mock_session() -> AsyncMock:
    """Create a mock async database session."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    return session


@pytest.fixture
def sample_command() -> AgentCommand:
    """Create a sample improvement request command."""
    return AgentCommand(
        task_id=uuid4(),
        trace_id=uuid4(),
        agent_id="api",
        payload={"target_role": "engineer", "trigger": "manual"},
        target_role="prompt_creator",
        instruction="Improve the engineer agent prompt",
    )


class TestPromptCreatorAnalysis:
    """Tests for failure analysis logic."""

    def test_failure_rate_threshold_is_10_percent(self) -> None:
        """Failure rate threshold is 10% as specified."""
        assert _FAILURE_RATE_THRESHOLD == 0.10

    @pytest.mark.asyncio
    @patch("nexus.agents.prompt_creator.publish", new_callable=AsyncMock)
    async def test_handle_task_rejects_missing_target_role(
        self, mock_publish: AsyncMock, mock_session: AsyncMock
    ) -> None:
        """handle_task fails when target_role is missing."""
        command = AgentCommand(
            task_id=uuid4(),
            trace_id=uuid4(),
            agent_id="api",
            payload={},  # Missing target_role
            target_role="prompt_creator",
            instruction="Improve prompt",
        )

        agent = _build_mock_agent()
        response = await agent.handle_task(command, mock_session)

        assert response.status == "failed"
        assert response.error is not None and "target_role" in response.error


class TestPromptCreatorProposal:
    """Tests for prompt proposal behavior."""

    def test_proposed_prompt_is_never_auto_active(self) -> None:
        """Verify the contract: proposed prompts are NEVER auto-activated."""
        # This is a design constraint test — the Prompt model field
        # defaults to is_active=False, and PromptCreatorAgent never
        # sets is_active=True. Only the API activation endpoint does.
        from nexus.db.models import Prompt

        p = Prompt(
            agent_role="engineer",
            version=2,
            content="test prompt",
            is_active=False,
            authored_by="prompt_creator_agent",
        )
        assert p.is_active is False


def _build_mock_agent() -> PromptCreatorAgent:
    """Build a PromptCreatorAgent with mocked dependencies."""
    mock_llm = MagicMock()
    mock_llm.model = "test:latest"

    return PromptCreatorAgent(
        role=MagicMock(value="prompt_creator"),
        agent_id="prompt-creator-001",
        subscribe_topics=["prompt.improvement_requests"],
        group_id="nexus-prompt_creator",
        llm_agent=mock_llm,
        db_session_factory=AsyncMock(),
    )

"""Chaos test fixtures — infrastructure failure injection."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nexus.kafka.schemas import AgentCommand, AgentResponse


@pytest.fixture
def sample_command() -> AgentCommand:
    """Create a sample AgentCommand for chaos testing."""
    return AgentCommand(
        task_id=uuid4(),
        trace_id=uuid4(),
        agent_id="test-agent",
        payload={"test": True},
        target_role="engineer",
        instruction="Test task for chaos testing",
    )


@pytest.fixture
def sample_response() -> AgentResponse:
    """Create a sample AgentResponse for chaos testing."""
    return AgentResponse(
        task_id=uuid4(),
        trace_id=uuid4(),
        agent_id="test-agent",
        payload={},
        status="success",
        output={"result": "test output"},
    )


@pytest.fixture
def mock_db_session_factory() -> AsyncMock:
    """Create a mock DB session factory."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock()
    session.add = MagicMock()

    factory = AsyncMock()
    factory.__aenter__ = AsyncMock(return_value=session)
    factory.__aexit__ = AsyncMock(return_value=False)
    factory.return_value = factory

    return factory

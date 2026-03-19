from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from nexus.core.kafka.schemas import AgentCommand, HeartbeatMessage, KafkaMessage


def test_kafka_message_requires_mandatory_fields() -> None:
    """KafkaMessage rejects messages missing task_id, trace_id, or agent_id."""
    with pytest.raises(ValidationError):
        KafkaMessage(payload={})  # type: ignore[call-arg]


def test_kafka_message_serialization() -> None:
    """KafkaMessage serializes and deserializes correctly."""
    msg = KafkaMessage(
        task_id=uuid4(),
        trace_id=uuid4(),
        agent_id="engineer",
        payload={"key": "value"},
    )
    data = msg.model_dump(mode="json")
    assert "task_id" in data
    assert "trace_id" in data
    assert "agent_id" in data
    assert data["payload"] == {"key": "value"}


def test_agent_command_includes_instruction() -> None:
    """AgentCommand extends KafkaMessage with target_role and instruction."""
    cmd = AgentCommand(
        task_id=uuid4(),
        trace_id=uuid4(),
        agent_id="ceo",
        payload={},
        target_role="engineer",
        instruction="Write a function",
    )
    assert cmd.target_role == "engineer"
    assert cmd.instruction == "Write a function"


def test_heartbeat_does_not_require_task_id() -> None:
    """HeartbeatMessage is lightweight and doesn't need task_id."""
    hb = HeartbeatMessage(agent_id="engineer")
    assert hb.status == "alive"
    assert hb.current_task_id is None

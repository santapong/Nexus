from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class KafkaMessage(BaseModel):
    """Standard message envelope. Mandatory on every Kafka message.

    Consumers reject messages missing task_id, trace_id, or agent_id.
    """

    message_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    trace_id: UUID
    agent_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: dict[str, object]


class AgentCommand(KafkaMessage):
    """Command sent to an agent via agent.commands topic."""

    target_role: str
    instruction: str


class AgentResponse(KafkaMessage):
    """Response published by an agent via agent.responses topic."""

    status: str  # success | failed | partial | escalated
    output: dict[str, object] | None = None
    error: str | None = None
    tokens_used: int = 0


class TaskResult(KafkaMessage):
    """Final task result published to task.results topic."""

    status: str  # completed | failed | escalated
    output: dict[str, object] | None = None
    error: str | None = None


class HeartbeatMessage(BaseModel):
    """Lightweight heartbeat — does not require task_id."""

    agent_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "alive"  # alive | busy | shutting_down
    current_task_id: UUID | None = None

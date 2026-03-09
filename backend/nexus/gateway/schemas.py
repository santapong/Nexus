"""A2A Gateway Pydantic schemas.

Defines the data models for the Agent-to-Agent (A2A) protocol
as specified in CLAUDE.md §9.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


# ─── Agent Card (/.well-known/agent.json) ────────────────────────────────────


class AgentSkill(BaseModel):
    """A single skill the agent can perform."""

    id: str
    name: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)


class AgentCard(BaseModel):
    """Public Agent Card served at /.well-known/agent.json.

    Describes the agent's identity, capabilities, and API endpoint.
    """

    name: str = "NEXUS"
    description: str = (
        "Agentic AI Company-as-a-Service — accepts research, "
        "writing, engineering, and analysis tasks."
    )
    url: str = ""
    version: str = "0.2.0"
    skills: list[AgentSkill] = Field(default_factory=lambda: [
        AgentSkill(
            id="research",
            name="Research & Analysis",
            description="Research a topic and produce a structured report.",
            input_schema={
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "depth": {"type": "string", "enum": ["brief", "detailed"]},
                },
                "required": ["topic"],
            },
        ),
        AgentSkill(
            id="write",
            name="Content Writing",
            description="Write emails, documents, or other content.",
            input_schema={
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["email", "document", "report"]},
                    "instruction": {"type": "string"},
                },
                "required": ["instruction"],
            },
        ),
        AgentSkill(
            id="code",
            name="Engineering",
            description="Write, debug, or review code.",
            input_schema={
                "type": "object",
                "properties": {
                    "language": {"type": "string"},
                    "instruction": {"type": "string"},
                },
                "required": ["instruction"],
            },
        ),
        AgentSkill(
            id="general",
            name="General Task",
            description="Handle any task — CEO will decompose and route.",
            input_schema={
                "type": "object",
                "properties": {
                    "instruction": {"type": "string"},
                },
                "required": ["instruction"],
            },
        ),
    ])
    auth: dict[str, str] = Field(default_factory=lambda: {
        "type": "bearer",
        "description": "Bearer token required for task submission.",
    })


# ─── A2A Task submission ────────────────────────────────────────────────────


class A2ATaskRequest(BaseModel):
    """Incoming task request from an external agent."""

    skill_id: str = "general"
    input: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class A2ATaskResponse(BaseModel):
    """Response after accepting an A2A task."""

    task_id: str
    status: str = "accepted"
    stream_url: str = ""


# ─── A2A Events (SSE stream) ────────────────────────────────────────────────


class A2AEventStatus(BaseModel):
    """Status update event in the SSE stream."""

    event_type: str = "status_update"
    task_id: str
    status: str  # accepted, working, completed, failed
    message: str = ""
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class A2AArtifactEvent(BaseModel):
    """Artifact produced during task execution."""

    event_type: str = "artifact"
    task_id: str
    artifact_type: str  # text, code, data
    content: str
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class A2ACompletionEvent(BaseModel):
    """Final completion event."""

    event_type: str = "completion"
    task_id: str
    status: str  # completed, failed
    output: dict[str, Any] | None = None
    error: str | None = None
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

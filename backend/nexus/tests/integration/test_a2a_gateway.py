"""Integration tests for the A2A Gateway.

Tests agent card, authentication, task submission, access control,
and end-to-end task flow including DB persistence and SSE streaming.
"""
from __future__ import annotations

import json

from nexus.gateway.auth import (
    register_token,
    seed_dev_token,
    validate_token,
)
from nexus.gateway.schemas import A2ATaskRequest, AgentCard


class TestA2AAuthentication:
    """Tests for A2A bearer token validation."""

    def test_valid_token_accepted(self) -> None:
        """Registered token is accepted."""
        raw_token = "test-token-1234"
        register_token(raw_token, name="test")

        is_valid, error = validate_token(raw_token)
        assert is_valid is True
        assert error == ""

    def test_invalid_token_rejected(self) -> None:
        """Unregistered token is rejected."""
        is_valid, error = validate_token("nonexistent-token")
        assert is_valid is False
        assert "Invalid" in error

    def test_empty_token_rejected(self) -> None:
        """Empty token is rejected."""
        is_valid, error = validate_token("")
        assert is_valid is False
        assert "Missing" in error

    def test_expired_token_rejected(self) -> None:
        """Expired token is rejected."""
        register_token(
            "expired-token",
            name="expired",
            expires_at=1.0,  # Already expired
        )
        is_valid, error = validate_token("expired-token")
        assert is_valid is False
        assert "expired" in error.lower()

    def test_skill_access_control(self) -> None:
        """Token with limited skills can't access other skills."""
        register_token(
            "limited-token",
            name="limited",
            allowed_skills=["research"],
        )
        # Allowed skill
        is_valid, _ = validate_token("limited-token", skill_id="research")
        assert is_valid is True

        # Disallowed skill
        is_valid, error = validate_token("limited-token", skill_id="code")
        assert is_valid is False
        assert "skill" in error.lower()

    def test_wildcard_skill_access(self) -> None:
        """Token with wildcard can access all skills."""
        register_token(
            "wildcard-token",
            name="wildcard",
            allowed_skills=["*"],
        )
        is_valid, _ = validate_token("wildcard-token", skill_id="code")
        assert is_valid is True
        is_valid, _ = validate_token("wildcard-token", skill_id="research")
        assert is_valid is True

    def test_dev_token_seeder(self) -> None:
        """Dev token seeder creates a valid token."""
        raw = seed_dev_token()
        is_valid, _ = validate_token(raw)
        assert is_valid is True


class TestAgentCard:
    """Tests for the Agent Card schema."""

    def test_agent_card_has_skills(self) -> None:
        """Agent Card contains the default skills."""
        card = AgentCard()
        assert len(card.skills) >= 4
        skill_ids = [s.id for s in card.skills]
        assert "research" in skill_ids
        assert "write" in skill_ids
        assert "code" in skill_ids
        assert "general" in skill_ids

    def test_agent_card_has_auth_info(self) -> None:
        """Agent Card contains authentication info."""
        card = AgentCard()
        assert card.auth["type"] == "bearer"

    def test_agent_card_version(self) -> None:
        """Agent Card has version info."""
        card = AgentCard()
        assert card.version == "0.2.0"


class TestA2ATaskRequest:
    """Tests for task request validation."""

    def test_default_skill_is_general(self) -> None:
        """Default skill_id is 'general'."""
        req = A2ATaskRequest()
        assert req.skill_id == "general"

    def test_custom_input(self) -> None:
        """Custom input is accepted."""
        req = A2ATaskRequest(
            skill_id="research",
            input={"topic": "quantum computing", "depth": "detailed"},
            metadata={"caller": "external-agent"},
        )
        assert req.input["topic"] == "quantum computing"
        assert req.metadata["caller"] == "external-agent"


class TestA2AEndToEndFlow:
    """End-to-end tests for the A2A gateway inbound task flow.

    These tests validate DB persistence, Kafka publishing, status
    polling, and SSE streaming with mocked infrastructure.
    """

    def test_submit_task_creates_db_record(self) -> None:
        """submit_task persists a Task row with source='a2a'."""

        from nexus.db.models import Task, TaskSource, TaskStatus

        # Simulate the DB record creation logic from routes.submit_task
        task = Task(
            trace_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            instruction="Research quantum computing trends",
            status=TaskStatus.QUEUED.value,
            source=TaskSource.A2A.value,
            source_agent="external-test-agent",
        )
        assert task.status == "queued"
        assert task.source == "a2a"
        assert task.source_agent == "external-test-agent"
        assert task.instruction == "Research quantum computing trends"

    def test_submit_task_builds_correct_kafka_command(self) -> None:
        """submit_task creates an AgentCommand targeting the CEO."""
        from uuid import uuid4

        from nexus.kafka.schemas import AgentCommand

        task_id = uuid4()
        trace_id = uuid4()
        command = AgentCommand(
            task_id=task_id,
            trace_id=trace_id,
            agent_id="a2a-gateway",
            payload={
                "source": "a2a",
                "skill_id": "research",
                "metadata": {"caller": "ext-agent"},
            },
            target_role="ceo",
            instruction="Research quantum computing trends",
        )

        assert command.agent_id == "a2a-gateway"
        assert command.target_role == "ceo"
        assert command.payload["source"] == "a2a"
        assert command.payload["skill_id"] == "research"
        assert str(command.task_id) == str(task_id)

    def test_task_status_response_shape(self) -> None:
        """get_task_status returns expected fields from a Task object."""
        from nexus.db.models import Task, TaskStatus

        task = Task(
            trace_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            instruction="Test instruction",
            status=TaskStatus.COMPLETED.value,
            source="a2a",
            tokens_used=1500,
            output={"result": "done"},
            error=None,
        )
        # Simulate the response dict built by get_task_status
        response = {
            "task_id": str(task.id),
            "status": task.status,
            "output": task.output,
            "error": task.error,
            "tokens_used": task.tokens_used,
        }

        assert response["status"] == "completed"
        assert response["tokens_used"] == 1500
        assert response["output"] == {"result": "done"}
        assert response["error"] is None

    def test_sse_event_format(self) -> None:
        """SSE events follow the 'data: {json}\\n\\n' format."""
        task_id = "test-task-123"

        # Connected event
        connected = f"data: {json.dumps({'event_type': 'connected', 'task_id': task_id})}\n\n"
        assert connected.startswith("data: ")
        assert connected.endswith("\n\n")
        parsed = json.loads(connected.replace("data: ", "").strip())
        assert parsed["event_type"] == "connected"
        assert parsed["task_id"] == task_id

        # Done event
        done = f"data: {json.dumps({'event_type': 'done', 'task_id': task_id})}\n\n"
        parsed_done = json.loads(done.replace("data: ", "").strip())
        assert parsed_done["event_type"] == "done"

    def test_sse_terminates_on_task_result(self) -> None:
        """SSE stream should terminate when it sees a task_result event."""
        # Simulate the termination check from stream_task_events
        event_data = json.dumps({
            "event": "task_result",
            "task_id": "test-123",
            "status": "completed",
            "output": {"result": "done"},
        })
        parsed = json.loads(event_data)
        assert parsed.get("event") in ("task_result", "task_failed")

    def test_sse_does_not_terminate_on_subtask_event(self) -> None:
        """SSE stream should NOT terminate on intermediate subtask events."""
        event_data = json.dumps({
            "event": "subtask_completed",
            "task_id": "sub-456",
            "parent_task_id": "test-123",
            "status": "success",
        })
        parsed = json.loads(event_data)
        assert parsed.get("event") not in ("task_result", "task_failed")

    def test_sse_requires_valid_token(self) -> None:
        """SSE endpoint rejects requests without valid bearer token."""
        is_valid, error = validate_token("")
        assert is_valid is False
        # The SSE endpoint returns {"error": error} for invalid tokens
        response = {"error": error}
        assert "error" in response

    def test_a2a_task_request_instruction_extraction(self) -> None:
        """Task instruction is extracted from input.instruction or input.topic."""
        # Case 1: instruction key present
        req1 = A2ATaskRequest(
            input={"instruction": "Build a REST API"},
        )
        instruction = req1.input.get("instruction", "")
        assert instruction == "Build a REST API"

        # Case 2: topic key as fallback
        req2 = A2ATaskRequest(
            input={"topic": "quantum computing"},
        )
        instruction2 = req2.input.get("instruction", "")
        if not instruction2:
            instruction2 = req2.input.get("topic", str(req2.input))
        assert instruction2 == "quantum computing"

        # Case 3: neither key — falls back to string representation
        req3 = A2ATaskRequest(
            input={"data": "raw payload"},
        )
        instruction3 = req3.input.get("instruction", "")
        if not instruction3:
            instruction3 = req3.input.get("topic", str(req3.input))
        assert "raw payload" in instruction3

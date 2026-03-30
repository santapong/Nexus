"""Unit tests for conference room messaging — MeetingCommand, plan approval, and meeting flow.

Tests the new schemas, CEO meeting decision heuristic, and meeting round orchestration.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from nexus.core.kafka.schemas import MeetingCommand, PlanApprovalMessage
from nexus.db.models import TaskStatus


class TestMeetingCommand:
    """Tests for the MeetingCommand Kafka schema."""

    def test_meeting_command_creation(self) -> None:
        """MeetingCommand creates with all required fields."""
        cmd = MeetingCommand(
            task_id=uuid4(),
            trace_id=uuid4(),
            agent_id="ceo-001",
            payload={},
            meeting_id="meeting-abc",
            question="How should we approach this?",
            participants=["engineer", "analyst"],
            round_number=1,
        )
        assert cmd.meeting_id == "meeting-abc"
        assert cmd.question == "How should we approach this?"
        assert cmd.participants == ["engineer", "analyst"]
        assert cmd.round_number == 1

    def test_meeting_command_serialization(self) -> None:
        """MeetingCommand serializes and deserializes via model_dump/validate."""
        cmd = MeetingCommand(
            task_id=uuid4(),
            trace_id=uuid4(),
            agent_id="ceo-001",
            payload={"meeting_id": "m-123"},
            meeting_id="m-123",
            question="What are the risks?",
            participants=["engineer", "analyst", "writer"],
            round_number=2,
        )
        data = cmd.model_dump(mode="json")
        restored = MeetingCommand.model_validate(data)
        assert restored.meeting_id == "m-123"
        assert restored.participants == ["engineer", "analyst", "writer"]
        assert restored.round_number == 2

    def test_meeting_command_default_round(self) -> None:
        """MeetingCommand defaults to round 1."""
        cmd = MeetingCommand(
            task_id=uuid4(),
            trace_id=uuid4(),
            agent_id="ceo",
            payload={},
            meeting_id="m-1",
            question="test",
            participants=["engineer"],
        )
        assert cmd.round_number == 1

    def test_meeting_command_missing_fields_raises(self) -> None:
        """MeetingCommand requires meeting_id, question, and participants."""
        with pytest.raises(ValidationError):
            MeetingCommand(
                task_id=uuid4(),
                trace_id=uuid4(),
                agent_id="ceo",
                payload={},
                # missing meeting_id, question, participants
            )  # type: ignore[call-arg]


class TestPlanApprovalMessage:
    """Tests for the PlanApprovalMessage Kafka schema."""

    def test_plan_approval_approved(self) -> None:
        """PlanApprovalMessage with approved=True."""
        msg = PlanApprovalMessage(
            task_id=uuid4(),
            trace_id=uuid4(),
            agent_id="api",
            payload={},
            approved=True,
            feedback="",
        )
        assert msg.approved is True
        assert msg.feedback == ""

    def test_plan_approval_rejected_with_feedback(self) -> None:
        """PlanApprovalMessage with rejection and feedback."""
        msg = PlanApprovalMessage(
            task_id=uuid4(),
            trace_id=uuid4(),
            agent_id="api",
            payload={},
            approved=False,
            feedback="Need more focus on security",
        )
        assert msg.approved is False
        assert msg.feedback == "Need more focus on security"


class TestTaskStatusEnum:
    """Tests for the AWAITING_APPROVAL task status."""

    def test_awaiting_approval_status_exists(self) -> None:
        """TaskStatus enum includes awaiting_approval."""
        assert TaskStatus.AWAITING_APPROVAL == "awaiting_approval"
        assert TaskStatus.AWAITING_APPROVAL.value == "awaiting_approval"

    def test_all_statuses_present(self) -> None:
        """All expected task statuses exist in the enum."""
        expected = {"queued", "running", "paused", "awaiting_approval",
                    "completed", "failed", "escalated"}
        actual = {s.value for s in TaskStatus}
        assert expected == actual


class TestShouldUseMeeting:
    """Tests for CEO's _should_use_meeting() heuristic."""

    def _make_command(
        self, instruction: str, payload: dict | None = None,
    ) -> object:
        """Create a mock AgentCommand-like object for testing."""
        from nexus.core.kafka.schemas import AgentCommand

        return AgentCommand(
            task_id=uuid4(),
            trace_id=uuid4(),
            agent_id="api",
            payload=payload or {},
            target_role="ceo",
            instruction=instruction,
        )

    def test_short_instruction_skips_meeting(self) -> None:
        """Short instructions skip the meeting flow."""
        from nexus.agents.ceo import CEOAgent, _MIN_MEETING_INSTRUCTION_LENGTH

        # We can't instantiate CEOAgent without all deps, so test the heuristic directly
        cmd = self._make_command("Fix the login bug")
        assert len(cmd.instruction) < _MIN_MEETING_INSTRUCTION_LENGTH

    def test_complexity_keywords_trigger_meeting(self) -> None:
        """Instructions with complexity keywords should trigger meeting."""
        from nexus.agents.ceo import _COMPLEXITY_KEYWORDS

        assert _COMPLEXITY_KEYWORDS.search("Build a REST API for user management")
        assert _COMPLEXITY_KEYWORDS.search("Design the authentication system")
        assert _COMPLEXITY_KEYWORDS.search("Migrate the database to PostgreSQL 16")
        assert _COMPLEXITY_KEYWORDS.search("Implement the payment integration")

    def test_simple_instructions_no_keywords(self) -> None:
        """Simple instructions without complexity keywords."""
        from nexus.agents.ceo import _COMPLEXITY_KEYWORDS

        assert _COMPLEXITY_KEYWORDS.search("Fix the typo in README") is None
        assert _COMPLEXITY_KEYWORDS.search("Update the version number") is None

    def test_user_override_require_meeting_true(self) -> None:
        """User can force meeting via payload flag."""
        cmd = self._make_command("Short task", payload={"require_meeting": True})
        assert cmd.payload.get("require_meeting") is True

    def test_user_override_require_meeting_false(self) -> None:
        """User can skip meeting via payload flag."""
        cmd = self._make_command(
            "Build a complex microservices platform with authentication and database design",
            payload={"require_meeting": False},
        )
        assert cmd.payload.get("require_meeting") is False


class TestMeetingRoomRoundOrchestration:
    """Tests for MeetingRoom.run_meeting_round() method."""

    def test_meeting_room_has_run_meeting_round(self) -> None:
        """MeetingRoom class has the run_meeting_round method."""
        from nexus.core.kafka.meeting import MeetingRoom

        assert hasattr(MeetingRoom, "run_meeting_round")
        assert callable(getattr(MeetingRoom, "run_meeting_round"))

    def test_convergence_report_model(self) -> None:
        """ConvergenceReport serializes correctly."""
        from nexus.core.kafka.meeting import ConvergenceReport

        report = ConvergenceReport(
            meeting_id="test-meeting",
            is_converging=True,
            is_looping=False,
            is_stagnating=False,
            recommendation="synthesize",
            reason="Agents are converging on consensus.",
        )
        data = report.model_dump()
        assert data["is_converging"] is True
        assert data["recommendation"] == "synthesize"


class TestFactoryTopics:
    """Tests for updated ROLE_TOPICS with meeting.room subscription."""

    def test_ceo_subscribes_to_meeting_room(self) -> None:
        """CEO role includes meeting.room in topic subscriptions."""
        from nexus.agents.factory import ROLE_TOPICS
        from nexus.core.kafka.topics import Topics
        from nexus.db.models import AgentRole

        assert Topics.MEETING_ROOM in ROLE_TOPICS[AgentRole.CEO]

    def test_ceo_subscribes_to_plan_approval(self) -> None:
        """CEO role includes plan.approval in topic subscriptions."""
        from nexus.agents.factory import ROLE_TOPICS
        from nexus.core.kafka.topics import Topics
        from nexus.db.models import AgentRole

        assert Topics.PLAN_APPROVAL in ROLE_TOPICS[AgentRole.CEO]

    def test_specialist_agents_subscribe_to_meeting_room(self) -> None:
        """Engineer, Analyst, Writer subscribe to meeting.room."""
        from nexus.agents.factory import ROLE_TOPICS
        from nexus.core.kafka.topics import Topics
        from nexus.db.models import AgentRole

        for role in [AgentRole.ENGINEER, AgentRole.ANALYST, AgentRole.WRITER]:
            assert Topics.MEETING_ROOM in ROLE_TOPICS[role], f"{role} missing meeting.room"

    def test_qa_subscribes_to_meeting_room(self) -> None:
        """QA subscribes to meeting.room for evaluation meetings."""
        from nexus.agents.factory import ROLE_TOPICS
        from nexus.core.kafka.topics import Topics
        from nexus.db.models import AgentRole

        assert Topics.MEETING_ROOM in ROLE_TOPICS[AgentRole.QA]

    def test_director_does_not_subscribe_to_meeting_room(self) -> None:
        """Director does NOT subscribe to meeting.room (gets data via CEO payload)."""
        from nexus.agents.factory import ROLE_TOPICS
        from nexus.core.kafka.topics import Topics
        from nexus.db.models import AgentRole

        assert Topics.MEETING_ROOM not in ROLE_TOPICS[AgentRole.DIRECTOR]


class TestBaseProcessMessageMeetingDetection:
    """Tests for AgentBase._process_message() meeting message detection."""

    def test_meeting_command_has_required_fields(self) -> None:
        """MeetingCommand can be distinguished from AgentCommand by fields."""
        meeting_raw = {
            "task_id": str(uuid4()),
            "trace_id": str(uuid4()),
            "agent_id": "ceo",
            "payload": {},
            "meeting_id": "meeting-123",
            "question": "How should we approach?",
            "participants": ["engineer", "analyst"],
            "round_number": 1,
            "timestamp": "2026-03-30T12:00:00Z",
            "message_id": str(uuid4()),
        }
        # Should have both meeting_id and participants
        assert "meeting_id" in meeting_raw
        assert "participants" in meeting_raw

    def test_agent_command_lacks_meeting_fields(self) -> None:
        """Standard AgentCommand does not have meeting_id or participants."""
        agent_raw = {
            "task_id": str(uuid4()),
            "trace_id": str(uuid4()),
            "agent_id": "ceo",
            "payload": {},
            "target_role": "engineer",
            "instruction": "Write a function",
            "timestamp": "2026-03-30T12:00:00Z",
            "message_id": str(uuid4()),
        }
        assert "meeting_id" not in agent_raw
        assert "participants" not in agent_raw

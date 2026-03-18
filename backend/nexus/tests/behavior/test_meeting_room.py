"""Behavior tests for the Meeting Room pattern.

Tests meeting lifecycle: create -> question -> response -> terminate,
timeout fallback, max rounds guard, and transcript generation.

Meeting state is stored in Redis db:0 (working memory).
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from nexus.core.kafka.meeting import (
    MeetingConfig,
    MeetingMessage,
    MeetingRoom,
    close_meeting,
    create_meeting,
)


@pytest.fixture
def meeting_config() -> MeetingConfig:
    """Create a test meeting configuration."""
    return MeetingConfig(
        parent_task_id=str(uuid4()),
        trace_id=str(uuid4()),
        topic="Should we use microservices or monolith?",
        participants=["analyst", "engineer"],
        max_rounds=3,
        timeout_seconds=300,
    )


class TestMeetingLifecycle:
    """Tests for the meeting room create -> debate -> terminate lifecycle."""

    @pytest.mark.asyncio
    @patch("nexus.kafka.meeting.redis_working", new_callable=AsyncMock)
    async def test_create_meeting(
        self,
        mock_redis: AsyncMock,
        meeting_config: MeetingConfig,
    ) -> None:
        """Meeting is created with correct config and stored in Redis."""
        mock_redis.set = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.delete = AsyncMock()

        room = await create_meeting(meeting_config)
        assert room.meeting_id == meeting_config.meeting_id
        assert room.current_round == 0
        assert len(room.messages) == 0
        assert not room.is_timed_out
        assert not room.is_max_rounds

        # Verify Redis set was called
        mock_redis.set.assert_called_once()

        # Cleanup
        await close_meeting(meeting_config.meeting_id)
        mock_redis.delete.assert_called_once()

    @pytest.mark.asyncio
    @patch("nexus.kafka.meeting.publish", new_callable=AsyncMock)
    @patch("nexus.kafka.meeting.redis_working", new_callable=AsyncMock)
    async def test_pose_question_increments_round(
        self,
        mock_redis: AsyncMock,
        mock_publish: AsyncMock,
        meeting_config: MeetingConfig,
    ) -> None:
        """Posing a question increments the round counter."""
        mock_redis.set = AsyncMock()
        room = await create_meeting(meeting_config)

        await room.pose_question(
            "What are the pros of microservices?",
            sender_id="ceo-001",
        )

        assert room.current_round == 1
        assert len(room.messages) == 1
        assert room.messages[0].message_type == "question"
        assert room.messages[0].sender_role == "ceo"
        mock_publish.assert_called_once()

        mock_redis.delete = AsyncMock()
        await close_meeting(meeting_config.meeting_id)

    @pytest.mark.asyncio
    @patch("nexus.kafka.meeting.publish", new_callable=AsyncMock)
    @patch("nexus.kafka.meeting.redis_working", new_callable=AsyncMock)
    async def test_submit_response(
        self,
        mock_redis: AsyncMock,
        mock_publish: AsyncMock,
        meeting_config: MeetingConfig,
    ) -> None:
        """Agent response is recorded and published."""
        mock_redis.set = AsyncMock()
        room = await create_meeting(meeting_config)
        room.current_round = 1

        await room.submit_response(
            "Microservices provide better scalability.",
            sender_role="analyst",
            sender_id="analyst-001",
        )

        assert len(room.messages) == 1
        assert room.messages[0].message_type == "response"
        assert room.messages[0].sender_role == "analyst"
        assert room.messages[0].round_number == 1

        mock_redis.delete = AsyncMock()
        await close_meeting(meeting_config.meeting_id)

    @pytest.mark.asyncio
    @patch("nexus.kafka.meeting.publish", new_callable=AsyncMock)
    @patch("nexus.kafka.meeting.redis_working", new_callable=AsyncMock)
    async def test_terminate_returns_result(
        self,
        mock_redis: AsyncMock,
        mock_publish: AsyncMock,
        meeting_config: MeetingConfig,
    ) -> None:
        """Termination returns MeetingResult with all messages."""
        mock_redis.set = AsyncMock()
        room = await create_meeting(meeting_config)
        room.current_round = 1

        await room.submit_response(
            "Test response",
            sender_role="analyst",
            sender_id="analyst-001",
        )

        result = await room.terminate(
            "We'll go with microservices.",
            sender_id="ceo-001",
        )

        assert result.meeting_id == meeting_config.meeting_id
        assert result.terminated_by == "ceo"
        assert result.rounds_completed == 1
        assert len(result.messages) == 2  # response + terminate

        mock_redis.delete = AsyncMock()
        await close_meeting(meeting_config.meeting_id)

    @pytest.mark.asyncio
    @patch("nexus.kafka.meeting.publish", new_callable=AsyncMock)
    @patch("nexus.kafka.meeting.redis_working", new_callable=AsyncMock)
    async def test_full_debate_round(
        self,
        mock_redis: AsyncMock,
        mock_publish: AsyncMock,
        meeting_config: MeetingConfig,
    ) -> None:
        """Full cycle: CEO question -> agent responses -> CEO concludes."""
        mock_redis.set = AsyncMock()
        room = await create_meeting(meeting_config)

        # Round 1: CEO asks
        await room.pose_question("Pros and cons?", sender_id="ceo-001")

        # Agents respond
        await room.submit_response(
            "Pro: scalability. Con: complexity.",
            sender_role="analyst",
            sender_id="analyst-001",
        )
        await room.submit_response(
            "Pro: independent deploys. Con: network overhead.",
            sender_role="engineer",
            sender_id="engineer-001",
        )

        # CEO concludes
        result = await room.terminate(
            "Go with microservices for core services.",
            sender_id="ceo-001",
        )

        assert result.rounds_completed == 1
        assert len(result.messages) == 4

        # Verify transcript
        transcript = room.get_transcript()
        assert "QUESTION" in transcript
        assert "ANALYST" in transcript
        assert "ENGINEER" in transcript
        assert "CONCLUSION" in transcript

        mock_redis.delete = AsyncMock()
        await close_meeting(meeting_config.meeting_id)


class TestMeetingGuards:
    """Tests for timeout and max-round guards."""

    def test_timeout_detection(self, meeting_config: MeetingConfig) -> None:
        """Meeting detects when it exceeds timeout."""
        meeting_config.timeout_seconds = 1
        room = MeetingRoom(meeting_config)

        assert not room.is_timed_out
        room._start_time = time.time() - 2  # Simulate past start
        assert room.is_timed_out

    def test_max_rounds_detection(self, meeting_config: MeetingConfig) -> None:
        """Meeting detects when max rounds are reached."""
        meeting_config.max_rounds = 2
        room = MeetingRoom(meeting_config)

        assert not room.is_max_rounds
        room.current_round = 2
        assert room.is_max_rounds

    def test_get_responses_for_round(self, meeting_config: MeetingConfig) -> None:
        """Can filter responses by round number."""
        room = MeetingRoom(meeting_config)

        # Add messages from two different rounds
        room.messages = [
            MeetingMessage(
                meeting_id=room.meeting_id,
                sender_role="analyst",
                sender_id="a1",
                message_type="response",
                content="Round 1 response",
                round_number=1,
            ),
            MeetingMessage(
                meeting_id=room.meeting_id,
                sender_role="engineer",
                sender_id="e1",
                message_type="response",
                content="Round 2 response",
                round_number=2,
            ),
        ]

        round_1 = room.get_responses_for_round(1)
        assert len(round_1) == 1
        assert round_1[0].sender_role == "analyst"

        round_2 = room.get_responses_for_round(2)
        assert len(round_2) == 1
        assert round_2[0].sender_role == "engineer"

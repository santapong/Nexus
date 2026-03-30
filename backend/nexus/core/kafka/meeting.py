"""Meeting room — temporary Kafka-based multi-agent debate space.

Provides a MeetingRoom abstraction for agents to exchange messages in
a structured debate. CEO creates and moderates meetings, poses questions,
reads agent responses, and decides when to close the meeting.

The Director agent monitors meetings for convergence and loop detection,
ensuring discussions terminate productively rather than cycling endlessly.

The meeting uses the existing `meeting.room` topic with a keyed partition
scheme: all messages for one meeting share the same key (meeting_id).
"""

from __future__ import annotations

import json
import time
from difflib import SequenceMatcher
from uuid import UUID, uuid4

import structlog
from pydantic import BaseModel, Field

from nexus.core.kafka.producer import publish
from nexus.core.kafka.schemas import KafkaMessage
from nexus.core.kafka.topics import Topics
from nexus.core.redis.clients import redis_working

logger = structlog.get_logger()

# ─── Constants ───────────────────────────────────────────────────────────────

DEFAULT_TIMEOUT_SECONDS = 300  # 5 minutes
MAX_ROUNDS = 10
SIMILARITY_THRESHOLD = 0.75  # Above this, responses are considered repetitive
STAGNATION_WINDOW = 2  # Consecutive rounds with no new ideas = stagnation


# ─── Meeting room models ────────────────────────────────────────────────────


class MeetingMessage(BaseModel):
    """A single message in a meeting room."""

    meeting_id: str
    sender_role: str
    sender_id: str
    message_type: str  # "question", "response", "decision", "terminate"
    content: str
    round_number: int = 0
    timestamp: float = Field(default_factory=time.time)


class MeetingConfig(BaseModel):
    """Configuration for a meeting room session."""

    meeting_id: str = Field(default_factory=lambda: str(uuid4()))
    parent_task_id: str
    trace_id: str
    topic: str  # The debate topic / question
    participants: list[str]  # Agent roles to invite
    max_rounds: int = MAX_ROUNDS
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS


class MeetingResult(BaseModel):
    """Result of a completed meeting room session."""

    meeting_id: str
    rounds_completed: int
    messages: list[MeetingMessage]
    conclusion: str
    terminated_by: str  # "ceo" | "timeout" | "max_rounds" | "director_convergence" | "director_loop"


class ConvergenceReport(BaseModel):
    """Director's analysis of meeting discussion health."""

    meeting_id: str
    is_converging: bool = False
    is_looping: bool = False
    is_stagnating: bool = False
    similarity_scores: list[float] = Field(default_factory=list)
    unique_ideas_per_round: list[int] = Field(default_factory=list)
    recommendation: str = ""  # "continue" | "synthesize" | "terminate"
    reason: str = ""


# ─── Meeting room manager ───────────────────────────────────────────────────


class MeetingRoom:
    """Manages a single meeting room session.

    The CEO creates a MeetingRoom, poses questions, collects responses
    from participating agents, and decides when to terminate.

    All messages are published to the `meeting.room` Kafka topic with
    the meeting_id as the partition key, ensuring message ordering.
    """

    def __init__(self, config: MeetingConfig) -> None:
        self.config = config
        self.messages: list[MeetingMessage] = []
        self.current_round = 0
        self._start_time = time.time()

    @property
    def meeting_id(self) -> str:
        """Return the meeting ID."""
        return self.config.meeting_id

    @property
    def is_timed_out(self) -> bool:
        """Check if the meeting has exceeded its timeout."""
        return (time.time() - self._start_time) > self.config.timeout_seconds

    @property
    def is_max_rounds(self) -> bool:
        """Check if the meeting has exceeded max rounds."""
        return self.current_round >= self.config.max_rounds

    async def publish_message(self, msg: MeetingMessage) -> None:
        """Publish a meeting message to the meeting.room topic.

        Args:
            msg: The message to publish.
        """
        kafka_msg = KafkaMessage(
            task_id=UUID(self.config.parent_task_id),
            trace_id=UUID(self.config.trace_id),
            agent_id=msg.sender_id,
            payload=msg.model_dump(),
        )
        await publish(
            Topics.MEETING_ROOM,
            kafka_msg,
            key=self.meeting_id,
        )
        self.messages.append(msg)

        logger.info(
            "meeting_message_published",
            meeting_id=self.meeting_id,
            sender_role=msg.sender_role,
            message_type=msg.message_type,
            round=msg.round_number,
        )

    async def pose_question(self, question: str, sender_id: str) -> None:
        """CEO poses a question to all participants.

        Args:
            question: The question or prompt for the debate round.
            sender_id: The CEO agent's ID.
        """
        self.current_round += 1
        msg = MeetingMessage(
            meeting_id=self.meeting_id,
            sender_role="ceo",
            sender_id=sender_id,
            message_type="question",
            content=question,
            round_number=self.current_round,
        )
        await self.publish_message(msg)

    async def submit_response(self, response: str, sender_role: str, sender_id: str) -> None:
        """An agent submits a response to the current question.

        Args:
            response: The agent's response text.
            sender_role: The agent's role (e.g., "analyst", "engineer").
            sender_id: The agent's ID.
        """
        msg = MeetingMessage(
            meeting_id=self.meeting_id,
            sender_role=sender_role,
            sender_id=sender_id,
            message_type="response",
            content=response,
            round_number=self.current_round,
        )
        await self.publish_message(msg)

    async def terminate(
        self, conclusion: str, sender_id: str, reason: str = "ceo"
    ) -> MeetingResult:
        """CEO terminates the meeting with a conclusion.

        Args:
            conclusion: The CEO's final summary/decision.
            sender_id: The CEO agent's ID.
            reason: Why terminated ("ceo", "timeout", "max_rounds").

        Returns:
            MeetingResult with all messages and the conclusion.
        """
        msg = MeetingMessage(
            meeting_id=self.meeting_id,
            sender_role="ceo",
            sender_id=sender_id,
            message_type="terminate",
            content=conclusion,
            round_number=self.current_round,
        )
        await self.publish_message(msg)

        logger.info(
            "meeting_terminated",
            meeting_id=self.meeting_id,
            rounds=self.current_round,
            total_messages=len(self.messages),
            reason=reason,
        )

        return MeetingResult(
            meeting_id=self.meeting_id,
            rounds_completed=self.current_round,
            messages=self.messages,
            conclusion=conclusion,
            terminated_by=reason,
        )

    def get_transcript(self) -> str:
        """Get a formatted transcript of all meeting messages.

        Returns:
            A readable string of all messages exchanged in the meeting.
        """
        lines: list[str] = []
        for msg in self.messages:
            prefix = f"[Round {msg.round_number}] {msg.sender_role.upper()}"
            if msg.message_type == "question":
                lines.append(f"{prefix} (QUESTION): {msg.content}")
            elif msg.message_type == "response":
                lines.append(f"{prefix}: {msg.content}")
            elif msg.message_type == "decision":
                lines.append(f"{prefix} (DECISION): {msg.content}")
            elif msg.message_type == "terminate":
                lines.append(f"{prefix} (CONCLUSION): {msg.content}")
        return "\n\n".join(lines)

    def get_responses_for_round(self, round_num: int) -> list[MeetingMessage]:
        """Get all agent responses for a specific round.

        Args:
            round_num: The round number to get responses for.

        Returns:
            List of response messages from that round.
        """
        return [
            m for m in self.messages if m.round_number == round_num and m.message_type == "response"
        ]

    def check_convergence(self) -> ConvergenceReport:
        """Analyze the meeting for convergence, loops, and stagnation.

        The Director agent calls this to decide whether to continue,
        synthesize a result, or terminate the meeting.

        Returns:
            ConvergenceReport with analysis and recommendation.
        """
        report = ConvergenceReport(meeting_id=self.meeting_id)

        if self.current_round < 2:
            report.recommendation = "continue"
            report.reason = "Too few rounds to assess convergence"
            return report

        # Compute per-round similarity to detect repetition
        round_texts: list[str] = []
        for r in range(1, self.current_round + 1):
            responses = self.get_responses_for_round(r)
            combined = " ".join(m.content for m in responses)
            round_texts.append(combined)

        # Compare consecutive rounds for similarity
        for i in range(1, len(round_texts)):
            sim = SequenceMatcher(None, round_texts[i - 1], round_texts[i]).ratio()
            report.similarity_scores.append(round(sim, 3))

        # Detect looping: high similarity across consecutive rounds
        recent_sims = report.similarity_scores[-STAGNATION_WINDOW:]
        if recent_sims and all(s >= SIMILARITY_THRESHOLD for s in recent_sims):
            report.is_looping = True

        # Detect stagnation: agents repeating their own arguments
        for r in range(1, self.current_round + 1):
            responses = self.get_responses_for_round(r)
            unique_contents: set[str] = set()
            for resp in responses:
                # Check if this response is substantially different from existing ones
                is_unique = True
                for existing in unique_contents:
                    if SequenceMatcher(None, existing, resp.content).ratio() >= SIMILARITY_THRESHOLD:
                        is_unique = False
                        break
                if is_unique:
                    unique_contents.add(resp.content)
            report.unique_ideas_per_round.append(len(unique_contents))

        # Check if unique ideas are declining
        if len(report.unique_ideas_per_round) >= STAGNATION_WINDOW:
            recent_ideas = report.unique_ideas_per_round[-STAGNATION_WINDOW:]
            if all(c <= 1 for c in recent_ideas):
                report.is_stagnating = True

        # Detect convergence: agents are agreeing (high intra-round similarity)
        if self.current_round >= 2:
            last_responses = self.get_responses_for_round(self.current_round)
            if len(last_responses) >= 2:
                contents = [m.content for m in last_responses]
                intra_sims: list[float] = []
                for i in range(len(contents)):
                    for j in range(i + 1, len(contents)):
                        intra_sims.append(
                            SequenceMatcher(None, contents[i], contents[j]).ratio()
                        )
                avg_intra = sum(intra_sims) / len(intra_sims) if intra_sims else 0.0
                if avg_intra >= SIMILARITY_THRESHOLD:
                    report.is_converging = True

        # Determine recommendation
        if report.is_looping:
            report.recommendation = "terminate"
            report.reason = (
                f"Discussion is looping — last {STAGNATION_WINDOW} rounds have "
                f">={SIMILARITY_THRESHOLD:.0%} similarity. No new insights being generated."
            )
        elif report.is_stagnating:
            report.recommendation = "synthesize"
            report.reason = (
                "Discussion is stagnating — agents are repeating arguments "
                "without adding new perspectives."
            )
        elif report.is_converging:
            report.recommendation = "synthesize"
            report.reason = "Agents are converging on a consensus. Ready for synthesis."
        elif self.is_max_rounds:
            report.recommendation = "terminate"
            report.reason = f"Maximum rounds ({self.config.max_rounds}) reached."
        elif self.is_timed_out:
            report.recommendation = "terminate"
            report.reason = f"Meeting timed out after {self.config.timeout_seconds}s."
        else:
            report.recommendation = "continue"
            report.reason = "Discussion is productive — new ideas emerging."

        logger.info(
            "meeting_convergence_checked",
            meeting_id=self.meeting_id,
            round=self.current_round,
            recommendation=report.recommendation,
            is_looping=report.is_looping,
            is_stagnating=report.is_stagnating,
            is_converging=report.is_converging,
        )

        return report

    async def run_meeting_round(
        self,
        question: str,
        sender_id: str,
        *,
        wait_seconds: float = 30.0,
        poll_interval: float = 2.0,
    ) -> list[MeetingMessage]:
        """Orchestrate a full meeting round: pose question, wait for responses.

        The CEO calls this to run one round of discussion. It publishes a
        MeetingCommand to the meeting.room topic and then polls Redis for
        responses from all participants until either all respond or
        wait_seconds expires.

        Args:
            question: The question to pose for this round.
            sender_id: The CEO agent's ID.
            wait_seconds: Max seconds to wait for all participant responses.
            poll_interval: Seconds between checking for new responses.

        Returns:
            List of response MeetingMessages received during this round.
        """
        await self.pose_question(question, sender_id)

        # Publish MeetingCommand so agents' consumer loops receive it
        from nexus.core.kafka.schemas import MeetingCommand as MeetingCmd

        meeting_cmd = MeetingCmd(
            task_id=UUID(self.config.parent_task_id),
            trace_id=UUID(self.config.trace_id),
            agent_id=sender_id,
            payload={"meeting_id": self.config.meeting_id},
            meeting_id=self.config.meeting_id,
            question=question,
            participants=self.config.participants,
            round_number=self.current_round,
        )
        await publish(Topics.MEETING_ROOM, meeting_cmd, key=self.meeting_id)

        # Wait for participant responses by polling Redis meeting state
        expected = len(self.config.participants)
        elapsed = 0.0
        import asyncio

        while elapsed < wait_seconds:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            # Re-load meeting state from Redis to check for new responses
            updated = await get_meeting(self.meeting_id)
            if updated is None:
                break

            responses = updated.get_responses_for_round(self.current_round)
            # Sync our local state with Redis
            self.messages = updated.messages

            if len(responses) >= expected:
                logger.info(
                    "meeting_round_all_responded",
                    meeting_id=self.meeting_id,
                    round=self.current_round,
                    responses=len(responses),
                    expected=expected,
                )
                break

        responses = self.get_responses_for_round(self.current_round)
        logger.info(
            "meeting_round_completed",
            meeting_id=self.meeting_id,
            round=self.current_round,
            responses=len(responses),
            expected=expected,
            timed_out=elapsed >= wait_seconds,
        )

        # Save updated state
        await save_meeting(self)

        return responses

    def get_best_contributions(self) -> list[MeetingMessage]:
        """Extract the most substantive contributions from the meeting.

        Returns responses sorted by content length (as a proxy for depth),
        deduplicated to remove near-identical responses. The Director uses
        this to synthesize the best final output.

        Returns:
            List of the most unique and substantive meeting messages.
        """
        all_responses = [m for m in self.messages if m.message_type == "response"]
        if not all_responses:
            return []

        # Sort by content length descending (longer = more detailed)
        all_responses.sort(key=lambda m: len(m.content), reverse=True)

        # Deduplicate: keep only responses that are sufficiently different
        best: list[MeetingMessage] = []
        for resp in all_responses:
            is_unique = True
            for kept in best:
                if SequenceMatcher(None, kept.content, resp.content).ratio() >= SIMILARITY_THRESHOLD:
                    is_unique = False
                    break
            if is_unique:
                best.append(resp)

        return best


# ─── Meeting registry — Redis db:0 backed ───────────────────────────────────

_MEETING_KEY_PREFIX = "meeting:"


def _redis_key(meeting_id: str) -> str:
    return f"{_MEETING_KEY_PREFIX}{meeting_id}"


def _serialize_room(room: MeetingRoom) -> str:
    """Serialize a MeetingRoom to JSON for Redis storage."""
    return json.dumps(
        {
            "config": room.config.model_dump(),
            "messages": [m.model_dump() for m in room.messages],
            "current_round": room.current_round,
            "start_time": room._start_time,
        }
    )


def _deserialize_room(data: str) -> MeetingRoom:
    """Deserialize a MeetingRoom from Redis JSON."""
    parsed = json.loads(data)
    config = MeetingConfig(**parsed["config"])
    room = MeetingRoom(config)
    room.messages = [MeetingMessage(**m) for m in parsed["messages"]]
    room.current_round = parsed["current_round"]
    room._start_time = parsed["start_time"]
    return room


async def create_meeting(config: MeetingConfig) -> MeetingRoom:
    """Create and register a new meeting room in Redis.

    Args:
        config: The meeting configuration.

    Returns:
        A new MeetingRoom instance.
    """
    room = MeetingRoom(config)
    ttl = config.timeout_seconds + 60
    await redis_working.set(
        _redis_key(config.meeting_id),
        _serialize_room(room),
        ex=ttl,
    )

    logger.info(
        "meeting_created",
        meeting_id=config.meeting_id,
        parent_task_id=config.parent_task_id,
        participants=config.participants,
        max_rounds=config.max_rounds,
        timeout_seconds=config.timeout_seconds,
    )

    return room


async def get_meeting(meeting_id: str) -> MeetingRoom | None:
    """Get an active meeting room by ID from Redis.

    Args:
        meeting_id: The meeting ID to look up.

    Returns:
        MeetingRoom if found, None otherwise.
    """
    data = await redis_working.get(_redis_key(meeting_id))
    if data is None:
        return None
    return _deserialize_room(data if isinstance(data, str) else data.decode("utf-8"))


async def save_meeting(room: MeetingRoom) -> None:
    """Persist updated meeting state to Redis.

    Call after modifying a MeetingRoom (e.g., after publish_message).

    Args:
        room: The meeting room to save.
    """
    remaining_ttl = await redis_working.ttl(_redis_key(room.meeting_id))
    ttl = max(remaining_ttl, 60) if remaining_ttl > 0 else 360
    await redis_working.set(
        _redis_key(room.meeting_id),
        _serialize_room(room),
        ex=ttl,
    )


async def close_meeting(meeting_id: str) -> None:
    """Remove a meeting room from Redis.

    Args:
        meeting_id: The meeting ID to close.
    """
    await redis_working.delete(_redis_key(meeting_id))
    logger.info("meeting_closed", meeting_id=meeting_id)

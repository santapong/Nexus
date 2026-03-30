from __future__ import annotations


class Topics:
    """All Kafka topic names. Single source of truth.

    No hardcoded topic strings anywhere else in the codebase.
    """

    TASK_QUEUE = "task.queue"
    TASK_RESULTS = "task.results"
    TASK_REVIEW_QUEUE = "task.review_queue"
    AGENT_COMMANDS = "agent.commands"
    AGENT_RESPONSES = "agent.responses"
    MEETING_ROOM = "meeting.room"
    MEMORY_UPDATES = "memory.updates"
    TOOLS_REQUESTS = "tools.requests"
    TOOLS_RESPONSES = "tools.responses"
    AUDIT_LOG = "audit.log"
    AGENT_HEARTBEAT = "agent.heartbeat"
    HUMAN_INPUT_NEEDED = "human.input_needed"
    A2A_INBOUND = "a2a.inbound"
    PROMPT_IMPROVEMENT = "prompt.improvement_requests"
    PROMPT_BENCHMARK = "prompt.benchmark_requests"
    PROMPT_PROPOSALS = "prompt.proposals"
    DIRECTOR_REVIEW = "director.review"
    PLAN_APPROVAL = "plan.approval"

    # Dead letter topics — failed messages after max retries
    DEAD_LETTER_SUFFIX = ".dead_letter"
    TASK_QUEUE_DL = "task.queue.dead_letter"
    AGENT_COMMANDS_DL = "agent.commands.dead_letter"
    AGENT_RESPONSES_DL = "agent.responses.dead_letter"
    TASK_RESULTS_DL = "task.results.dead_letter"
    A2A_INBOUND_DL = "a2a.inbound.dead_letter"

    @classmethod
    def dead_letter_for(cls, topic: str) -> str:
        """Return the dead letter topic name for a given source topic.

        Args:
            topic: The original topic name.

        Returns:
            Topic name with dead letter suffix appended.
        """
        return f"{topic}{cls.DEAD_LETTER_SUFFIX}"

    @classmethod
    def all_topics(cls) -> list[str]:
        """Return all topic names for creation at startup."""
        return [
            v
            for k, v in vars(cls).items()
            if not k.startswith("_")
            and isinstance(v, str)
            and k not in ("all_topics", "dead_letter_for", "DEAD_LETTER_SUFFIX")
        ]

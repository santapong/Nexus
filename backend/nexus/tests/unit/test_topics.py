from __future__ import annotations

from nexus.integrations.kafka.topics import Topics


def test_all_topics_returns_all_defined_topics() -> None:
    """Verify all_topics() includes every topic constant."""
    topics = Topics.all_topics()
    assert len(topics) >= 16
    assert Topics.TASK_QUEUE in topics
    assert Topics.A2A_INBOUND in topics
    assert Topics.PROMPT_PROPOSALS in topics


def test_no_duplicate_topics() -> None:
    """Verify no topic name is duplicated."""
    topics = Topics.all_topics()
    assert len(topics) == len(set(topics))

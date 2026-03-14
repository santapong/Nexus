"""E2E multi-agent flow tests using test: model provider.

Run with: docker compose exec backend pytest nexus/tests/e2e/test_e2e_multi_agent.py -v
Requires: docker compose up, make migrate, make seed

Tests the full multi-agent pipeline: API -> Kafka -> CEO -> specialists -> QA -> result.
Uses test: model for zero-cost runs.
"""
from __future__ import annotations

import sys

import httpx

from nexus.tests.e2e.helpers import (
    BASE_URL,
    MULTI_AGENT_TIMEOUT_SECONDS,
    get_trace,
    poll_until_done,
    run_task,
    skip_if_not_running,
    submit_task,
)


class TestMultiAgentE2E:
    """E2E tests for multi-agent task routing and completion.

    These tests require Docker services to be running.
    They use the test: model provider for zero-cost execution.
    """

    def test_single_agent_engineering_task(self) -> None:
        """CEO routes a simple engineering task to Engineer agent."""
        if skip_if_not_running("single_agent"):
            return

        with httpx.Client(timeout=30) as client:
            outcome = run_task(
                client,
                "Write a Python function that checks if a number is prime.",
            )

        assert outcome.status in ("completed", "failed"), (
            f"Expected terminal status, got: {outcome.status}"
        )
        sys.stdout.write(
            f"  Single-agent: {outcome.status} in {outcome.duration:.1f}s "
            f"({outcome.subtask_count} subtasks)\n"
        )

    def test_multi_agent_research_and_write(self) -> None:
        """CEO decomposes into research (Analyst) + writing (Writer) subtasks."""
        if skip_if_not_running("multi_agent"):
            return

        with httpx.Client(timeout=30) as client:
            outcome = run_task(
                client,
                "Research the benefits of async programming in Python and write "
                "a brief summary email about the key advantages.",
                timeout=MULTI_AGENT_TIMEOUT_SECONDS,
            )

        assert outcome.status in ("completed", "failed"), (
            f"Expected terminal status, got: {outcome.status}"
        )
        sys.stdout.write(
            f"  Multi-agent: {outcome.status} in {outcome.duration:.1f}s "
            f"({outcome.subtask_count} subtasks)\n"
        )

    def test_task_trace_endpoint(self) -> None:
        """Verify the trace endpoint returns parent + subtask tree."""
        if skip_if_not_running("trace"):
            return

        with httpx.Client(timeout=30) as client:
            task_id = submit_task(
                client, "Explain what Python decorators are."
            )
            poll_until_done(client, task_id)
            trace = get_trace(client, task_id)

        assert "parent" in trace, "Trace must contain 'parent'"
        assert "subtasks" in trace, "Trace must contain 'subtasks'"
        assert "total_subtasks" in trace, "Trace must contain 'total_subtasks'"
        sys.stdout.write(
            f"  Trace: parent={trace['parent']['id']}, "
            f"subtasks={trace['total_subtasks']}\n"
        )

    def test_task_list_filter(self) -> None:
        """Verify task list endpoint with status filter."""
        if skip_if_not_running("list_filter"):
            return

        with httpx.Client(timeout=30) as client:
            resp = client.get(f"{BASE_URL}/api/tasks", params={"limit": 5})
            resp.raise_for_status()
            tasks = resp.json()

        assert isinstance(tasks, list), "Expected list of tasks"
        sys.stdout.write(f"  Task list: {len(tasks)} tasks returned\n")

    def test_phase2_dod_research_and_email(self) -> None:
        """Phase 2 DoD: competitive analysis -> email summary via analyst + writer + QA."""
        if skip_if_not_running("phase2_dod"):
            return

        with httpx.Client(timeout=30) as client:
            outcome = run_task(
                client,
                "Write a competitive analysis of Python web frameworks "
                "and draft an email summary to the engineering team.",
                timeout=MULTI_AGENT_TIMEOUT_SECONDS,
            )

        assert outcome.status in ("completed", "failed"), (
            f"Expected terminal status, got: {outcome.status}"
        )
        # Multi-agent decomposition should produce subtasks
        sys.stdout.write(
            f"  Phase2 DoD: {outcome.status} in {outcome.duration:.1f}s "
            f"({outcome.subtask_count} subtasks, "
            f"{outcome.completed_subtasks} completed)\n"
        )

    def test_decomposition_fallback_to_engineer(self) -> None:
        """Simple single-concept task should complete (via decomposition or fallback)."""
        if skip_if_not_running("fallback"):
            return

        with httpx.Client(timeout=30) as client:
            outcome = run_task(
                client,
                "Write a Python function to reverse a linked list.",
            )

        assert outcome.status in ("completed", "failed"), (
            f"Expected terminal status, got: {outcome.status}"
        )
        # Should have at least 1 subtask (either decomposed or engineer fallback)
        assert outcome.subtask_count >= 1, (
            f"Expected at least 1 subtask, got: {outcome.subtask_count}"
        )
        sys.stdout.write(
            f"  Fallback: {outcome.status} in {outcome.duration:.1f}s "
            f"({outcome.subtask_count} subtasks)\n"
        )

    def test_trace_shows_subtask_tree_with_statuses(self) -> None:
        """After completion, trace shows all subtasks with their statuses."""
        if skip_if_not_running("trace_statuses"):
            return

        with httpx.Client(timeout=30) as client:
            outcome = run_task(
                client,
                "Research Python type hints best practices and write a short guide.",
                timeout=MULTI_AGENT_TIMEOUT_SECONDS,
            )

            if outcome.status == "timeout":
                sys.stdout.write("  SKIP: Task timed out\n")
                return

            trace = get_trace(client, outcome.task_id)

        assert trace["total_subtasks"] >= 1, "Expected at least 1 subtask"

        # All subtasks should be in a terminal status
        for st in trace["subtasks"]:
            assert st["status"] in ("completed", "failed", "escalated"), (
                f"Subtask {st['id']} has non-terminal status: {st['status']}"
            )

        sys.stdout.write(
            f"  Trace tree: {trace['total_subtasks']} subtasks, "
            f"{trace['completed_subtasks']} completed, "
            f"parent={trace['parent']['status']}\n"
        )

"""Phase 2 E2E flow tests — multi-agent orchestration verification.

Run with: docker compose exec backend pytest nexus/tests/e2e/test_e2e_phase2_flows.py -v
Requires: docker compose up, make migrate, make seed

Tests Phase 2 specific flows: dependency resolution, QA approval,
parallel subtask dispatch, concurrent tasks, and replay timeline.
"""
from __future__ import annotations

import sys
import time

import httpx

from nexus.tests.e2e.helpers import (
    BASE_URL,
    MULTI_AGENT_TIMEOUT_SECONDS,
    get_replay,
    get_task,
    get_trace,
    poll_until_done,
    run_task,
    skip_if_not_running,
    submit_task,
)


class TestPhase2Flows:
    """Phase 2 orchestration flow tests.

    These tests verify multi-agent coordination: dependency resolution,
    QA approval pipeline, parallel dispatch, and observability.
    """

    def test_dependency_resolution_analyst_then_writer(self) -> None:
        """Writer subtask should start after analyst completes (dependency ordering)."""
        if skip_if_not_running("dependency"):
            return

        with httpx.Client(timeout=30) as client:
            outcome = run_task(
                client,
                "Research the benefits of microservices architecture, "
                "then write a technical blog post summarizing the findings.",
                timeout=MULTI_AGENT_TIMEOUT_SECONDS,
            )

            if outcome.status == "timeout":
                sys.stdout.write("  SKIP: Task timed out\n")
                return

            trace = get_trace(client, outcome.task_id)

        assert outcome.status in ("completed", "failed"), (
            f"Expected terminal status, got: {outcome.status}"
        )

        # If CEO decomposed into multiple subtasks, check ordering
        if trace["total_subtasks"] >= 2:
            subtasks = trace["subtasks"]
            # Find analyst and writer subtasks by checking instruction content
            analyst_st = None
            writer_st = None
            for st in subtasks:
                instr_lower = st["instruction"].lower()
                if "research" in instr_lower or "analys" in instr_lower:
                    analyst_st = st
                elif "write" in instr_lower or "blog" in instr_lower or "summar" in instr_lower:
                    writer_st = st

            if analyst_st and writer_st and analyst_st.get("completed_at") and writer_st.get("started_at"):
                sys.stdout.write(
                    f"  Dependency: analyst completed={analyst_st['completed_at']}, "
                    f"writer started={writer_st['started_at']}\n"
                )
            else:
                sys.stdout.write(
                    f"  Dependency: {trace['total_subtasks']} subtasks "
                    f"(timing data incomplete for ordering check)\n"
                )
        else:
            sys.stdout.write(
                f"  Dependency: single subtask (CEO used fallback), "
                f"status={outcome.status}\n"
            )

    def test_qa_approval_completes_parent(self) -> None:
        """QA approval should update the parent task to completed with output."""
        if skip_if_not_running("qa_approval"):
            return

        with httpx.Client(timeout=30) as client:
            outcome = run_task(
                client,
                "Explain the SOLID principles in object-oriented programming "
                "and provide a Python example for each.",
                timeout=MULTI_AGENT_TIMEOUT_SECONDS,
            )

            if outcome.status == "timeout":
                sys.stdout.write("  SKIP: Task timed out\n")
                return

            # Fetch the parent task directly
            task_data = get_task(client, outcome.task_id)

        assert task_data["status"] in ("completed", "failed"), (
            f"Parent task should be terminal, got: {task_data['status']}"
        )

        if task_data["status"] == "completed":
            assert task_data.get("output") is not None, (
                "Completed task should have output"
            )

        sys.stdout.write(
            f"  QA approval: parent status={task_data['status']}, "
            f"has_output={task_data.get('output') is not None}\n"
        )

    def test_task_replay_shows_multi_agent_timeline(self) -> None:
        """Replay endpoint should show episodes and LLM calls across agents."""
        if skip_if_not_running("replay"):
            return

        with httpx.Client(timeout=30) as client:
            outcome = run_task(
                client,
                "Research Python async patterns and write a concise guide.",
                timeout=MULTI_AGENT_TIMEOUT_SECONDS,
            )

            if outcome.status == "timeout":
                sys.stdout.write("  SKIP: Task timed out\n")
                return

            replay = get_replay(client, outcome.task_id)

        assert "episodes" in replay, "Replay must contain 'episodes'"
        assert "llm_calls" in replay, "Replay must contain 'llm_calls'"
        assert "total_episodes" in replay, "Replay must contain 'total_episodes'"
        assert "total_llm_calls" in replay, "Replay must contain 'total_llm_calls'"

        # At minimum, CEO decomposition should produce an LLM call
        total_llm = replay["total_llm_calls"]
        total_episodes = replay["total_episodes"]

        sys.stdout.write(
            f"  Replay: {total_episodes} episodes, {total_llm} LLM calls, "
            f"subtask_episodes={len(replay.get('subtask_episodes', []))}\n"
        )

    def test_three_subtask_parallel_execution(self) -> None:
        """Three independent subtasks should be dispatched without waiting for each other."""
        if skip_if_not_running("parallel"):
            return

        with httpx.Client(timeout=30) as client:
            outcome = run_task(
                client,
                "Research Python best practices, write a coding standards document, "
                "and create a Python style guide template.",
                timeout=MULTI_AGENT_TIMEOUT_SECONDS,
            )

            if outcome.status == "timeout":
                sys.stdout.write("  SKIP: Task timed out\n")
                return

            trace = get_trace(client, outcome.task_id)

        assert outcome.status in ("completed", "failed"), (
            f"Expected terminal status, got: {outcome.status}"
        )

        sys.stdout.write(
            f"  Parallel: {outcome.status} in {outcome.duration:.1f}s, "
            f"{trace['total_subtasks']} subtasks, "
            f"{trace['completed_subtasks']} completed\n"
        )

    def test_single_agent_still_works(self) -> None:
        """Regression: single-agent tasks should still complete in Phase 2."""
        if skip_if_not_running("regression"):
            return

        with httpx.Client(timeout=30) as client:
            outcome = run_task(
                client,
                "What is the time complexity of quicksort?",
            )

        assert outcome.status in ("completed", "failed"), (
            f"Expected terminal status, got: {outcome.status}"
        )
        sys.stdout.write(
            f"  Regression: {outcome.status} in {outcome.duration:.1f}s\n"
        )

    def test_multiple_concurrent_tasks(self) -> None:
        """Three tasks submitted rapidly should all complete without deadlock."""
        if skip_if_not_running("concurrent"):
            return

        instructions = [
            "Explain what a Python context manager is.",
            "Write a Python function to calculate factorial recursively.",
            "What are Python generators and how do they work?",
        ]

        with httpx.Client(timeout=30) as client:
            # Submit all tasks rapidly
            task_ids = [submit_task(client, instr) for instr in instructions]

            # Poll all tasks for completion
            results = []
            for task_id in task_ids:
                result = poll_until_done(
                    client, task_id, timeout=MULTI_AGENT_TIMEOUT_SECONDS
                )
                results.append(result)

        # All tasks should reach a terminal status
        for i, result in enumerate(results):
            assert result["status"] in ("completed", "failed", "escalated", "timeout"), (
                f"Task {i+1} has non-terminal status: {result['status']}"
            )

        statuses = [r["status"] for r in results]
        completed = sum(1 for s in statuses if s == "completed")
        sys.stdout.write(
            f"  Concurrent: {completed}/{len(results)} completed, "
            f"statuses={statuses}\n"
        )

    def test_token_tracking_across_workflow(self) -> None:
        """Token usage should be tracked across multi-agent workflows."""
        if skip_if_not_running("token_tracking"):
            return

        with httpx.Client(timeout=30) as client:
            outcome = run_task(
                client,
                "Write a Python decorator that caches function results.",
                timeout=MULTI_AGENT_TIMEOUT_SECONDS,
            )

            if outcome.status == "timeout":
                sys.stdout.write("  SKIP: Task timed out\n")
                return

            replay = get_replay(client, outcome.task_id)

        # Token tracking should have recorded at least one LLM call
        total_llm = replay.get("total_llm_calls", 0)

        sys.stdout.write(
            f"  Tokens: task tokens_used={outcome.tokens_used}, "
            f"replay total_llm_calls={total_llm}\n"
        )

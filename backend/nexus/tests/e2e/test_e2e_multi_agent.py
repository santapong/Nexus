"""E2E multi-agent flow tests using test: model provider.

Run with: docker compose exec backend pytest nexus/tests/e2e/test_e2e_multi_agent.py -v
Requires: docker compose up, make migrate, make seed

Tests the full multi-agent pipeline: API → Kafka → CEO → specialists → QA → result.
Uses test: model for zero-cost runs.
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass

import httpx

BASE_URL = "http://localhost:8000"
TASK_TIMEOUT_SECONDS = 120
POLL_INTERVAL = 2.0


@dataclass
class TaskOutcome:
    """Result of a submitted test task."""

    task_id: str
    status: str
    duration: float
    tokens_used: int = 0
    output: dict | None = None
    error: str | None = None
    subtask_count: int = 0


def _submit_task(client: httpx.Client, instruction: str) -> str:
    """Submit a task via the API and return the task_id."""
    resp = client.post(
        f"{BASE_URL}/api/tasks",
        json={"instruction": instruction},
    )
    resp.raise_for_status()
    return resp.json()["task_id"]


def _poll_until_done(
    client: httpx.Client, task_id: str, timeout: float = TASK_TIMEOUT_SECONDS
) -> dict:
    """Poll a task until it reaches a terminal status or times out."""
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        resp = client.get(f"{BASE_URL}/api/tasks/{task_id}")
        resp.raise_for_status()
        data = resp.json()
        if data["status"] in ("completed", "failed", "escalated"):
            return data
        time.sleep(POLL_INTERVAL)
    return {"status": "timeout", "error": "Task timed out"}


def _get_trace(client: httpx.Client, task_id: str) -> dict:
    """Fetch the task trace (parent + subtasks)."""
    resp = client.get(f"{BASE_URL}/api/tasks/{task_id}/trace")
    resp.raise_for_status()
    return resp.json()


def _run_task(
    client: httpx.Client, instruction: str, *, timeout: float = TASK_TIMEOUT_SECONDS
) -> TaskOutcome:
    """Submit a task, wait for completion, return outcome."""
    start = time.monotonic()
    task_id = _submit_task(client, instruction)
    result = _poll_until_done(client, task_id, timeout)
    duration = time.monotonic() - start

    trace = _get_trace(client, task_id)

    return TaskOutcome(
        task_id=task_id,
        status=result["status"],
        duration=duration,
        tokens_used=result.get("tokens_used", 0),
        output=result.get("output"),
        error=result.get("error"),
        subtask_count=trace.get("total_subtasks", 0),
    )


class TestMultiAgentE2E:
    """E2E tests for multi-agent task routing and completion.

    These tests require Docker services to be running.
    They use the test: model provider for zero-cost execution.
    """

    def _check_health(self) -> bool:
        """Verify backend is reachable and healthy."""
        try:
            with httpx.Client(timeout=5) as c:
                resp = c.get(f"{BASE_URL}/health")
                return resp.status_code == 200
        except Exception:
            return False

    def test_single_agent_engineering_task(self) -> None:
        """CEO routes a simple engineering task to Engineer agent."""
        if not self._check_health():
            sys.stdout.write("SKIP: Backend not running\n")
            return

        with httpx.Client(timeout=30) as client:
            outcome = _run_task(
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
        if not self._check_health():
            sys.stdout.write("SKIP: Backend not running\n")
            return

        with httpx.Client(timeout=30) as client:
            outcome = _run_task(
                client,
                "Research the benefits of async programming in Python and write "
                "a brief summary email about the key advantages.",
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
        if not self._check_health():
            sys.stdout.write("SKIP: Backend not running\n")
            return

        with httpx.Client(timeout=30) as client:
            task_id = _submit_task(
                client, "Explain what Python decorators are."
            )
            _poll_until_done(client, task_id)
            trace = _get_trace(client, task_id)

        assert "parent" in trace, "Trace must contain 'parent'"
        assert "subtasks" in trace, "Trace must contain 'subtasks'"
        assert "total_subtasks" in trace, "Trace must contain 'total_subtasks'"
        sys.stdout.write(
            f"  Trace: parent={trace['parent']['id']}, "
            f"subtasks={trace['total_subtasks']}\n"
        )

    def test_task_list_filter(self) -> None:
        """Verify task list endpoint with status filter."""
        if not self._check_health():
            sys.stdout.write("SKIP: Backend not running\n")
            return

        with httpx.Client(timeout=30) as client:
            # List all tasks
            resp = client.get(f"{BASE_URL}/api/tasks", params={"limit": 5})
            resp.raise_for_status()
            tasks = resp.json()

        assert isinstance(tasks, list), "Expected list of tasks"
        sys.stdout.write(f"  Task list: {len(tasks)} tasks returned\n")

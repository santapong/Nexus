"""Shared E2E test helpers for NEXUS multi-agent tests.

Provides common utilities for submitting tasks via HTTP, polling for
completion, and checking trace/replay data. All E2E tests import from here.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

BASE_URL = "http://localhost:8000"
TASK_TIMEOUT_SECONDS = 120
MULTI_AGENT_TIMEOUT_SECONDS = 180
POLL_INTERVAL = 2.0
DELAY_BETWEEN_TASKS = 5.0


@dataclass
class TaskOutcome:
    """Result of a submitted test task."""

    task_id: str
    status: str
    duration: float
    tokens_used: int = 0
    output: dict[str, Any] | None = None
    error: str | None = None
    subtask_count: int = 0
    completed_subtasks: int = 0
    subtasks: list[dict[str, Any]] = field(default_factory=list)


def check_health() -> bool:
    """Verify backend is reachable and healthy."""
    try:
        with httpx.Client(timeout=5) as c:
            resp = c.get(f"{BASE_URL}/health")
            return resp.status_code == 200
    except Exception:
        return False


def submit_task(client: httpx.Client, instruction: str) -> str:
    """Submit a task via the API and return the task_id."""
    resp = client.post(
        f"{BASE_URL}/api/tasks",
        json={"instruction": instruction},
    )
    resp.raise_for_status()
    result: str = str(resp.json()["task_id"])
    return result


def poll_until_done(
    client: httpx.Client,
    task_id: str,
    timeout: float = TASK_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Poll a task until it reaches a terminal status or times out."""
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        resp = client.get(f"{BASE_URL}/api/tasks/{task_id}")
        resp.raise_for_status()
        data: dict[str, Any] = dict(resp.json())
        if data["status"] in ("completed", "failed", "escalated"):
            return data
        time.sleep(POLL_INTERVAL)
    return {"status": "timeout", "error": "Task timed out"}


def get_task(client: httpx.Client, task_id: str) -> dict[str, Any]:
    """Fetch a single task by ID."""
    resp = client.get(f"{BASE_URL}/api/tasks/{task_id}")
    resp.raise_for_status()
    result: dict[str, Any] = dict(resp.json())
    return result


def get_trace(client: httpx.Client, task_id: str) -> dict[str, Any]:
    """Fetch the task trace (parent + subtasks)."""
    resp = client.get(f"{BASE_URL}/api/tasks/{task_id}/trace")
    resp.raise_for_status()
    result: dict[str, Any] = dict(resp.json())
    return result


def get_replay(client: httpx.Client, task_id: str) -> dict[str, Any]:
    """Fetch the task replay (episodic memory + LLM usage timeline)."""
    resp = client.get(f"{BASE_URL}/api/tasks/{task_id}/replay")
    resp.raise_for_status()
    result: dict[str, Any] = dict(resp.json())
    return result


def run_task(
    client: httpx.Client,
    instruction: str,
    *,
    timeout: float = TASK_TIMEOUT_SECONDS,
) -> TaskOutcome:
    """Submit a task, wait for completion, return outcome with trace data."""
    start = time.monotonic()
    task_id = submit_task(client, instruction)
    result = poll_until_done(client, task_id, timeout)
    duration = time.monotonic() - start

    trace = get_trace(client, task_id)

    return TaskOutcome(
        task_id=task_id,
        status=result["status"],
        duration=duration,
        tokens_used=result.get("tokens_used", 0),
        output=result.get("output"),
        error=result.get("error"),
        subtask_count=trace.get("total_subtasks", 0),
        completed_subtasks=trace.get("completed_subtasks", 0),
        subtasks=trace.get("subtasks", []),
    )


def skip_if_not_running(label: str = "") -> bool:
    """Check health and print skip message if backend is down. Returns True if should skip."""
    if not check_health():
        sys.stdout.write(f"SKIP{': ' + label if label else ''}: Backend not running\n")
        return True
    return False

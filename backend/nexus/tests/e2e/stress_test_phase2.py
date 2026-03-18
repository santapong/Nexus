"""20-task mixed stress test for Phase 2 verification.

Run with: python -m nexus.tests.e2e.stress_test_phase2
Requires: docker compose up, make migrate, make seed

Submits 20 tasks across 5 categories (single-agent, research, multi-agent,
sequential dependencies, edge cases) via HTTP, polls for completion,
and reports per-category pass rates. Gate: >= 85% overall pass rate.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

BASE_URL = "http://localhost:8000"
TASK_TIMEOUT_SECONDS = 180
DELAY_BETWEEN_TASKS = 5.0

# ---- Task definitions: 20 tasks, 4 per category ----

TASKS: list[dict[str, str]] = [
    # Category 1: Single-agent engineering (tasks 1-4)
    {
        "instruction": "Write a Python function to check if a string is a palindrome.",
        "category": "single_engineering",
    },
    {
        "instruction": (
            "Write a Python class that implements a simple stack with push, pop, and peek."
        ),
        "category": "single_engineering",
    },
    {
        "instruction": "Explain what a Python list comprehension is with a simple example.",
        "category": "single_engineering",
    },
    {
        "instruction": "Write a Python function that merges two sorted lists into one sorted list.",
        "category": "single_engineering",
    },
    # Category 2: Single-agent research/writing (tasks 5-8)
    {
        "instruction": "Explain the GIL (Global Interpreter Lock) in Python.",
        "category": "single_research",
    },
    {
        "instruction": "What are the main differences between threads and processes in Python?",
        "category": "single_research",
    },
    {
        "instruction": "Explain the Observer design pattern and when to use it.",
        "category": "single_research",
    },
    {
        "instruction": "What is dependency injection and why is it useful?",
        "category": "single_research",
    },
    # Category 3: Multi-agent decomposition (tasks 9-13)
    {
        "instruction": (
            "Research Python async patterns and write a working asyncio example with gather."
        ),
        "category": "multi_agent",
    },
    {
        "instruction": (
            "Research REST API best practices and write a Python example implementing them."
        ),
        "category": "multi_agent",
    },
    {
        "instruction": (
            "Analyze the pros and cons of microservices and write a summary email about it."
        ),
        "category": "multi_agent",
    },
    {
        "instruction": "Research Python testing frameworks and write a comparison guide.",
        "category": "multi_agent",
    },
    {
        "instruction": (
            "Research database indexing strategies and draft a technical recommendation."
        ),
        "category": "multi_agent",
    },
    # Category 4: Sequential dependencies (tasks 14-17)
    {
        "instruction": (
            "Research Python type hints best practices, then write"
            " a style guide based on the findings."
        ),
        "category": "sequential",
    },
    {
        "instruction": (
            "Analyze the current trends in AI development, then draft"
            " a strategy document based on the analysis."
        ),
        "category": "sequential",
    },
    {
        "instruction": (
            "Research GraphQL vs REST API tradeoffs, then write a"
            " technical decision document recommending one."
        ),
        "category": "sequential",
    },
    {
        "instruction": (
            "Research Python logging best practices, then write an"
            " implementation guide with code examples."
        ),
        "category": "sequential",
    },
    # Category 5: Edge cases (tasks 18-20)
    {"instruction": "Hello.", "category": "edge_case"},
    {
        "instruction": (
            "Fix this code: `def avg(lst): return sum(lst) / len(lst)`"
            " -- it crashes on empty lists."
        ),
        "category": "edge_case",
    },
    {
        "instruction": "Write a comprehensive Python REST API client class with retry logic, "
        "exponential backoff, timeout handling, circuit breaker pattern, "
        "request/response logging, header management, authentication support, "
        "and connection pooling. Include full type annotations and docstrings.",
        "category": "edge_case",
    },
]


@dataclass
class TaskResult:
    index: int
    instruction: str
    category: str
    task_id: str
    status: str
    duration: float
    tokens_used: int = 0
    subtask_count: int = 0
    error: str | None = None


@dataclass
class CategoryStats:
    total: int = 0
    passed: int = 0
    failed: int = 0


@dataclass
class StressTestReport:
    results: list[TaskResult] = field(default_factory=list)
    total: int = 0
    passed: int = 0
    failed: int = 0
    timed_out: int = 0
    total_tokens: int = 0
    total_duration: float = 0.0
    categories: dict[str, CategoryStats] = field(default_factory=dict)


def submit_task(client: httpx.Client, instruction: str) -> str:
    """Submit a task and return its task_id."""
    resp = client.post(
        f"{BASE_URL}/api/tasks",
        json={"instruction": instruction},
    )
    resp.raise_for_status()
    return resp.json()["task_id"]


def poll_task(client: httpx.Client, task_id: str, timeout: float) -> dict[str, Any]:
    """Poll until task completes or times out."""
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        resp = client.get(f"{BASE_URL}/api/tasks/{task_id}")
        resp.raise_for_status()
        data = resp.json()
        if data["status"] in ("completed", "failed", "escalated"):
            return data
        time.sleep(2.0)
    return {"status": "timeout", "error": "Task timed out"}


def get_subtask_count(client: httpx.Client, task_id: str) -> int:
    """Get the number of subtasks for a task."""
    try:
        resp = client.get(f"{BASE_URL}/api/tasks/{task_id}/trace")
        resp.raise_for_status()
        return resp.json().get("total_subtasks", 0)
    except Exception:
        return 0


def run_stress_test() -> StressTestReport:
    """Run the 20-task mixed stress test."""
    report = StressTestReport()

    # Verify health first
    with httpx.Client(timeout=10) as client:
        try:
            health = client.get(f"{BASE_URL}/health")
            health.raise_for_status()
            health_data = health.json()
            if health_data.get("status") != "healthy":
                sys.stdout.write(f"WARNING: System health is '{health_data.get('status')}'\n")
        except Exception as e:
            sys.stdout.write(f"ERROR: Cannot reach backend at {BASE_URL}: {e}\n")
            sys.stdout.write("Make sure docker compose is up and services are healthy.\n")
            sys.exit(1)

    total_tasks = len(TASKS)
    sys.stdout.write(f"\nStarting {total_tasks}-task Phase 2 stress test...\n")
    sys.stdout.write(f"{'=' * 70}\n\n")

    with httpx.Client(timeout=30) as client:
        for i, task_def in enumerate(TASKS, 1):
            instruction = task_def["instruction"]
            category = task_def["category"]
            sys.stdout.write(f"[{i:02d}/{total_tasks:02d}] [{category}] {instruction[:50]}... ")
            sys.stdout.flush()

            # Initialize category stats
            if category not in report.categories:
                report.categories[category] = CategoryStats()

            start = time.monotonic()
            try:
                task_id = submit_task(client, instruction)
                result_data = poll_task(client, task_id, TASK_TIMEOUT_SECONDS)
                duration = time.monotonic() - start
                status = result_data["status"]
                tokens = result_data.get("tokens_used", 0)
                subtasks = get_subtask_count(client, task_id)

                task_result = TaskResult(
                    index=i,
                    instruction=instruction,
                    category=category,
                    task_id=task_id,
                    status=status,
                    duration=duration,
                    tokens_used=tokens,
                    subtask_count=subtasks,
                    error=result_data.get("error"),
                )

                report.categories[category].total += 1
                if status == "completed":
                    report.passed += 1
                    report.categories[category].passed += 1
                    sys.stdout.write(
                        f"PASS ({duration:.1f}s, {tokens} tokens, {subtasks} subtasks)\n"
                    )
                elif status == "timeout":
                    report.timed_out += 1
                    report.failed += 1
                    report.categories[category].failed += 1
                    sys.stdout.write(f"TIMEOUT ({duration:.1f}s)\n")
                else:
                    report.failed += 1
                    report.categories[category].failed += 1
                    error_msg = result_data.get("error", "unknown")
                    sys.stdout.write(f"FAIL: {error_msg[:50]} ({duration:.1f}s)\n")

                report.results.append(task_result)
                report.total_tokens += tokens

            except Exception as e:
                duration = time.monotonic() - start
                report.failed += 1
                report.categories[category].total += 1
                report.categories[category].failed += 1
                report.results.append(
                    TaskResult(
                        index=i,
                        instruction=instruction,
                        category=category,
                        task_id="",
                        status="error",
                        duration=duration,
                        error=str(e),
                    )
                )
                sys.stdout.write(f"ERROR: {e}\n")

            report.total += 1
            report.total_duration += duration

            if i < total_tasks:
                time.sleep(DELAY_BETWEEN_TASKS)

    return report


def print_report(report: StressTestReport) -> None:
    """Print the stress test summary with per-category breakdown."""
    pass_rate = (report.passed / report.total * 100) if report.total > 0 else 0

    sys.stdout.write(f"\n{'=' * 70}\n")
    sys.stdout.write("PHASE 2 STRESS TEST RESULTS\n")
    sys.stdout.write(f"{'=' * 70}\n\n")

    # Overall stats
    sys.stdout.write(f"Total tasks:    {report.total}\n")
    sys.stdout.write(f"Passed:         {report.passed}\n")
    sys.stdout.write(f"Failed:         {report.failed}\n")
    sys.stdout.write(f"Timed out:      {report.timed_out}\n")
    sys.stdout.write(f"Pass rate:      {pass_rate:.1f}%\n")
    sys.stdout.write(f"Total tokens:   {report.total_tokens:,}\n")
    sys.stdout.write(f"Total duration: {report.total_duration:.1f}s\n\n")

    # Per-category breakdown
    sys.stdout.write("Per-category breakdown:\n")
    sys.stdout.write(f"  {'Category':<25} {'Pass':>6} {'Fail':>6} {'Rate':>8}\n")
    sys.stdout.write(f"  {'-' * 47}\n")
    for cat_name, cat_stats in sorted(report.categories.items()):
        cat_rate = (cat_stats.passed / cat_stats.total * 100) if cat_stats.total > 0 else 0
        sys.stdout.write(
            f"  {cat_name:<25} {cat_stats.passed:>6} {cat_stats.failed:>6} {cat_rate:>7.1f}%\n"
        )

    # Subtask stats for multi-agent tasks
    multi_results = [r for r in report.results if r.category in ("multi_agent", "sequential")]
    if multi_results:
        avg_subtasks = sum(r.subtask_count for r in multi_results) / len(multi_results)
        sys.stdout.write(f"\nMulti-agent avg subtasks: {avg_subtasks:.1f}\n")

    # Gate check
    sys.stdout.write(f"\n{'=' * 70}\n")
    gate_pass = pass_rate >= 85.0
    if gate_pass:
        sys.stdout.write("PHASE 2 VERIFICATION GATE: PASSED (>= 85%)\n")
    else:
        sys.stdout.write("PHASE 2 VERIFICATION GATE: FAILED (< 85%)\n")
    sys.stdout.write(f"{'=' * 70}\n")

    # Show failures
    failures = [r for r in report.results if r.status != "completed"]
    if failures:
        sys.stdout.write("\nFailed tasks:\n")
        for f in failures:
            sys.stdout.write(
                f"  [{f.index:02d}] [{f.category}] {f.status}: {f.instruction[:50]}...\n"
            )
            if f.error:
                sys.stdout.write(f"       Error: {f.error[:80]}\n")

    # Save results to JSON
    results_file = "stress_test_phase2_results.json"
    with open(results_file, "w") as fp:
        json.dump(
            {
                "phase": 2,
                "total": report.total,
                "passed": report.passed,
                "failed": report.failed,
                "timed_out": report.timed_out,
                "pass_rate": pass_rate,
                "total_tokens": report.total_tokens,
                "total_duration": report.total_duration,
                "categories": {
                    name: {"total": s.total, "passed": s.passed, "failed": s.failed}
                    for name, s in report.categories.items()
                },
                "results": [
                    {
                        "index": r.index,
                        "instruction": r.instruction,
                        "category": r.category,
                        "task_id": r.task_id,
                        "status": r.status,
                        "duration": r.duration,
                        "tokens_used": r.tokens_used,
                        "subtask_count": r.subtask_count,
                        "error": r.error,
                    }
                    for r in report.results
                ],
            },
            fp,
            indent=2,
        )
    sys.stdout.write(f"\nResults saved to {results_file}\n")


if __name__ == "__main__":
    report = run_stress_test()
    print_report(report)
    sys.exit(0 if report.passed / max(report.total, 1) >= 0.85 else 1)

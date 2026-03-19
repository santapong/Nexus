"""10-task stress test for Phase 2 verification.

Run with: python -m nexus.tests.e2e.stress_test
Requires: docker compose up, make migrate, make seed

Submits 10 tasks (2 per category) via HTTP, polls for completion,
and reports pass/fail rate. Gate: >= 90% (9/10) pass rate.
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
DELAY_BETWEEN_TASKS = 5.0  # Groq free tier: ~30 RPM, need spacing

# ─── Task definitions — 10 tasks, 2 per category ─────────────────────────────

TASKS: list[dict[str, str]] = [
    # 1-2: Simple questions
    {"instruction": "Explain what a Python list comprehension is with a simple example."},
    {"instruction": "Explain the GIL (Global Interpreter Lock) in Python."},
    # 3-4: Code generation
    {"instruction": "Write a Python function to check if a string is a palindrome."},
    {
        "instruction": (
            "Write a Python class that implements a simple stack with push, pop, and peek."
        )
    },
    # 5-6: Research + code
    {
        "instruction": (
            "Research Python async patterns and write a working asyncio example with gather."
        )
    },
    {"instruction": "Explain the Observer design pattern and implement it in Python."},
    # 7-8: Debugging
    {
        "instruction": (
            "Fix this code: `def avg(lst): return sum(lst) / len(lst)` - it crashes on empty lists."
        )
    },
    {
        "instruction": (
            "Fix this code: `result = [lambda: i for i in range(5)]` - all lambdas return 4."
        )
    },
    # 9-10: Complex multi-step
    {
        "instruction": (
            "Write a Python REST API client class with retry logic,"
            " exponential backoff, and timeout handling."
        )
    },
    {
        "instruction": (
            "Write a simple Python event emitter class that supports"
            " on, off, once, and emit methods."
        )
    },
]


@dataclass
class TaskResult:
    index: int
    instruction: str
    task_id: str
    status: str
    duration: float
    tokens_used: int = 0
    error: str | None = None


@dataclass
class StressTestReport:
    results: list[TaskResult] = field(default_factory=list)
    total: int = 0
    passed: int = 0
    failed: int = 0
    timed_out: int = 0
    total_tokens: int = 0
    total_duration: float = 0.0


def submit_task(client: httpx.Client, instruction: str) -> str:
    """Submit a task and return its task_id."""
    resp = client.post(
        f"{BASE_URL}/api/tasks",
        json={"instruction": instruction},
    )
    resp.raise_for_status()
    result: str = str(resp.json()["task_id"])
    return result


def poll_task(client: httpx.Client, task_id: str, timeout: float) -> dict[str, Any]:
    """Poll until task completes or times out."""
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        resp = client.get(f"{BASE_URL}/api/tasks/{task_id}")
        resp.raise_for_status()
        data: dict[str, Any] = dict(resp.json())
        if data["status"] in ("completed", "failed", "escalated"):
            return data
        time.sleep(2.0)
    return {"status": "timeout", "error": "Task timed out"}


def run_stress_test() -> StressTestReport:
    """Run the 50-task stress test."""
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
    sys.stdout.write(f"\nStarting {total_tasks}-task stress test...\n")
    sys.stdout.write(f"{'=' * 70}\n\n")

    with httpx.Client(timeout=30) as client:
        for i, task_def in enumerate(TASKS, 1):
            instruction = task_def["instruction"]
            sys.stdout.write(f"[{i:02d}/{total_tasks:02d}] {instruction[:60]}... ")
            sys.stdout.flush()

            start = time.monotonic()
            try:
                task_id = submit_task(client, instruction)
                result_data = poll_task(client, task_id, TASK_TIMEOUT_SECONDS)
                duration = time.monotonic() - start
                status = result_data["status"]
                tokens = result_data.get("tokens_used", 0)

                task_result = TaskResult(
                    index=i,
                    instruction=instruction,
                    task_id=task_id,
                    status=status,
                    duration=duration,
                    tokens_used=tokens,
                    error=result_data.get("error"),
                )

                if status == "completed":
                    report.passed += 1
                    sys.stdout.write(f"PASS ({duration:.1f}s, {tokens} tokens)\n")
                elif status == "timeout":
                    report.timed_out += 1
                    report.failed += 1
                    sys.stdout.write(f"TIMEOUT ({duration:.1f}s)\n")
                else:
                    report.failed += 1
                    error_msg = result_data.get("error", "unknown")
                    sys.stdout.write(f"FAIL: {error_msg[:50]} ({duration:.1f}s)\n")

                report.results.append(task_result)
                report.total_tokens += tokens

            except Exception as e:
                duration = time.monotonic() - start
                report.failed += 1
                report.results.append(
                    TaskResult(
                        index=i,
                        instruction=instruction,
                        task_id="",
                        status="error",
                        duration=duration,
                        error=str(e),
                    )
                )
                sys.stdout.write(f"ERROR: {e}\n")

            report.total += 1
            report.total_duration += time.monotonic() - start

            if i < len(TASKS):
                time.sleep(DELAY_BETWEEN_TASKS)

    return report


def print_report(report: StressTestReport) -> None:
    """Print the stress test summary."""
    pass_rate = (report.passed / report.total * 100) if report.total > 0 else 0

    sys.stdout.write(f"\n{'=' * 70}\n")
    sys.stdout.write("STRESS TEST RESULTS\n")
    sys.stdout.write(f"{'=' * 70}\n\n")
    sys.stdout.write(f"Total tasks:    {report.total}\n")
    sys.stdout.write(f"Passed:         {report.passed}\n")
    sys.stdout.write(f"Failed:         {report.failed}\n")
    sys.stdout.write(f"Timed out:      {report.timed_out}\n")
    sys.stdout.write(f"Pass rate:      {pass_rate:.1f}%\n")
    sys.stdout.write(f"Total tokens:   {report.total_tokens:,}\n")
    sys.stdout.write(f"Total duration: {report.total_duration:.1f}s\n\n")

    gate_pass = pass_rate >= 90.0
    if gate_pass:
        sys.stdout.write("VERIFICATION GATE: PASSED (>= 90%)\n")
    else:
        sys.stdout.write("VERIFICATION GATE: FAILED (< 90%)\n")

    # Show failures
    failures = [r for r in report.results if r.status != "completed"]
    if failures:
        sys.stdout.write("\nFailed tasks:\n")
        for f in failures:
            sys.stdout.write(f"  [{f.index:02d}] {f.status}: {f.instruction[:50]}...\n")
            if f.error:
                sys.stdout.write(f"       Error: {f.error[:80]}\n")

    # Save results to JSON
    results_file = "stress_test_results.json"
    with open(results_file, "w") as fp:
        json.dump(
            {
                "total": report.total,
                "passed": report.passed,
                "failed": report.failed,
                "timed_out": report.timed_out,
                "pass_rate": pass_rate,
                "total_tokens": report.total_tokens,
                "total_duration": report.total_duration,
                "results": [
                    {
                        "index": r.index,
                        "instruction": r.instruction,
                        "task_id": r.task_id,
                        "status": r.status,
                        "duration": r.duration,
                        "tokens_used": r.tokens_used,
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
    sys.exit(0 if report.passed / max(report.total, 1) >= 0.9 else 1)

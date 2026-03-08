"""50-task stress test for Phase 1 gate.

Run with: python -m nexus.tests.e2e.stress_test
Requires: docker compose up, make migrate, make seed

Submits 50 tasks of increasing complexity via HTTP, polls for completion,
and reports pass/fail rate. Phase 2 gate: >= 90% (45/50) pass rate.
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field

import httpx

BASE_URL = "http://localhost:8000"
TASK_TIMEOUT_SECONDS = 120
DELAY_BETWEEN_TASKS = 1.0

# ─── Task definitions ────────────────────────────────────────────────────────

TASKS: list[dict[str, str]] = [
    # 1-10: Simple questions
    {"instruction": "Explain what a Python list comprehension is with a simple example."},
    {"instruction": "What is the difference between a tuple and a list in Python?"},
    {"instruction": "Explain how Python's garbage collector works in 3 sentences."},
    {"instruction": "What does the `yield` keyword do in Python?"},
    {"instruction": "Explain the GIL (Global Interpreter Lock) in Python."},
    {"instruction": "What is the difference between `==` and `is` in Python?"},
    {"instruction": "Explain Python decorators with a simple example."},
    {"instruction": "What are Python context managers and how does `with` work?"},
    {"instruction": "Explain the difference between `*args` and `**kwargs`."},
    {"instruction": "What is duck typing in Python?"},
    # 11-20: Code generation
    {"instruction": "Write a Python function to check if a string is a palindrome."},
    {"instruction": "Write a Python function to sort a dictionary by its values."},
    {"instruction": "Write a Python function that implements binary search on a sorted list."},
    {"instruction": "Write a Python class that implements a simple stack with push, pop, and peek."},
    {"instruction": "Write a Python function to flatten a nested list of arbitrary depth."},
    {"instruction": "Write a Python function to find the nth Fibonacci number using memoization."},
    {"instruction": "Write a Python function that removes duplicate elements from a list while preserving order."},
    {"instruction": "Write a Python function to validate an email address using regex."},
    {"instruction": "Write a Python function that converts a Roman numeral string to an integer."},
    {"instruction": "Write a Python function to merge two sorted lists into one sorted list."},
    # 21-30: Research + code
    {"instruction": "Research Python async patterns and write a working asyncio example with gather."},
    {"instruction": "Explain the Observer design pattern and implement it in Python."},
    {"instruction": "Explain how Python dataclasses work and write an example with inheritance."},
    {"instruction": "Explain the Strategy pattern and implement it in Python for sorting algorithms."},
    {"instruction": "Research Python's typing module and write an example using Protocol and TypeVar."},
    {"instruction": "Explain Python's descriptor protocol and write a custom descriptor example."},
    {"instruction": "Research Python's functools module and demonstrate lru_cache, partial, and reduce."},
    {"instruction": "Explain how Python metaclasses work and create a simple metaclass example."},
    {"instruction": "Research Python's itertools module and demonstrate 5 useful functions."},
    {"instruction": "Explain the Singleton pattern in Python and show 3 different ways to implement it."},
    # 31-40: Debugging
    {"instruction": "Fix this code: `def avg(lst): return sum(lst) / len(lst)` — it crashes on empty lists."},
    {"instruction": "Fix this code: `d = {}; d['a']['b'] = 1` — it raises KeyError."},
    {"instruction": "Fix this code: `items = [1,2,3]; for i in items: items.remove(i)` — it doesn't remove all items."},
    {"instruction": "Fix this code that has a race condition: two threads incrementing a shared counter without locks."},
    {"instruction": "Fix this code: `result = [lambda: i for i in range(5)]` — all lambdas return 4."},
    {"instruction": "Fix this code: `class Foo: items = []; def add(self, x): self.items.append(x)` — shared mutable default."},
    {"instruction": "Fix this code: `async def fetch(): return requests.get(url)` — blocking call in async context."},
    {"instruction": "Fix this code: `f = open('file.txt'); data = f.read()` — resource leak, no close."},
    {"instruction": "Fix this code: `import json; json.loads('{key: value}')` — invalid JSON format."},
    {"instruction": "Fix this code: `x = 0.1 + 0.2; assert x == 0.3` — floating point comparison."},
    # 41-50: Complex multi-step
    {"instruction": "Write a Python REST API client class with retry logic, exponential backoff, and timeout handling."},
    {"instruction": "Write a thread-safe LRU cache in Python using OrderedDict and threading.Lock."},
    {"instruction": "Write a Python function that parses a mathematical expression string and evaluates it (supporting +, -, *, /, parentheses)."},
    {"instruction": "Write a simple Python event emitter class that supports on, off, once, and emit methods."},
    {"instruction": "Write a Python rate limiter using the token bucket algorithm."},
    {"instruction": "Write a Python circuit breaker pattern implementation with open, closed, and half-open states."},
    {"instruction": "Write a Python class that implements a priority queue using a heap."},
    {"instruction": "Write a Python decorator that caches results to disk using JSON files."},
    {"instruction": "Write a Python function that validates and parses ISO 8601 datetime strings without external libraries."},
    {"instruction": "Write a comprehensive Python unit test suite for a simple calculator class with add, subtract, multiply, and divide."},
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
    return resp.json()["task_id"]


def poll_task(client: httpx.Client, task_id: str, timeout: float) -> dict:
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
                sys.stdout.write(
                    f"WARNING: System health is '{health_data.get('status')}'\n"
                )
        except Exception as e:
            sys.stdout.write(f"ERROR: Cannot reach backend at {BASE_URL}: {e}\n")
            sys.stdout.write("Make sure docker compose is up and services are healthy.\n")
            sys.exit(1)

    sys.stdout.write(f"\nStarting 50-task stress test...\n")
    sys.stdout.write(f"{'='*70}\n\n")

    with httpx.Client(timeout=30) as client:
        for i, task_def in enumerate(TASKS, 1):
            instruction = task_def["instruction"]
            sys.stdout.write(f"[{i:02d}/50] {instruction[:60]}... ")
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

    sys.stdout.write(f"\n{'='*70}\n")
    sys.stdout.write(f"STRESS TEST RESULTS\n")
    sys.stdout.write(f"{'='*70}\n\n")
    sys.stdout.write(f"Total tasks:    {report.total}\n")
    sys.stdout.write(f"Passed:         {report.passed}\n")
    sys.stdout.write(f"Failed:         {report.failed}\n")
    sys.stdout.write(f"Timed out:      {report.timed_out}\n")
    sys.stdout.write(f"Pass rate:      {pass_rate:.1f}%\n")
    sys.stdout.write(f"Total tokens:   {report.total_tokens:,}\n")
    sys.stdout.write(f"Total duration: {report.total_duration:.1f}s\n\n")

    gate_pass = pass_rate >= 90.0
    if gate_pass:
        sys.stdout.write(f"PHASE 2 GATE: PASSED (>= 90%)\n")
    else:
        sys.stdout.write(f"PHASE 2 GATE: FAILED (< 90%)\n")

    # Show failures
    failures = [r for r in report.results if r.status != "completed"]
    if failures:
        sys.stdout.write(f"\nFailed tasks:\n")
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

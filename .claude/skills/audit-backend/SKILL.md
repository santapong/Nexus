---
name: audit-backend
description: Run a high-level backend correctness audit of the NEXUS codebase. Use when the user asks for a backend review, before a production push, or after refactoring AgentBase or Kafka consumers. Checks async correctness, error handling, idempotency, and the agent guard chain. Read-only.
---

# Backend Correctness Audit Skill

Audits NEXUS for the backend correctness issues that produce silent task failures, lost data, and unbounded resource consumption.

## When to invoke

- Before any production deployment
- After changes to `agents/base.py`, `core/kafka/consumer.py`, `core/recovery.py`, `core/shutdown.py`, `core/llm/circuit_breaker.py`
- After adding a new agent role
- When tasks are silently failing or hanging in production

## Workflow

Run as a single Explore subagent with the prompt template below.

### 1. AgentBase guard chain

`backend/nexus/agents/base.py`. The documented order is:

```
idempotency → budget check → load memory → handle_task → write memory → publish → broadcast
```

Verify:

- **Order is correct in code** (not just docstring)
- Memory write is in a **separate try/finally** so its failure prevents result publication (CLAUDE.md §20 rule 2)
- The outer `except Exception` block does **not** publish a result when memory write fails
- `asyncio.CancelledError` propagates (does not get swallowed by broad except)
- `asyncio.create_task(...)` results are stored as `self._foo_task` (otherwise GC'd)

### 2. Kafka consumer idempotency

Every consumer must call `check_idempotency(message_id)` before processing:

- `backend/nexus/agents/base.py` (Pattern A: agent side) ✓
- `backend/nexus/core/kafka/result_consumer.py` (Pattern B: consumer side) — often missing
- `backend/nexus/core/kafka/meeting.py`
- `backend/nexus/core/kafka/dead_letter.py` — at-least-once redelivery here can multiply dead letters

### 3. Topic constants

```bash
grep -rn '"task\.\|"agent\.\|"meeting\.\|"prompt\.\|"director\.' backend/nexus/ \
  --include='*.py' | grep -v 'core/kafka/topics.py'
```

Any hit outside `topics.py` violates §10 rule "no hardcoded topic strings."

### 4. Async correctness

- Missing `await` on coroutines:
  ```bash
  grep -rn 'db\.execute(\|session\.execute(\|kafka\.send\|redis\.' backend/nexus/ | grep -v 'await\|def '
  ```
- Sync I/O in async functions: `requests.`, `time.sleep(`, `open(` (unless `aiofiles`), `psycopg2.` (must be asyncpg)
- `asyncio.create_task` without storing the reference

### 5. Error handling

```bash
grep -rn 'except:\|except Exception:.*pass\|except.*:\s*$' backend/nexus/ \
  --include='*.py'
```

Each hit needs justification. Broad `except Exception` is acceptable around guard-chain steps **only if** the error is logged, audit-logged, and the task is marked failed.

### 6. Settings discipline

```bash
grep -rn 'os\.environ\|os\.getenv' backend/nexus/ --include='*.py' \
  | grep -v 'settings\.py\|tests/'
```

Any hit outside `settings.py` violates §16 rule 6. Required env vars without defaults: app must fail at **startup** with a helpful error, not on first use.

### 7. Heartbeat + health monitor

`backend/nexus/agents/health_monitor.py`:

- Auto-fail after 5 min silence — is the check atomic? (Race: agent heartbeats between Redis fetch and silence check.) Use Redis EVAL/Lua for atomicity.
- "Never heartbeated" vs "stopped heartbeating" — should be distinguished in logs and metrics.
- Health monitor itself heartbeats? (Otherwise it can hang silently.)

### 8. Circuit breaker

`backend/nexus/core/llm/circuit_breaker.py`:

- Per-provider state, not global
- HALF_OPEN → CLOSED clears the sliding-window failure count (otherwise old failures keep reopening it)
- Circuit state exposed in `/health`
- Fallback chain is configured per role, not just a global

### 9. Recovery service

`backend/nexus/core/recovery.py`:

- Runs once at startup, not periodically (or has idempotency on `recovery_attempt`)
- Marks orphans before re-publishing (otherwise crash mid-recovery re-publishes the same task)
- Has a max age cutoff (don't recover a task from 6 months ago)

### 10. Graceful shutdown

`backend/nexus/core/shutdown.py`:

- SIGTERM + SIGINT handled
- `is_shutting_down()` flag checked in consumer loops **before fetching next message**
- 30-second drain timeout
- In-flight tasks checkpoint state before exit so recovery can resume them
- Result consumer drained before exit (otherwise late results lost)

### 11. Test coverage gaps

`backend/nexus/tests/`. Confirm tests exist for:

- Guard chain ordering invariants (skip step → assert no publish)
- Memory write failure (raise inside write_memory → assert no publish)
- Consumer idempotency loss
- Circuit breaker HALF_OPEN edge cases
- Recovery + concurrent new-task arrival race
- Graceful shutdown with in-flight tasks

## Output format

```
# Backend Correctness Audit — YYYY-MM-DD

## Critical
- **[file:line] Title** — description + recommended fix

## High
- ...

## Medium
- ...

## Notes / things that look correct
- ...
```

## Rules

- Read-only.
- Cite file paths and line numbers.
- Cap at 1500 words.

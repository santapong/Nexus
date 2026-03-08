# ERRORLOG.md
## NEXUS — Error & Bug Tracking Log

> **Update this file whenever you find a bug, silent failure, wrong assumption,
> or unexpected behavior — even if you fix it immediately.**
>
> The purpose is to build a knowledge base so future agents and humans
> do not repeat the same mistakes.
>
> Format defined in AGENTS.md §10.
> Most recent entry at the top.

---

## Severity Reference

| Severity | Meaning |
|----------|---------|
| `critical` | Data loss, security issue, or silent incorrect behavior that corrupts state |
| `high` | Incorrect behavior that affects task outcomes or agent memory |
| `medium` | Incorrect behavior that degrades quality but doesn't corrupt state |
| `low` | Minor issue, cosmetic bug, or suboptimal but not wrong behavior |

## Status Reference

| Status | Meaning |
|--------|---------|
| `open` | Error discovered, fix not yet implemented |
| `fixed` | Root cause addressed, verified by test |
| `mitigated` | Partially addressed, full fix deferred to BACKLOG |
| `wont-fix` | Known issue, accepted risk, documented reason |

---

## Error Entry Template

Copy this template for each new error.

```markdown
## ERROR-{NNN} — {short description}

**Date:** YYYY-MM-DD
**Severity:** critical | high | medium | low
**Status:** open | fixed | mitigated | wont-fix
**Found by:** {agent_name or 'human'} during {task or context}
**Affected files:** {list}

### What happened
{Exact description of the incorrect behavior. Be specific.
Include: what was expected vs what actually happened.}

### Root cause
{Why did it happen? Wrong assumption? Missing guard? Race condition?
Missing test? Bad default? Dependency behavior?}

### Fix applied
{What was changed to fix it?
Include: commit hash or PR number if available.
If status is 'open': describe what fix is needed and who should do it.}

### Prevention
{What prevents this from happening again?
- New test name + location
- New rule added to AGENTS.md or CLAUDE.md (section number)
- New guard or validation added
- Dependency version pinned}

---
```

---

## Error Log

<!-- New entries go here, below this line, newest first -->

## ERROR-011 — Docker port conflicts with host services

**Date:** 2026-03-08
**Severity:** medium
**Status:** fixed
**Found by:** claude_code during E2E verification
**Affected files:** `docker-compose.yml`

### What happened
`docker compose up` failed to bind ports 5432 and 6379 because the host machine
runs local PostgreSQL (5432) and Redis (6379).

### Root cause
docker-compose.yml used identical host:container port mappings (5432:5432, 6379:6379).
Host services occupied these ports.

### Fix applied
Remapped host ports: postgres `5433:5432`, redis `6380:6379`. Internal Docker networking
unaffected — containers still use standard ports via Docker DNS. See ADR-015.

### Prevention
- ADR-015 documents the port mapping convention
- `docker-compose.yml` comments explain the remapping reason

---

## ERROR-010 — Frontend API path mismatches

**Date:** 2026-03-08
**Severity:** high
**Status:** fixed
**Found by:** claude_code during E2E verification
**Affected files:** `frontend/src/App.tsx` (before decomposition), `frontend/src/api/client.ts`

### What happened
Frontend called `/tasks`, `/approvals` directly. Backend routes are under `/api/` prefix
(`/api/tasks`, `/api/approvals`). All API calls returned 404. Additionally, approval
endpoints used separate `/approve` and `/reject` paths instead of the correct single
`/resolve` endpoint.

### Root cause
Frontend was written before the API router prefix was finalized. The approval API design
changed from two endpoints to one `POST /resolve` with `{ approved: bool }` body.

### Fix applied
Updated all API paths to use `/api/` prefix. Changed approval calls to use
`POST /api/approvals/{id}/resolve` with `{ approved: bool, resolved_by: 'human' }`.

### Prevention
- API client module (`frontend/src/api/client.ts`) centralizes all API paths
- Future: generate TypeScript types from OpenAPI spec to catch mismatches at build time

---

## ERROR-009 — Heartbeat double-serialization causes TypeError

**Date:** 2026-03-08
**Severity:** high
**Status:** fixed
**Found by:** claude_code during E2E verification
**Affected files:** `backend/nexus/agents/base.py`

### What happened
Agent heartbeat loop crashed with `Object of type bytes is not JSON serializable`.
Heartbeat messages never reached Kafka.

### Root cause
The heartbeat code did `json.dumps(hb.model_dump(mode="json")).encode("utf-8")` producing
`bytes`, then passed it to the Kafka producer whose `value_serializer=lambda v: json.dumps(v).encode("utf-8")`
tried to JSON-serialize the bytes object. Double serialization.

### Fix applied
Pass `hb.model_dump(mode="json")` (a `dict`) directly to `producer.send_and_wait()`.
The producer's `value_serializer` handles JSON encoding.

### Prevention
- Pattern documented: never pre-serialize when using a producer with `value_serializer`
- Same pattern applies to all Kafka `publish()` calls via `producer.py`

---

## ERROR-008 — Task not persisting to DB before Kafka consumer processes it

**Date:** 2026-03-08
**Severity:** critical
**Status:** fixed
**Found by:** claude_code during E2E verification
**Affected files:** `backend/nexus/api/tasks.py`

### What happened
Task created via `POST /api/tasks` was flushed to DB but not committed before the Kafka
message was published. CEO agent consumed the Kafka message and queried the DB, but the
task didn't exist yet (uncommitted transaction).

### Root cause
Relied on Litestar's auto-commit, which commits after the response is sent. The Kafka
consumer processes the message before the HTTP response completes.

### Fix applied
Added explicit `await db_session.commit()` after `db_session.flush()` and before
`publish()` in `tasks.py`. See ADR-016.

### Prevention
- ADR-016: explicit commit before Kafka publish is now a project convention
- Any API handler that writes to DB then publishes to Kafka must commit first

---

## ERROR-007 — sa_orm_sentinel column missing from Alembic migration

**Date:** 2026-03-08
**Severity:** critical
**Status:** fixed
**Found by:** claude_code during E2E verification
**Affected files:** `backend/alembic/versions/001_initial_schema.py`

### What happened
All database queries failed with `UndefinedColumnError: column "sa_orm_sentinel" does not exist`.
Health check, task creation, agent queries — everything touching the DB was broken.

### Root cause
Advanced Alchemy's `UUIDBase` and `UUIDAuditBase` automatically add a `sa_orm_sentinel`
column to ORM models. The hand-written Alembic migration did not include this column in
any of the 9 tables.

### Fix applied
Added `sa.Column("sa_orm_sentinel", sa.Integer(), nullable=True)` to all 9 tables
in `001_initial_schema.py`.

### Prevention
- Documented in project memory: Advanced Alchemy base classes add `sa_orm_sentinel`
- Future migrations should be auto-generated with `alembic revision --autogenerate`
  to catch ORM-added columns

---

## ERROR-006 — AnthropicModel rejects api_key parameter in pydantic-ai 0.5.x

**Date:** 2026-03-08
**Severity:** high
**Status:** fixed
**Found by:** claude_code during E2E verification
**Affected files:** `backend/nexus/llm/factory.py`

### What happened
`ModelFactory.get_model()` passed `api_key=settings.anthropic_api_key` to
`AnthropicModel()`. pydantic-ai 0.5.x raised `TypeError: __init__() got an unexpected
keyword argument 'api_key'`.

### Root cause
pydantic-ai 0.5.x changed the model constructor API. API keys are now read from
environment variables automatically (`ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`).

### Fix applied
Removed `api_key` parameter from `AnthropicModel()` and `GeminiModel()` calls in
`factory.py`. Keys are set via env vars in docker-compose.yml.

### Prevention
- ADR-014 documents the pydantic-ai version pin and API key behavior
- Version pinned to 0.5.x to prevent future breakage

---

## ERROR-005 — pydantic-ai 0.6+ incompatible with anthropic SDK 0.84+

**Date:** 2026-03-08
**Severity:** critical
**Status:** fixed
**Found by:** claude_code during E2E verification
**Affected files:** `backend/pyproject.toml`

### What happened
Backend failed to start with `ImportError` when pip resolved pydantic-ai 0.6+ with
anthropic 0.84.0. pydantic-ai 0.6+ imports `UserLocation` from
`anthropic.types.beta.beta_web_search_tool_20250305_param`, but anthropic 0.84.0 renamed
it to `BetaUserLocationParam`.

### Root cause
Breaking change in anthropic SDK 0.84.0 that pydantic-ai 0.6+ was not updated to handle.
No compatible combination of pydantic-ai 0.6+ and any anthropic SDK version exists.

### Fix applied
Pinned `pydantic-ai[anthropic,google]>=0.5.0,<0.6.0` and `anthropic>=0.80.0,<0.83.0`
in `pyproject.toml`. See ADR-014.

### Prevention
- Version pins in pyproject.toml prevent pip from resolving to broken combinations
- ADR-014 documents the constraint and future upgrade path

---

## ERROR-004 — structlog.get_level_from_name does not exist

**Date:** 2026-03-08
**Severity:** high
**Status:** fixed
**Found by:** claude_code during E2E verification
**Affected files:** `backend/nexus/app.py`, `backend/nexus/agents/runner.py`

### What happened
Backend crashed at startup with `AttributeError: module 'structlog' has no attribute
'get_level_from_name'`. Both `app.py` and `runner.py` called this non-existent function.

### Root cause
`structlog.get_level_from_name()` was assumed to exist but does not. The function was
likely confused with an internal or deprecated API.

### Fix applied
Replaced with `getattr(logging, settings.log_level.upper(), logging.INFO)` using
Python's standard `logging` module to convert level name strings to integers.

### Prevention
- Pattern documented in project memory for future structlog usage
- `import logging` added to both files

---

## ERROR-003 — PRE-BUILD WARNING: Irreversible tool action before approval flow exists

**Date:** 2026-03-07
**Severity:** critical
**Status:** mitigated
**Found by:** claude_code during pre-build documentation review
**Affected files:** `nexus/tools/adapter.py`, `nexus/tools/guards.py`, `nexus/db/models.py`

### What happened
This is a pre-build warning, not a discovered bug. CLAUDE.md §23 Prevention Rule 4
identifies a critical risk: if any agent runs before `require_approval()` and the
`human_approvals` table exist, irreversible tools (file_write, git_push, send_email)
could execute without human consent.

### Root cause
The approval flow is infrastructure, not a feature. If treated as a Phase 2 feature,
agents in Phase 1 testing could trigger irreversible actions with no safety gate.

### Fix needed
Build `require_approval()` guard in `tools/guards.py` and `human_approvals` table
migration during Phase 0 (Day 2-3), before any agent code runs. All irreversible tools
must be disabled by default in Phase 1 testing until the approval UI is functional.

### Prevention
- Phase 0 gate: `human_approvals` table must exist before any agent runs
- Phase 1 gate: `require_approval()` guard must be unit tested before wiring to adapter.py
- CI: adapter.py must not import any irreversible tool function without a corresponding
  `require_approval()` call (enforce via behavior test)

---

## ERROR-002 — PRE-BUILD WARNING: Unbounded agent loop cost explosion

**Date:** 2026-03-07
**Severity:** critical
**Status:** mitigated
**Found by:** claude_code during pre-build documentation review
**Affected files:** `nexus/agents/base.py`, `nexus/llm/usage.py`, `nexus/redis/clients.py`

### What happened
This is a pre-build warning, not a discovered bug. CLAUDE.md §23 Prevention Rule 2
identifies a critical risk: without token budget enforcement, a single multi-agent task
could burn $50+ in LLM API costs before anyone notices. Agent loops (tool call -> LLM ->
tool call) can iterate indefinitely if not bounded.

### Root cause
LLM API calls have real cost. Without a hard cap checked before every call, there is no
upper bound on spending per task or per day.

### Fix needed
Implement before any real LLM call runs:
1. Redis db:1 token tracker: `token_budget:{task_id}` with per-task limit (default 50,000)
2. Daily spending cap: `daily_spend:{date}` with $5/day hard limit
3. `AgentBase._check_budget()` called before every `self.llm.run()` call
4. At 90% budget: pause task, publish to `human.input_needed`
5. 20-tool-call limit per task (CLAUDE.md §20 Rule 4)

### Prevention
- Phase 0 gate: Redis token tracker keys must be writable before agent code runs
- Phase 1 gate: `_check_budget()` must be unit tested with boundary cases (89%, 90%, 100%)
- Behavior test: agent with budget=100 tokens must pause and publish to human.input_needed

---

## ERROR-001 — PRE-BUILD WARNING: Building orchestration before core agent loop works

**Date:** 2026-03-07
**Severity:** high
**Status:** mitigated
**Found by:** claude_code during pre-build documentation review
**Affected files:** `nexus/agents/base.py`

### What happened
This is a pre-build warning, not a discovered bug. CLAUDE.md §23 Prevention Rule 1
identifies a high risk: if multi-agent orchestration (CEO delegation, meeting rooms,
QA pipeline) is built before the core single-agent loop is proven reliable, a bug in
AgentBase will cascade to every agent and invalidate weeks of work.

### Root cause
AgentBase is the most critical class in the system. Every agent inherits from it.
Its guard chain (idempotency -> budget -> load memory -> handle_task -> write memory ->
publish -> broadcast) must work flawlessly before any multi-agent interaction is attempted.

### Fix needed
Phase 1 must produce exactly ONE working agent (Engineer) with a proven guard chain.
The 50-task stress test (pass rate >= 90%) is the hard gate before Phase 2 starts.
Do not build CEO delegation, meeting rooms, or QA review pipeline until this gate passes.

### Prevention
- Phase 1 DoD: 50-task stress test at >= 90% pass rate
- Phase 2 is BLOCKED until this gate clears
- Behavior tests for every step in the guard chain must pass before stress test

---

## Known Patterns to Watch For

These patterns have caused problems in agentic systems generally.
Check for them during code review and testing.

### Pattern A — Memory write after publish

**Risk:** Agent publishes result to Kafka before writing episodic memory.
If memory write fails, the task appears complete but has no memory record.
**Watch for:** Any code where `kafka.publish()` appears before `memory.write_episode()`.
**Required order:** memory.write_episode() → kafka.publish() → always.

### Pattern B — Silent exception swallow

**Risk:** `except Exception: pass` hides failures. Tasks appear to complete but
produced no useful output. No log entry. No trace. Impossible to debug.
**Watch for:** Any bare `except` block without a log statement and re-raise.
**Required pattern:** Always log + (handle or re-raise).

### Pattern C — Sync I/O in async context

**Risk:** Blocking call inside an async function freezes the entire event loop.
All other tasks waiting on the event loop are blocked.
**Watch for:** `requests.get()`, `open()`, `time.sleep()` inside async functions.
**Required pattern:** Use async equivalents or wrap with `asyncio.to_thread()`.

### Pattern D — Duplicate Kafka message processing

**Risk:** Kafka delivers messages at-least-once. Without idempotency keys,
the same task can be processed twice. Double LLM calls, double memory writes,
double tool calls (possibly double emails sent).
**Watch for:** Any Kafka consumer that doesn't check a Redis idempotency key first.
**Required pattern:** Check `idempotency:{message_id}` in Redis db:3 before processing.

### Pattern E — Token budget not checked before LLM call

**Risk:** Agent makes LLM calls without checking remaining budget. Task exceeds
the per-task token limit, cost spikes, and the agent doesn't pause for human input.
**Watch for:** Any `await self.llm.run(...)` not preceded by `await self._check_budget(...)`.
**Required pattern:** Always _check_budget() → then llm.run().

### Pattern F — Irreversible tool without approval gate

**Risk:** Agent writes a file, sends an email, or pushes code without human approval.
Action cannot be undone.
**Watch for:** Any tool in `adapter.py` that has side effects but no `require_approval()` call.
**Required pattern:** Every tool with side effects in the real world MUST call `require_approval()`.

### Pattern G — Hardcoded Kafka topic string

**Risk:** Topic string typo is only caught at runtime, not at lint time. Misrouted
messages are silently dropped or go to wrong consumers.
**Watch for:** Any string literal matching a known topic pattern (e.g., `"agent.commands"`)
outside of `kafka/topics.py`.
**Required pattern:** Always `Topics.AGENT_COMMANDS`, never `"agent.commands"`.

---

*Last updated: 2026-03-08*
*Next error ID: ERROR-012*

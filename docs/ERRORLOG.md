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

## ERROR-018 — A2A gateway did not persist Task to database

**Date:** 2026-03-16
**Severity:** critical
**Status:** fixed
**Found by:** claude_code during Phase 2 completion review
**Affected files:** `backend/nexus/gateway/routes.py`

### What happened
The A2A gateway `submit_task` endpoint generated a `task_id`, published an `AgentCommand`
to Kafka `a2a.inbound` topic, but **never created a Task row in PostgreSQL**. This caused:
1. `result_consumer._update_task_in_db()` couldn't find the task — logged a warning and skipped.
2. CEO's `_create_subtasks()` set `parent_task_id` pointing to a non-existent row — FK violation.
3. `GET /a2a/tasks/{id}/status` returned a hardcoded placeholder instead of real state.

The regular task API (`api/tasks.py:44-59`) correctly created the Task before Kafka publish —
the A2A gateway missed this step.

### Root cause
The gateway was built during Phase 2 Priority Group 7 as a "publish to Kafka and let CEO
handle it" design. The assumption was that CEO would create the task record. But CEO receives
tasks from Kafka and expects the Task row to already exist (same as the regular task API flow).

### Fix applied
1. Added `db_session: AsyncSession` parameter to `submit_task` (Litestar DI injection).
2. Create `Task` record with `source=TaskSource.A2A.value` and `source_agent` from metadata.
3. `flush()` + `commit()` before Kafka publish (same pattern as `api/tasks.py`).
4. Replaced hardcoded `get_task_status` placeholder with real DB query.
5. Added SSE streaming endpoint `GET /a2a/tasks/{task_id}/events`.

### Prevention
- Pattern J (see below) added to Known Patterns
- Integration tests in `test_a2a_gateway.py` now validate DB record creation
- The commit-then-publish pattern is enforced: always persist to DB before Kafka

---

## ERROR-017 — Frontend prod Docker build fails (import.meta.env TypeScript error)

**Date:** 2026-03-14
**Severity:** medium
**Status:** fixed
**Found by:** claude_code during Docker multi-stage build implementation
**Affected files:** `frontend/tsconfig.json`, `frontend/src/vite-env.d.ts`

### What happened
`npm run build` in the Docker prod stage failed with:
```
src/api/client.ts(14,29): error TS2339: Property 'env' does not exist on type 'ImportMeta'.
src/ws/AgentWebSocketProvider.tsx(4,29): error TS2339: Property 'env' does not exist on type 'ImportMeta'.
```
TypeScript didn't know about Vite's `import.meta.env` extension.

### Root cause
Missing `vite-env.d.ts` type declaration file and no Vite client types referenced in
`tsconfig.json`. The dev server worked because Vite injects these types at runtime,
but `tsc` (used by `npm run build`) requires explicit type declarations.

### Fix applied
1. Created `frontend/src/vite-env.d.ts` with `/// <reference types="vite/client" />`
2. Added `"src/vite-env.d.ts"` to `tsconfig.json` `include` array

### Prevention
- Frontend CI job now runs `npx tsc --noEmit` and `npm run build` to catch type errors
- Standard Vite project setup always includes `vite-env.d.ts` — verify on project init

---

## ERROR-016 — Frontend node_modules packaged into Docker image

**Date:** 2026-03-14
**Severity:** medium
**Status:** fixed
**Found by:** user report — Docker build was slow and images were bloated
**Affected files:** `frontend/Dockerfile`, `frontend/.dockerignore`, `docker-compose.yml`

### What happened
Frontend Docker image was 451MB because: (1) No `.dockerignore` existed for the frontend
directory, so host `node_modules/` was sent as part of the Docker build context.
(2) `COPY . .` in the Dockerfile copied the host node_modules into the image alongside
the container's own `npm install` output. (3) Anonymous volume `- /app/node_modules` in
docker-compose.yml was fragile.

### Root cause
Missing `.dockerignore` for the frontend. Single-stage Dockerfile with no dev/prod separation.

### Fix applied
1. Created `frontend/.dockerignore` excluding `node_modules`, `dist`, `.git`
2. Multi-stage Dockerfile: `dev` → `build` → `prod` (nginx, 62MB)
3. Changed anonymous volume to named volume `frontend_node_modules:/app/node_modules`
4. Added `target: dev` to docker-compose.yml

### Prevention
- `.dockerignore` now exists for both backend and frontend
- Multi-stage builds ensure prod images never include dev dependencies
- Named volumes are more predictable than anonymous volumes

## ERROR-015 — In-memory meeting registry not cluster-safe

**Date:** 2026-03-10
**Severity:** medium
**Status:** mitigated
**Found by:** claude_code during Phase 2 PG 5 (meeting room) implementation
**Affected files:** `backend/nexus/kafka/meeting.py`

### What happened
The `MeetingRoom` class uses an in-memory dict `_meeting_registry` to track active meetings.
This works in single-process mode but will lose all meeting state if the process restarts,
and cannot be shared across multiple backend workers.

### Root cause
Phase 2 design choice for simplicity. The meeting registry stores active `MeetingRoom` objects
in a module-level dictionary. Designed for single-worker mode used in current deployment.

### Fix applied
Documented as a known limitation. The registry includes proper cleanup (`close()` method on
MeetingRoom, `close_all_meetings()` on registry). For Phase 3, meetings should use Redis-backed
state to survive restarts and enable multi-worker deployments.

### Prevention
- BACKLOG item for Redis-backed meeting registry (Phase 3)
- MeetingRoom includes timeout guards (300s) and max-round guards (10) to prevent zombie meetings
- `close_all_meetings()` is called during graceful shutdown

---

## ERROR-014 — Unused imports cascade in newly created Phase 2 files

**Date:** 2026-03-10
**Severity:** low
**Status:** fixed
**Found by:** claude_code (IDE linter feedback) during Phase 2 PG 4-7 implementation
**Affected files:** `backend/nexus/kafka/meeting.py`, `backend/nexus/agents/prompt_creator.py`,
`backend/nexus/api/prompts.py`, `backend/nexus/gateway/schemas.py`, `backend/nexus/gateway/auth.py`,
`backend/nexus/gateway/routes.py`, `backend/nexus/tests/integration/test_a2a_gateway.py`

### What happened
Multiple newly created files contained unused imports (`asyncio`, `Any`, `UUID`, `uuid4`,
`AgentRole`, `TaskStatus`, `patch`, `AsyncMock`, `pytest`, `_hash_token`, `Task`,
`A2ACompletionEvent`, `A2AEventStatus`). Ruff linter would flag these.

### Root cause
Files were created with imports that were anticipated to be needed but were not used in
the final implementation. Common pattern when writing code that evolves during development.

### Fix applied
Removed all unused imports across all 7 affected files in multiple cleanup passes.
Verified by IDE lint feedback — all unused import warnings resolved.

### Prevention
- Always verify imports after completing a file
- Run `ruff check --select F401` (unused imports) before committing
- IDE feedback loop catches these incrementally

---

## ERROR-013 — CEO decomposition f-string with JSON braces causes parse errors

**Date:** 2026-03-10
**Severity:** medium
**Status:** fixed
**Found by:** claude_code during Phase 2 implementation
**Affected files:** `backend/nexus/agents/ceo.py`

### What happened
CEO system prompt used f-string with inline JSON example containing braces:
`f"Example: [{{"role": "analyst"...}}]"`. IDE and some Python parsers flagged this as
a syntax error due to nested brace escaping ambiguity.

### Root cause
f-strings require `{{` and `}}` to produce literal braces. Combined with JSON examples
containing multiple nested objects, the escaping becomes fragile and hard to read.

### Fix applied
Changed the JSON example from an f-string to a plain string concatenation. The LLM
prompt template uses `str.format()` or simple concatenation for dynamic parts, keeping
the JSON example as a literal string.

### Prevention
- Pattern: never embed JSON examples in f-strings. Use plain strings for static content.
- Added to code review checklist for agent prompts.

---

## ERROR-012 — Unused imports/variables in Phase 2 agent files

**Date:** 2026-03-10
**Severity:** low
**Status:** fixed
**Found by:** claude_code during Phase 2 implementation
**Affected files:** `backend/nexus/agents/ceo.py`, `backend/nexus/tools/adapter.py`, `backend/nexus/kafka/result_consumer.py`

### What happened
Multiple files had unused imports (`datetime`, `timezone`, `uuid4`) and unused variable
assignments (`add_result`, `commit_result`, `ceo_id`). Would fail ruff lint checks.

### Root cause
Code was written with variables for debugging that were not cleaned up before finalization.

### Fix applied
Removed all unused imports and variable assignments. Verified with `ast.parse()` on all files.

### Prevention
- Run `ruff check` before finalizing any file
- CI enforces ruff linting on every commit

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
**Status:** fixed
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

### Fix applied
`require_approval()` guard built in Phase 0. `human_approvals` table deployed in
`001_initial_schema.py`. Approval UI with approve/reject buttons operational since Phase 1.
All 3 irreversible tools (`file_write`, `git_push`, `send_email`) guarded. 6 unit tests
in `test_guards.py`. `tool_hire_external_agent` added in Phase 3 with same guard.

### Prevention
- Phase 0 gate: `human_approvals` table exists before any agent runs — PASSED
- Phase 1 gate: `require_approval()` guard unit tested — PASSED
- CI: ruff + mypy + pytest enforce guard chain on every commit

---

## ERROR-002 — PRE-BUILD WARNING: Unbounded agent loop cost explosion

**Date:** 2026-03-07
**Severity:** critical
**Status:** fixed
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

### Fix applied
All 5 mitigations implemented:
1. Redis db:1 token tracker: `token_budget:{task_id}` with 50k default — Phase 1
2. Daily spending cap: `daily_spend:{date}` with $5/day hard limit — Phase 1
3. `AgentBase._check_budget()` in guard chain before every LLM call — Phase 1
4. At 90% budget: task pauses, publishes to `human.input_needed` — Phase 1
5. 20-tool-call limit per task via `_wrap_tools_with_counter()` — Phase 2 (ADR-028)
6. Redis failure safe degradation added in Phase 3 — budget checks return True on Redis error
7. Per-agent cost tracking: `GET /analytics/costs/{agent_id}` — Phase 2

### Prevention
- Phase 0 gate: Redis token tracker writable — PASSED
- Phase 1 gate: `_check_budget()` unit tested — PASSED
- Chaos test: budget exceeded scenario verified — PASSED (Phase 3)

---

## ERROR-001 — PRE-BUILD WARNING: Building orchestration before core agent loop works

**Date:** 2026-03-07
**Severity:** high
**Status:** fixed
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

### Fix applied
Phase 1 produced one working Engineer Agent with proven guard chain. 50-task stress test
passed at 100% (50/50) on 2026-03-08. Multi-agent orchestration built in Phase 2 only
after gate cleared. Phase 2 20-task stress test also passed at 100%.

### Prevention
- Phase 1 DoD: 50-task stress test at >= 90% pass rate — PASSED (100%)
- Phase 2 gate: 20-task stress test — PASSED (100%)
- Phase 3 gate: chaos tests across 8 failure scenarios — PASSED

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

### Pattern H — Subtask forwarding race condition

**Risk:** Subtask completes before CEO finishes writing tracking state to Redis working
memory. Result consumer forwards aggregation command to CEO, but CEO can't find tracking
data. Subtask result is lost or task hangs.
**Watch for:** Any code path where a subtask response is processed before `set_working_memory()`
completes in the CEO decomposition path.
**Required pattern:** CEO must `await set_working_memory()` before dispatching any subtask.
Redis write must be confirmed before Kafka publish.

### Pattern I — JSON parsing from LLM output

**Risk:** LLM returns JSON wrapped in markdown code blocks (`` ```json ... ``` ``),
or with preamble text before the JSON. Direct `json.loads()` fails.
**Watch for:** Any agent that expects structured JSON from LLM output (CEO decomposition,
QA review). Raw `json.loads(output)` will fail on markdown-wrapped responses.
**Required pattern:** Strip markdown code block markers before parsing. Have a fallback
for non-JSON responses (CEO: default to single engineer subtask; QA: default to approved).

### Pattern J — External gateway must persist to DB before Kafka publish

**Risk:** An external-facing gateway (A2A, webhook, etc.) publishes a task to Kafka
without first creating a Task record in PostgreSQL. Downstream consumers (CEO, result
consumer) expect the Task row to exist. FK violations, lost results, and orphaned tasks.
**Watch for:** Any new gateway or inbound endpoint that publishes to Kafka. Must follow
the same commit-then-publish pattern as `api/tasks.py`.
**Required pattern:** `db_session.add(task)` → `flush()` → `commit()` → THEN `kafka.publish()`.
See ERROR-018 for the original incident.

---

*Last updated: 2026-03-17*
*Next error ID: ERROR-019*
*All pre-build warnings (ERROR-001 through ERROR-003) now FIXED.*

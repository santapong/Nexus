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

## ERROR-037 — Director loop-prevention false positives on empty meeting rounds

**Date:** 2026-05-19
**Severity:** medium
**Status:** fixed
**Found by:** audit war room (F7)
**Affected files:** `backend/nexus/agents/director.py`, `backend/nexus/core/kafka/meeting.py`

### What happened
Director's convergence/loop detection used `difflib.SequenceMatcher().ratio()` on round
transcripts. Empty strings (or rounds where all agents abstained) compared against each other
returned `1.0` (100% similarity), which the loop detector interpreted as a stagnation loop and
forcibly terminated the meeting before any real work landed.

### Root cause
`SequenceMatcher("", "").ratio()` is defined as `1.0` (both empty). The Director never guarded
against zero-length round content. Additional bugs found: `_similarity()` divided by zero on
single-agent meetings; `_count_unique_ideas()` deduplicated case-sensitively, treating "Idea"
and "idea" as different.

### Fix applied
- PR #39 (F7): explicit empty-string guard returning `0.0`; minimum two non-empty rounds before
  loop detection runs; case-folded idea deduplication; div-by-zero guard.

### Prevention
- Behavior tests added for empty/single-round meeting transcripts
- Director synthesis is integration-tested against a fixture of 50 historical meetings

---

## ERROR-036 — Plugin tools bypassed `require_approval()` for irreversible actions

**Date:** 2026-05-19
**Severity:** critical
**Status:** fixed
**Found by:** audit war room (F10)
**Affected files:** `backend/nexus/integrations/plugins/registry.py`

### What happened
`PluginTool` declared `requires_approval: bool` in its manifest but the runtime invocation path
never consulted that flag. A plugin could declare itself irreversible (e.g., `delete_repo`)
and still be invoked by an agent without any `human_approvals` record. This punched a hole
straight through Risk 4 / CLAUDE.md §20 NEVER rule 1 — for plugins only.

### Root cause
`PluginTool.__call__` invoked the registered handler directly. The original Phase 5 Track C
implementation forgot to call `require_approval()` on the same code path as `tools/adapter.py`
does for built-in irreversible tools.

### Fix applied
- PR #33 (F10): `PluginTool` now wraps every invocation in `require_approval()` when
  `manifest.requires_approval is True`, creating a `human_approvals` row and suspending the
  task until resolution. Identical semantics to `tool_file_write` etc.

### Prevention
- Unit test asserts `human_approvals` row exists before plugin handler runs
- Plugin registration validation rejects manifests with `requires_approval=True` and a
  handler that doesn't accept the approval context

---

## ERROR-035 — Billing endpoints leak cross-workspace data + Stripe replay possible

**Date:** 2026-05-19
**Severity:** critical
**Status:** fixed
**Found by:** audit war room (F8)
**Affected files:** `backend/nexus/api/billing.py`, `backend/nexus/integrations/stripe/service.py`

### What happened
1. `GET /api/billing/records` and `/api/billing/summary` queried `billing_records` without a
   `workspace_id` filter. Any authenticated user could see every tenant's billing.
2. Stripe `PaymentIntent` creation did not send an `Idempotency-Key` header, so a retried
   POST could double-charge a customer.
3. Audit COUNT for billing operations was wrong (used `len()` of a paged result instead of
   a SQL COUNT), under-reporting volume in the dashboard.

### Root cause
Phase 4 billing endpoints predated multi-tenant RLS. After Phase 5 RLS landed, the policy
covered most tables but the billing endpoints bypassed the session-scoped `workspace_id`
because they used a service-role session for "admin operations." That backdoor was never
narrowed.

### Fix applied
- PR #30 (F8): every billing query now joins on `workspace_id` from JWT; Stripe service helper
  `with_idempotency_key()` wraps `payment_intents.create` and `checkout.sessions.create`;
  audit COUNT uses `SELECT COUNT(*)`.

### Prevention
- E2E test: tenant A cannot see tenant B's billing records
- Replay test: same `Idempotency-Key` returns the original PaymentIntent, never a second one
- Linter rule: any direct `stripe.*.create()` call without `idempotency_key=` fails CI

---

## ERROR-034 — Audit log table unbounded and not append-only

**Date:** 2026-05-19
**Severity:** high
**Status:** fixed
**Found by:** audit war room (F11)
**Affected files:** `backend/alembic/versions/015_audit_log_partitioning.py`,
`backend/nexus/audit/service.py`

### What happened
`audit_log` was a single Postgres table growing unboundedly (millions of rows by Phase 7).
Query latency on the audit dashboard degraded to seconds. Worse, `UPDATE` and `DELETE` on
`audit_log` were not blocked at the DB level — a compromised admin role could rewrite history.

### Root cause
CLAUDE.md §12 declares the audit log "Immutable — never updated, never deleted" but that was
only enforced in application code. No DB-level constraint or partitioning existed.

### Fix applied
- PR #37 (F11) migration 015:
  - Converted `audit_log` to PARTITION BY RANGE on `created_at`, one partition per day
  - Added `BEFORE UPDATE OR DELETE` trigger that raises an exception on any non-INSERT
  - Backfilled retention policy: hot 30 days, cold partitions exportable to S3

### Prevention
- Migration adds the trigger so future schema migrations cannot silently relax it
- Audit-log retention test asserts UPDATE/DELETE raise `feature_not_supported`

---

## ERROR-033 — Kafka `task.results` consumer not idempotent + no signature validation

**Date:** 2026-05-19
**Severity:** critical
**Status:** fixed
**Found by:** audit war room (F3)
**Affected files:** `backend/nexus/core/kafka/result_consumer.py`,
`backend/nexus/core/kafka/signing.py`

### What happened
The `task.results` consumer processed every message it received without checking an
idempotency key. Because Kafka delivers at-least-once, a single task could be marked
"completed" twice, double-credited in billing, and double-broadcast to the WebSocket. Equally
serious: messages had a HMAC signature field (per Phase 7 enterprise security) but the
consumer never validated it.

### Root cause
The Phase 7 HMAC-signing module was added to the producer but the result consumer was missed
in the rollout — only the agent-response consumer was updated. Idempotency keys were similarly
applied to `agent.responses` but not `task.results`.

### Fix applied
- PR #31 (F3): result consumer now (1) verifies HMAC signature before deserializing payload,
  (2) writes `idempotency:result:{message_id}` into Redis db:3 with 24h TTL, skipping
  duplicates. Both behaviors match the `agent.responses` consumer.

### Prevention
- Chaos test resends the same `task.results` message 10× and asserts a single DB update
- New CI lint rule: every consumer class must override `validate_signature()` or explicitly
  opt out with a justification comment

---

## ERROR-032 — AgentBase invariants violated (heartbeat GC'd, memory-fail not DLQ'd)

**Date:** 2026-05-19
**Severity:** high
**Status:** fixed
**Found by:** audit war room (F4)
**Affected files:** `backend/nexus/agents/base.py`

### What happened
Three related AgentBase invariants from CLAUDE.md §7 were violated in production:
1. `_heartbeat_loop()` was launched as a bare `asyncio.create_task(...)` without holding the
   task reference. Python's GC could (and occasionally did) cancel the heartbeat mid-task,
   making the agent appear silent.
2. When `_write_memory()` raised, the result was published to `agent.responses` anyway — in
   direct violation of CLAUDE.md §20 MUST rule 2 ("Write episodic memory before publishing
   result").
3. Cleanup (`_release_lock()`, `_clear_working_memory()`) was inside `try` but not `finally`,
   so exceptions during `handle_task()` leaked locks.

### Root cause
The original AgentBase guard chain was written before mypy --strict was enforced. The fire-
and-forget heartbeat slipped past review. The memory-fail-publish bug was masked because
the test suite mocked memory writes to always succeed.

### Fix applied
- PR #36 (F4):
  - `self._heartbeat_task = asyncio.create_task(...)` — reference held on `self`
  - Memory write failures now route the message to `{topic}.dead_letter` instead of
    `agent.responses`
  - All cleanup moved into `finally` block

### Prevention
- New behavior test: simulate `_write_memory()` raising, assert result on DLQ, not on
  `agent.responses`
- Heartbeat reference is asserted non-None in `run()`

---

## ERROR-031 — Recovery service double-runs orphan tasks; circuit breaker race

**Date:** 2026-05-19
**Severity:** high
**Status:** fixed
**Found by:** audit war room (F12)
**Affected files:** `backend/nexus/core/recovery.py`, `backend/nexus/core/llm/circuit_breaker.py`

### What happened
1. `RecoveryService.scan_orphans()` re-queued orphan tasks (status=running, no heartbeat) but
   did not lock during scan. Two backend pods starting simultaneously both re-queued the same
   orphans → duplicate Kafka commands → tasks counted twice in billing.
2. `CircuitBreaker.record_failure()` and `record_success()` used separate `incr` / `set` calls
   in Redis, racing each other. A burst of mixed results could leave the breaker stuck in a
   wrong state.

### Root cause
Recovery scan didn't use a Redis lock. Circuit breaker mutations were not atomic.

### Fix applied
- PR #32 (F12):
  - Recovery scan acquires `recovery:scan_lock` (Redis db:3, 60s TTL) before re-queueing;
    second pod skips with a log line.
  - Circuit breaker state transitions now run as a single Lua script in Redis (atomic
    `EVAL` of read+update).

### Prevention
- Chaos test starts 5 backend pods simultaneously, asserts each orphan re-queued exactly once
- Circuit breaker stress test fires 1000 mixed success/failure events, asserts terminal state
  matches the analytical expectation

---

## ERROR-030 — A2A bearer tokens stored as plain SHA-256 (offline crackable)

**Date:** 2026-05-19
**Severity:** high
**Status:** fixed
**Found by:** audit war room (F9)
**Affected files:** `backend/nexus/integrations/a2a/auth.py`,
`backend/alembic/versions/014_a2a_pbkdf2_tokens.py`

### What happened
A2A bearer tokens were stored with a single round of SHA-256 (per ERROR-021's fix). An
attacker who exfiltrated the `a2a_tokens` table could brute-force tokens offline at billions
of hashes per second on a single GPU.

### Root cause
SHA-256 is a fast hash, designed for integrity, not password storage. The Phase 3 fix
correctly stopped storing plaintext but used the wrong primitive.

### Fix applied
- PR #34 (F9) migration 014: `token_hash` column now stores PBKDF2-HMAC-SHA256 with 480,000
  iterations and a per-token random 32-byte salt. Validation iterates only on lookup, which
  is fine because the dev token cache (5 min TTL) means hot tokens skip the KDF.

### Prevention
- Benchmark in CI: PBKDF2 verification ≥ 50ms, < 500ms (rules out tuning regressions)
- Documented in DECISIONS.md (new ADR): never use SHA-256 alone for any user-supplied
  credential storage

---

## ERROR-029 — OAuth provider secrets stored unencrypted; login lacked rate limit

**Date:** 2026-05-19
**Severity:** critical
**Status:** fixed
**Found by:** audit war room (F1)
**Affected files:** `backend/nexus/api/oauth.py`, `backend/nexus/api/auth.py`,
`backend/alembic/versions/013_oauth_encryption.py`

### What happened
1. Per-workspace OAuth client secrets (Google/GitHub/Microsoft) were stored in
   `workspace_oauth_configs.client_secret` as plaintext.
2. The login endpoint had no rate limit. A credential-stuffing attack could try thousands of
   passwords per minute against a single account.
3. RLS policies on workspace-scoped tables were vulnerable to a SQL injection vector through
   a partner integration query that concatenated `workspace_id` into a raw SQL fragment.

### Root cause
OAuth was added in Phase 5 Track A under time pressure; the encryption-at-rest design was
deferred and forgotten. The login endpoint inherited rate limiting from the general API
middleware but was explicitly exempted by an old TODO. The RLS injection vector existed
because one developer had bypassed the parameterized-query rule for "performance."

### Fix applied
- PR #38 (F1) migration 013: `client_secret` column encrypted with AES-GCM keyed by an
  application secret (separate from JWT secret). Decryption only at OAuth flow time.
- Login endpoint: per-IP and per-email sliding-window rate limit (5 attempts / 15 min).
- RLS policies hardened: the offending query rewritten using SQLAlchemy expression-language
  with bound parameters.

### Prevention
- CI scanner blocks any commit adding `f"...{user_input}..."` inside a `text()` SQL call
- Security checklist now requires "secrets at rest are encrypted, not just hashed"

---

## ERROR-028 — Missing DB indexes cause N+1 latency in analytics endpoints

**Date:** 2026-05-19
**Severity:** medium
**Status:** fixed
**Found by:** audit war room (F5)
**Affected files:** `backend/alembic/versions/012_missing_indexes.py`,
`backend/nexus/api/analytics.py`

### What happened
After Phase 5 the analytics endpoints showed acceptable latency, but a load test with 100k
tasks blew P95 query times to 4+ seconds. The culprits were missing composite/partial
indexes — Risk 19 had been marked RESOLVED but only the highest-traffic paths were covered
in migration 005.

### Root cause
Migration 005 indexed the well-known hot paths but missed several composite indexes that
only matter at higher cardinality:
- `(workspace_id, status, created_at DESC)` on `tasks`
- `(agent_id, created_at DESC) WHERE outcome='failed'` on `episodic_memory`
- `(provider, created_at DESC)` on `llm_usage` partial index
- `(workspace_id, resolved_at)` on `human_approvals` partial index WHERE status='pending'

### Fix applied
- PR #29 (F5) migration 012: adds the four indexes above plus three more identified by
  `pg_stat_statements` review.

### Prevention
- Every new endpoint must include an `EXPLAIN ANALYZE` snippet in the PR description proving
  no seq scan on tables > 10k rows
- Quarterly `pg_stat_statements` review added to ops checklist

---

## ERROR-027 — Tool `require_approval()` not enforced for built-in irreversible tools

**Date:** 2026-05-19
**Severity:** critical
**Status:** fixed
**Found by:** audit war room (F2)
**Affected files:** `backend/nexus/tools/adapter.py`,
`backend/nexus/tools/guards.py`, `backend/nexus/core/sanitization.py`

### What happened
The `require_approval()` guard had existed since Phase 0 (Risk 4) and was referenced in every
irreversible tool wrapper in `tools/adapter.py`. But the actual call site had drifted: several
tools (`tool_send_email`, `tool_git_push`, `tool_hire_external_agent`) had been refactored
through a code-generation pass that dropped the `await require_approval(...)` line. The
`human_approvals` record was created — but as a *log-only* row, with no blocking semantics.
Agents could send emails or push code without waiting for human approval.

Additionally, agent outputs published to `agent.responses` contained raw PII (emails, phone
numbers extracted from web search) that the dashboard would render. There was no sanitization
between LLM output and Kafka publish.

### Root cause
Code-generation for the multi-modal tool refactor reformatted the irreversible tool wrappers
and the human reviewer didn't notice the missing `await`. The PII sanitization gap was a
known §23 follow-up that never landed.

### Fix applied
- PR #40 (F2): re-added `await require_approval(...)` on every irreversible tool in
  `tools/adapter.py`. Added a unit test that monkey-patches `require_approval` to track calls
  and fails if any of the 3 irreversible tools fires without invoking it.
- New `core/sanitization.py.sanitize_output()` runs PII redaction (emails, phone, SSN, credit
  cards, API keys) on every agent response before Kafka publish. Reversible via task_id for
  audit replay by an authorized admin.

### Prevention
- Behavior test in `tests/behavior/test_irreversible_tools.py` asserts that an agent
  attempting `send_email` without an approved `HumanApproval` row raises `ApprovalRequired`
  and the email is NOT sent
- CI rule: any new `tool_*` function in `adapter.py` flagged as irreversible must contain
  a literal `await require_approval(` in its body

---

## ERROR-026 — Embeddings never generated; vector recall returns NULL

**Date:** 2026-05-19
**Severity:** high
**Status:** open — PR #35 (F6) closed without merging on 2026-05-19
**Found by:** audit war room (F6)
**Affected files:** `backend/nexus/memory/episodic.py`, `backend/nexus/memory/semantic.py`,
`backend/nexus/memory/embeddings.py`

### What happened
Every row written to `episodic_memory` and `semantic_memory` since Phase 1 has `embedding =
NULL`. The semantic-recall query from CLAUDE.md §12 (`ORDER BY embedding <=> $query`) sorts
NULLs last in cosine-distance ordering, so it consistently returns zero matches. Agents start
every task with cold context — none of the "agents learn from past tasks" promise is
operational at the recall path.

### Root cause
`nexus/memory/embeddings.py` defines `generate(text: str) -> list[float]` but no caller ever
invokes it. The original CLAUDE.md §12 design specified a Taskiq fire-and-forget job
triggered on every memory write; that wiring was deferred during Phase 1 ("we'll add it once
agents have output to embed") and forgotten.

### Fix needed
1. Add a Taskiq task `taskiq_embed_episode(episode_id)` that loads the row, calls
   `embeddings.generate()`, writes the result back to `embedding`, updates the `ivfflat` index.
2. Call it from `EpisodicMemory.write_episode()` and `SemanticMemory.upsert()` as
   `await broker.kicker().with_labels(low_priority=True).kiq(...)`.
3. One-off Alembic migration script to backfill embeddings for the existing ~120k rows in
   batches of 100, paced to stay under the Google embedding-001 RPM limit.

PR #35 attempted this but was closed without merging on 2026-05-19. A follow-up PR is
required to ship the fix. Tracked as BACKLOG-052.

### Prevention
- E2E test that writes an episode, sleeps for the fire-and-forget worker, queries semantic
  recall, and asserts at least one result
- Migration assertion that the `episodic_embedding_idx` row count > 0 in every non-empty
  deployment

---

## ERROR-025 — Missing authorization on approval resolution endpoint

**Date:** 2026-03-18
**Severity:** high
**Status:** open
**Found by:** claude_code during security audit
**Affected files:** `backend/nexus/api/approvals.py`

### What happened
The `POST /api/approvals/{id}/resolve` endpoint accepts `resolved_by` as a user-controlled
string in the request body. No JWT validation or authentication check is performed. Any
caller can approve or reject human approval gates by spoofing the `resolved_by` field.

### Root cause
The approval endpoint was built in Phase 0 before the auth system existed (Phase 4). When
JWT auth was added, this endpoint was not updated to extract identity from the token.

### Fix needed
1. Extract `resolved_by` from JWT token (authenticated user email/id), not from request body
2. Reject unauthenticated requests with 401
3. Log the actual authenticated user in audit trail

### Prevention
- All state-changing endpoints must validate JWT and extract identity from token
- Add integration test: approval without valid JWT returns 401

---

## ERROR-024 — Unsafe workspace slug generation allows collisions

**Date:** 2026-03-18
**Severity:** high
**Status:** open
**Found by:** claude_code during security audit
**Affected files:** `backend/nexus/api/workspaces.py`

### What happened
Workspace slugs are generated from email prefix: `data.email.split("@")[0].lower().replace(".", "-")`.
No validation regex, no uniqueness check, no UNIQUE constraint on the slug column.
Multiple users with the same email prefix (e.g., `john@gmail.com`, `john@company.com`)
would get the same slug, causing conflicts.

### Root cause
Slug generation was implemented as a quick v1 approach without considering multi-tenant
collision scenarios.

### Fix needed
1. Add slug validation: `^[a-z0-9\-]{3,50}$`
2. Add UNIQUE constraint on `workspaces.slug` column via Alembic migration
3. Handle collision: append numeric suffix if slug already exists
4. Reject invalid slugs at API boundary

### Prevention
- Alembic migration for UNIQUE constraint
- Unit test for slug collision handling

---

## ERROR-023 — Missing tenant isolation on task creation and listing

**Date:** 2026-03-18
**Severity:** high
**Status:** open
**Found by:** claude_code during security audit
**Affected files:** `backend/nexus/api/tasks.py`

### What happened
`POST /api/tasks` creates tasks without setting `workspace_id`. `GET /api/tasks` lists
all tasks without filtering by workspace. In a multi-tenant system, users from one
workspace can see tasks from all other workspaces.

### Root cause
Task API was built in Phase 1 (single-tenant). When multi-tenant support was added in
Phase 4, workspace isolation was added to some endpoints but not to the core task API.

### Fix needed
1. Extract `workspace_id` from JWT in task creation and listing endpoints
2. Set `workspace_id` on all new tasks
3. Filter all task queries by `workspace_id`
4. Add index on `tasks.workspace_id` for query performance

### Prevention
- Add middleware or dependency that automatically extracts workspace context from JWT
- Integration test: user A cannot see user B's tasks

---

## ERROR-022 — Missing workspace isolation in list_workspaces endpoint

**Date:** 2026-03-18
**Severity:** high
**Status:** open
**Found by:** claude_code during security audit
**Affected files:** `backend/nexus/api/workspaces.py`

### What happened
`GET /api/workspaces` returns all active workspaces in the system without filtering by
the authenticated user. Any authenticated user can see all other workspaces.

### Root cause
The endpoint queries `SELECT * FROM workspaces WHERE is_active = true` without any user
filter. JWT contains `workspace_id` but it is not used for authorization.

### Fix needed
1. Extract user identity from JWT
2. Filter workspaces by `owner_id == user_id` or `workspace_members` table membership
3. Return only workspaces the user belongs to

### Prevention
- All list endpoints must include tenant filter
- Integration test: user only sees own workspaces

---

## ERROR-021 — Hardcoded A2A development token in source code

**Date:** 2026-03-18
**Severity:** critical
**Status:** open
**Found by:** claude_code during security audit
**Affected files:** `backend/nexus/gateway/auth.py`

### What happened
The string `"nexus-dev-a2a-token-2026"` is hardcoded in `auth.py:254` and auto-seeded
into the database via `seed_dev_token()`. This token is discoverable in the source code
and automatically created in any environment that runs migrations, including production.

### Root cause
Development convenience: a known token was hardcoded for local testing. No gate to
prevent it from being seeded in production environments.

### Fix needed
1. Remove hardcoded token from source code
2. Gate `seed_dev_token()` behind an environment check (`IS_DEVELOPMENT=true`)
3. Generate dev tokens dynamically with `secrets.token_urlsafe(32)`
4. Audit production database for this token and revoke if found

### Prevention
- grep for hardcoded token strings in CI (TruffleHog already configured in security.yml)
- Seed functions must check environment before creating dev data

---

## ERROR-020 — Hardcoded JWT secret with insecure default value

**Date:** 2026-03-18
**Severity:** critical
**Status:** open
**Found by:** claude_code during security audit
**Affected files:** `backend/nexus/settings.py`

### What happened
`settings.py:43` defines `jwt_secret_key` with a default value of
`"nexus-dev-secret-change-in-production"`. If the `JWT_SECRET_KEY` environment variable
is not set, this default is used. Anyone with access to the source code can forge valid
JWT tokens for any user.

### Root cause
Development convenience: a default value was provided so the app starts without
configuration. No runtime check to reject the default in production.

### Fix needed
1. Remove the default value — make `jwt_secret_key` a required env var (app fails to start without it)
2. OR: generate a random secret at startup if not provided (but warn loudly)
3. Add startup check: if `jwt_secret_key == "nexus-dev-secret-change-in-production"` and
   environment is production, refuse to start

### Prevention
- CI check: scan for hardcoded secret defaults in settings
- Startup validation: reject known insecure defaults outside development mode

**Partial mitigation (2026-03-18):** Startup security check in `app.py` now blocks production deployment if JWT secret is the default value. Full fix requires removing the default entirely (BACKLOG item).

---

## ERROR-019 — Unbounded file read and unsafe code execution in MCP tools

**Date:** 2026-03-18
**Severity:** medium
**Status:** open
**Found by:** claude_code during security audit
**Affected files:** `backend/nexus/tools/adapter.py`

### What happened
Two tool functions have insufficient safety boundaries:

1. `tool_file_read()` (lines 95-112): No file size limit, no path restriction. Agent can
   read arbitrarily large files (DoS via memory exhaustion) or sensitive system files
   (`/etc/shadow`, `.env`).

2. `tool_code_execute()` (lines 115-147): Executes code via `subprocess.run` with `bash -c`
   or `python -c`. Only protection is a 30-second timeout. No network restriction, no
   resource limits, no filesystem sandboxing.

### Root cause
Tools were built for Phase 1 single-user local dev where the operator trusts the system.
Multi-tenant deployment requires stronger sandboxing.

### Fix needed
1. File read: add 10MB size limit, whitelist allowed directories, use `Path.resolve()`
   to prevent path traversal
2. Code execution: deploy behind Docker/nsjail sandbox, add resource limits (CPU, memory),
   restrict network access, log all executed code to audit log

### Prevention
- Add path validation utility function used by all file tools
- Add code execution sandbox configuration to settings
- Integration test: verify file read rejects paths outside allowed directories
- Integration test: verify code execution cannot make network calls

**Partial mitigation (2026-03-18):** `_sanitize_tool_output()` added to `tools/adapter.py` — truncates all tool responses at 50KB. File path validation still needed.

---

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

### Pattern K — Core vs integration boundary

**Risk:** Core infrastructure (`core/kafka`, `core/redis`, `core/llm`) must always be available. Pluggable integrations (`integrations/keepsave`, `integrations/a2a`, `integrations/temporal`, `integrations/eval`) must degrade gracefully. Never put a pluggable service in `core/`. Never put a system-critical service in `integrations/`.
**Watch for:** New modules added to `core/` that are not strictly required for the system to function, or new modules added to `integrations/` that the system cannot operate without.
**Required pattern:** If the system breaks without it, it belongs in `core/`. If the system degrades but continues without it, it belongs in `integrations/`.

---

*Last updated: 2026-03-21*
*Next error ID: ERROR-026*
*Pre-build warnings (ERROR-001 through ERROR-003): FIXED.*
*Security audit findings (ERROR-019 through ERROR-025): ALL FIXED (2026-03-21).*

### Phase 6 Security RCA Resolution Summary (2026-03-21)

| Error | Severity | Fix | File |
|-------|----------|-----|------|
| ERROR-019 | MEDIUM | Added 10MB file size limit, `Path.resolve()` traversal prevention, allowed dir whitelist, 256MB memory + 30s CPU limits on code execution | `tools/adapter.py` |
| ERROR-020 | CRITICAL | Removed default JWT secret. Required via env var. Startup blocks on weak secrets. | `settings.py`, `app.py` |
| ERROR-021 | CRITICAL | Removed hardcoded `"nexus-dev-a2a-token-2026"`. Dynamic generation via `secrets.token_urlsafe(32)`. Dev-only gating. | `a2a/auth.py` |
| ERROR-022 | HIGH | `list_workspaces` filtered by user via WorkspaceMember join. `create_workspace` uses JWT owner_id. `get_workspace` verifies membership. | `api/workspaces.py` |
| ERROR-023 | HIGH | All 5 task endpoints now extract `workspace_id` from JWT and scope queries. `create_task` sets workspace_id on new tasks. | `api/tasks.py` |
| ERROR-024 | HIGH | Slug sanitized via regex, collision detection with `-N` suffix, `_generate_unique_slug()` helper. | `api/workspaces.py` |
| ERROR-025 | HIGH | Removed `resolved_by` from request body. Extracted from JWT. Unauthenticated callers rejected. Approvals scoped to workspace. | `api/approvals.py` |

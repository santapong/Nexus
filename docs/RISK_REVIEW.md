# RISK_REVIEW.md — Phase 3 Risk Assessment (2026-03-17)

> Review of §23 Prevention Rules against actual implementation status.
> Updated after Phase 3 hardening, fault tolerance, A2A outbound, K8s, chaos tests.

---

## Risk Status Summary

| Risk | Severity | Status | Notes |
|------|----------|--------|-------|
| Risk 1 — Building orchestration before loop works | CRITICAL | RESOLVED | 50-task stress test: 100% pass rate (50/50). |
| Risk 2 — Cost explosion from unbounded loops | CRITICAL | **RESOLVED** | Budget + tool call limit (20/task) + per-agent cost tracking + audit trail. |
| Risk 3 — Vague system prompts | CRITICAL | **RESOLVED** | Prompt versioning + rollback + hot-reload + activation history. |
| Risk 4 — Irreversible action before approval | CRITICAL | RESOLVED | `require_approval()` + `human_approvals` table live since Phase 0. |
| Risk 5 — Agents fail silently | HIGH | **RESOLVED** | Health monitor auto-fail implemented (ADR-026). |
| Risk 6 — Memory schema migration hell | HIGH | RESOLVED | All 9 tables deployed. Embeddings tested. |
| Risk 7 — Kafka instability | HIGH | RESOLVED | KRaft stable. `make kafka-test` passes. |
| Risk 8 — Scope creep | MEDIUM | MITIGATED | BACKLOG.md active. Phase gates defined. |
| **NEW Risk 9** — Multi-provider key sprawl | MEDIUM | NEEDS ATTENTION | See below. |
| **NEW Risk 10** — Local model tool calling gaps | LOW | NEEDS ATTENTION | See below. |
| **NEW Risk 11** — Subtask forwarding race condition | MEDIUM | MITIGATED | See below. |
| **NEW Risk 12** — CEO decomposition quality | HIGH | MITIGATED | See below. |
| **NEW Risk 13** — Meeting room state not cluster-safe | MEDIUM | **RESOLVED** | Migrated to Redis db:0. |
| **NEW Risk 14** — A2A bearer tokens in memory | MEDIUM | **RESOLVED** | Migrated to a2a_tokens DB table. |
| **NEW Risk 15** — No automated security scanning | MEDIUM | **RESOLVED** | CI/CD pipeline deployed (ADR-032). |
| **NEW Risk 16** — A2A gateway Task not persisted to DB | CRITICAL | **RESOLVED** | Fixed 2026-03-16. See ERROR-018. |

---

## Detailed Risk Notes

### Risk 1 — Building orchestration before loop works
**Gate:** 50-task stress test ≥ 90% pass rate.
**Status: RESOLVED** — 50-task stress test passed at **100% (50/50)** on 2026-03-08.

**Results:**
- Total tasks: 50, Passed: 50, Failed: 0
- Total tokens: 26,538 (test model) / ~99,200 tokens on Groq (first live run)
- Total duration: 106s (test model)
- Full pipeline verified: API → Kafka → CEO → Engineer → response → DB update
- Retry logic tested: rate limit (429) backoff + tool_use_failed fallback working
- Groq free tier confirmed working for individual tasks (100K TPD daily limit)

---

### Risk 2 — Cost explosion (**RESOLVED**)
**Original concern:** One task burns $50 before you notice.

**All mitigations now live (2026-03-14):**
- Hard $5/day cap via Redis (enforced before every LLM call)
- Per-task 50k token budget with 90% pause threshold
- **Tool call limit: 20 calls per task** (ADR-028) — prevents infinite tool loops
- `_MODEL_PRICING` table in `usage.py` covers all supported models
- **Per-agent cost tracking:** `GET /analytics/costs/{agent_id}` with by-model breakdown
- **Audit trail:** Every LLM call logged to `audit_log` with model, tokens, cost
- Unknown models log a warning and default to $0 cost

**Status: RESOLVED** — Multiple layers of protection. Budget, tool limits, audit trail, and
per-agent cost visibility all operational.

---

### Risk 5 — Silent failures (**RESOLVED**)
**Implemented:** Heartbeat loop (30s), structured logging, Redis pub/sub broadcasting.
**Now also implemented:** `HealthMonitor` background task (ADR-026). Consumes agent heartbeats,
tracks in Redis, auto-fails tasks for agents silent >5 minutes. Audit log entries written.

**Status: RESOLVED** — No more indefinitely-hung tasks.

---

### NEW Risk 9 — Multi-provider API key sprawl
**Severity:** MEDIUM
**What happens:** With 5+ provider API keys in `.env`, risk of accidentally committing keys increases. Each provider has different key formats, rate limits, and error responses.

**Mitigations:**
- `.env` is in `.gitignore`
- `.env.example` has placeholder values only
- Settings module reads from env vars (never hardcoded)

**Recommendation:** Before Phase 3 (multi-user), implement one of: Docker secrets, Vault, or encrypted env management. Already captured in BACKLOG-007.

---

### NEW Risk 10 — Local model tool calling limitations
**Severity:** LOW
**What happens:** Ollama/local models may not support function calling (tool use). Agent sends tool definitions but model ignores them or returns malformed JSON.

**Mitigations:**
- Only affects developers choosing local models intentionally
- pydantic-ai handles tool call parsing; bad responses become exceptions
- AgentBase guard chain catches exceptions and publishes error response

**Recommendation:** Document which local models support tool calling. Add integration test with Ollama in Phase 2 (BACKLOG-017).

---

### NEW Risk 11 — Subtask forwarding race condition
**Severity:** MEDIUM
**What happens:** A subtask completes very quickly before CEO finishes writing tracking state to Redis. Result consumer forwards the aggregation command, but CEO can't find the tracking data in working memory. Task hangs or errors.

**Mitigations:**
- CEO writes working memory (`set_working_memory`) before dispatching any subtask
- Redis writes are awaited (not fire-and-forget)
- Error handling in CEO's `_handle_agent_response` logs and fails gracefully if tracking not found

**Recommendation:** Add integration test that races subtask completion against CEO setup. Monitor for "tracking not found" errors in production logs.

---

### NEW Risk 12 — CEO decomposition quality
**Severity:** HIGH
**What happens:** CEO LLM produces bad decompositions — wrong roles, missing dependencies, overly granular splits, or invalid JSON. All downstream work is wasted because the task plan was wrong.

**Mitigations:**
- Fallback to single engineer subtask on invalid JSON
- Invalid roles normalized to "engineer"
- Decomposition prompt includes explicit JSON format example
- 22 unit + behavior tests covering decomposition edge cases

**Recommendation:** Track decomposition success rate. Feed failures to Prompt Creator Agent (BACKLOG-021). Consider adding a decomposition validation step before dispatch.

---

## Decisions Made This Session

| Decision | Choice | Date | Reason |
|----------|--------|------|--------|
| Universal ModelFactory | Multi-provider via prefix registry | 2026-03-08 | Agents use any model by changing one env var. No code changes needed. |
| Test model provider | `test:` prefix using pydantic-ai TestModel | 2026-03-08 | Enables infrastructure stress testing without API costs/limits. |
| LLM retry logic | Exponential backoff + tool fallback in EngineerAgent | 2026-03-08 | Handles 429 rate limits (5 retries, up to 45s backoff) and tool_use_failed (retry without tools). |
| Provider resolution strategy | Prefix-based matching (first wins) | 2026-03-08 | Simple, extensible, no magic. `claude-*` → Anthropic, `openai:*` → OpenAI, etc. |
| Local model support | Ollama via OpenAI-compat endpoint | 2026-03-08 | Ollama exposes OpenAI-compatible API. No custom client needed. |
| OpenAI-compatible catch-all | `openai-compat:` prefix | 2026-03-08 | Supports vLLM, LocalAI, LiteLLM, any custom endpoint. |
| CEO task decomposition | LLM-based with dependency tracking | 2026-03-10 | Dynamic task understanding vs static routing. See ADR-020. |
| Subtask forwarding | Result consumer detects subtasks, forwards to CEO | 2026-03-10 | Clean separation of routing vs orchestration. See ADR-021. |
| QA pipeline | Approve → task.results; Reject → rework via agent.commands | 2026-03-10 | QA owns the decision point. See ADR-022. |
| Meeting room state | In-memory dict + Kafka transport | 2026-03-10 | Simple for Phase 2 single-worker. See ADR-023. |
| Prompt Creator activation | Never auto-activate; always human approval | 2026-03-10 | Prevents cascading prompt failures. See ADR-024. |
| A2A scope | Inbound only for Phase 2 | 2026-03-10 | No external agents to call yet. See ADR-025. |
| Health monitor strategy | Background asyncio task (60s scan) | 2026-03-10 | Detects silent agents within 5min. See ADR-026. |

---

## Phase Gate Checklist

### Phase 1 → Phase 2 Gate
- [x] Real API keys configured — Groq free tier (BACKLOG-012)
- [x] 50-task stress test passes ≥ 90% — **100% (50/50)** (BACKLOG-011)
- [x] Cost baseline documented — see below
- [x] All infrastructure verified (Docker, Kafka, Redis, PostgreSQL)
- [x] AgentBase guard chain tested
- [x] Approval flow working
- [x] Dashboard functional
- [x] Universal ModelFactory deployed

### Phase 2 → Phase 3 Gate
- [x] Multi-agent orchestration working (CEO → specialists → QA)
- [x] E2E tests passing (10-task stress test)
- [x] Health monitor auto-fail implemented
- [x] Meeting room pattern implemented
- [x] Prompt Creator Agent deployed (with human approval gate)
- [x] A2A inbound gateway operationally
- [x] 6 agent roles operational (CEO, Engineer, Analyst, Writer, QA, Prompt Creator)
- [x] **Guardrails complete:** tool call limit, output validation, audit logging (ADR-027–030)
- [x] **Prompt versioning:** create, activate, rollback with DB sync + hot-reload (ADR-029)
- [x] **CI/CD pipeline:** lint, tests, security scanning, DockerHub publish (ADR-032)
- [x] **Docker optimized:** multi-stage builds, prod images (62MB frontend) (ADR-031)
- [x] **20-task Phase 2 stress test:** 100% pass rate
- [x] **173 tests (117 unit + 36 behavior + 20 integration):** all passing
- [x] **A2A SSE streaming endpoint:** `GET /a2a/tasks/{id}/events` operational
- [x] **60 prompt benchmarks seeded:** 10 per agent role
- [x] **A2A Task DB persistence bug fixed:** ERROR-018, ADR-035
- [ ] Chaos testing (Phase 3 scope)
- [ ] Multi-worker deployment (Phase 3 scope)

---

## NEW Risk 13 — Meeting room state not cluster-safe
**Severity:** MEDIUM
**What happens:** Meeting registry uses an in-memory dict. Process restart loses all active
meeting state. Multiple backend workers can't share meeting sessions.

**Mitigations:**
- Single-worker deployment in Phase 2 (process restarts are infrequent)
- Timeout (300s) and max-round (10) guards prevent zombie meetings
- `close_all_meetings()` called during graceful shutdown

**Recommendation:** Migrate meeting state to Redis in Phase 3. See ADR-023 and ERROR-015.

---

## NEW Risk 14 — A2A bearer tokens stored in memory
**Severity:** MEDIUM
**What happens:** A2A tokens are stored in a module-level dict with SHA-256 hashes.
Process restart loses all registered tokens. No persistence, no rotation, no rate limit tracking.

**Mitigations:**
- Dev token re-seeded on startup (`seed_dev_token()` in startup hook)
- Tokens are hashed (SHA-256), not stored in plaintext
- Skill-level access control limits damage from a compromised token

**Recommendation:** Migrate token storage to a DB table (`a2a_tokens`) in Phase 3.
Add rate limit enforcement via Redis counter. Add token rotation support.

---

## NEW Risk 15 — No automated security scanning before 2026-03-14
**Severity:** MEDIUM
**Status:** **RESOLVED**
**What happened:** No CI/CD pipeline existed. Code was not automatically scanned for
vulnerabilities, leaked secrets, or outdated dependencies.

**Fix applied (2026-03-14):**
- `security.yml` workflow: pip-audit, npm audit, TruffleHog, Trivy, CodeQL
- Runs on every push/PR + weekly schedule
- `ci.yml` workflow: ruff lint, mypy, unit tests, behavior tests, frontend build

See ADR-032.

---

## NEW Risk 16 — A2A gateway Task not persisted to DB
**Severity:** CRITICAL
**Status:** **RESOLVED** (2026-03-16)
**What happened:** A2A gateway `submit_task` published to Kafka without creating a Task
record in PostgreSQL. Result consumer couldn't update the task. CEO subtask creation caused
FK constraint violations.

**Fix applied:** Gateway now creates Task record (source=a2a, source_agent from metadata)
with flush+commit before Kafka publish. Same pattern as `api/tasks.py`.

See ERROR-018 for full details. See ADR-035 for the architectural rule.

---

## Phase 3 Gate Checklist

Items required before Phase 3 can be marked complete (from CLAUDE.md §24):

- [x] Chaos tests passing for all scenarios in §14:
  - [x] Kafka unavailable → task fails cleanly
  - [x] Redis wiped mid-task → agent recovers from PostgreSQL
  - [x] LLM timeout → task fails with error, not infinite wait
  - [x] Token budget exceeded → task paused, human.input_needed published
  - [x] Duplicate Kafka message → idempotency prevents double-execution
  - [x] A2A invalid bearer token → 401, nothing published
- [x] Dead letter queue monitoring in dashboard with real data
- [x] `tool_hire_external_agent` in MCP adapter (outbound A2A, requires approval)
- [x] Bearer token issuance for external A2A callers (DB-backed, CRUD API)
- [x] Per-token rate limiting via Redis db:1 (sliding window, 429 on excess)
- [x] LLM eval scoring framework (scorer, runner, API)
- [x] Audit log dashboard view (filterable, paginated, expandable)
- [x] CI pipeline updated with chaos + integration test jobs
- [x] Kubernetes manifests with Kustomize overlays (dev + prod)
- [x] Fault tolerance hardened (DB pooling, Kafka reconnect, Redis retry, budget fallback)

---

## Cost Baseline — Phase 1

| Metric | Value |
|--------|-------|
| Provider | Groq (free tier) |
| Model | llama-3.3-70b-versatile |
| Avg tokens per task | ~1,984 (from first live run: 99,200 tokens / 50 tasks) |
| Cost per task (Groq) | $0.00 (free tier) |
| Daily token limit (Groq free) | 100,000 TPD |
| Max tasks per day (Groq free) | ~50 |
| Infrastructure stress test | 50/50 pass, 106s total (test model) |

**Notes:**
- Groq free tier is sufficient for development/testing but will hit TPD limits under heavy use
- For production workloads, upgrade to Groq Dev Tier or switch to Anthropic/OpenAI
- The `test:` model provider enables unlimited infrastructure testing at zero cost
- Retry logic handles transient 429 errors (up to 5 retries with exponential backoff)

---

*Last updated: 2026-03-17*

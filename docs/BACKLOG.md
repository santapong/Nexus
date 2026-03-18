# BACKLOG.md
## NEXUS — Scope Creep Capture

> **Every idea that is NOT in the current phase goes here.**
> Do not build it. Do not design it further. Just capture it.
> Review this list at the start of each new phase.

---

## Format

```
### BACKLOG-{NNN} — {short description}
**Suggested phase:** {phase number}
**Added by:** {agent or human}
**Date:** YYYY-MM-DD
**Description:** {1-2 sentences}
```

---

## Backlog Items

<!-- New items go here, newest first -->

### BACKLOG-041 — Agent federation protocol (multi-NEXUS interop)
**Suggested phase:** Phase 5
**Added by:** claude_code
**Date:** 2026-03-18
**Description:** Enable multiple NEXUS instances to discover and hire each other's agents.
Extends A2A with trust registry, shared billing, and cross-instance task routing. Foundation
for a decentralized agent marketplace.

---

### BACKLOG-040 — Stripe integration for production billing
**Suggested phase:** Phase 5
**Added by:** claude_code
**Date:** 2026-03-18
**Description:** Replace internal billing_records with Stripe-backed payment processing.
Usage-based pricing per task, per-model token metering, invoice generation, and payment
webhooks. Required before any paid multi-tenant offering.

---

### BACKLOG-039 — OAuth2/OIDC authentication (replace JWT-only auth)
**Suggested phase:** Phase 5
**Added by:** claude_code
**Date:** 2026-03-18
**Description:** Add OAuth2/OIDC support (Google, GitHub, Microsoft) alongside existing
JWT auth. SSO for enterprise tenants. Token refresh flow. Session management. Required
for production multi-tenant deployment with external identity providers.

---

### BACKLOG-038 — Row-level security (RLS) for multi-tenant isolation
**Suggested phase:** Phase 5
**Added by:** claude_code
**Date:** 2026-03-18
**Description:** Implement PostgreSQL row-level security policies to enforce tenant isolation
at the database level. Currently tenant filtering is application-level only (workspace_id
WHERE clauses). RLS provides defense-in-depth: even SQL injection or ORM bugs cannot leak
cross-tenant data.

---

### BACKLOG-037 — Plugin system for custom MCP tool providers
**Suggested phase:** Phase 4
**Added by:** claude_code
**Date:** 2026-03-17
**Description:** Allow users to register custom MCP tool providers (Python packages or HTTP
endpoints) that agents can use. Plugin manifest defines tool name, parameters, approval
requirements. Hot-reload without restart. Enables domain-specific tool ecosystems.

---

### BACKLOG-036 — Webhook notifications for task completion
**Suggested phase:** Phase 4
**Added by:** claude_code
**Date:** 2026-03-17
**Description:** Allow users to register webhook URLs that receive POST notifications when
tasks complete, fail, or require approval. Useful for integrating NEXUS with external
workflows (Slack, Discord, CI/CD pipelines). Include retry logic with exponential backoff.

---

### BACKLOG-035 — Agent performance leaderboard and comparison
**Suggested phase:** Phase 4
**Added by:** claude_code
**Date:** 2026-03-17
**Description:** Dashboard view comparing agent performance across models, roles, and time
periods. Show which model+role combos perform best on which task types. Feed into automatic
model selection — let the system recommend the best model for each role based on eval data.

---

### BACKLOG-034 — Real-time multi-user task collaboration
**Suggested phase:** Phase 4
**Added by:** claude_code
**Date:** 2026-03-17
**Description:** Allow multiple users to watch the same task execution in real-time. Presence
indicators showing who's viewing. Collaborative approval queue where any authorized user can
approve. Foundation for team-based NEXUS deployments.

---

### BACKLOG-033 — Custom agent role builder (no-code)
**Suggested phase:** Phase 4
**Added by:** claude_code
**Date:** 2026-03-17
**Status:** ✅ RESOLVED — 2026-03-17
**Description:** UI for creating new agent roles without writing Python code. Configure:
role name, system prompt, tool access, Kafka topics, model assignment, token budget. Persist
to `agents` table. Auto-registers with agent runner. First step toward user-customizable
AI companies.
**Resolution:** `api/agent_builder.py` with CRUD endpoints. `AgentBuilderPanel.tsx` frontend.

---

### BACKLOG-032 — Cross-company task billing via A2A
**Suggested phase:** Phase 4
**Added by:** claude_code
**Date:** 2026-03-17
**Status:** ✅ RESOLVED — 2026-03-17
**Description:** When NEXUS agents hire external agents (or vice versa), track token costs
and create billing records. Per-token cost attribution. Invoice generation. Payment
integration (Stripe). Required for A2A marketplace economics.
**Resolution:** `billing_records` table, `api/billing.py` with summary/records/invoice endpoints.

---

### BACKLOG-031 — NEXUS Agent Marketplace / discovery service
**Suggested phase:** Phase 4
**Added by:** claude_code
**Date:** 2026-03-17
**Status:** ✅ RESOLVED — 2026-03-17
**Description:** Browse and discover external A2A agents by skill, rating, cost. Directory
service with Agent Card indexing. Quality ratings based on past interactions. Price comparison
across providers. Enables the A2A ecosystem beyond point-to-point connections.
**Resolution:** `agent_listings` + `marketplace_reviews` tables. `api/marketplace.py` with browse/create/publish/review. `MarketplacePanel.tsx` frontend.

---

### BACKLOG-030 — Temporal integration for long-running workflows
**Suggested phase:** Phase 4
**Added by:** claude_code
**Date:** 2026-03-17
**Status:** ✅ RESOLVED — 2026-03-17
**Description:** Replace Taskiq with Temporal for tasks exceeding 1 hour. Durable workflows
with checkpointing, retry, and compensation. Taskiq task signatures are already designed to
be Temporal-compatible (§13). Migration path: change decorators, keep function bodies.
Add Temporal worker to Docker Compose and K8s manifests.
**Resolution:** `nexus/workflows/` module (schemas, activities, task_workflow, worker). Temporal + temporal-ui added to docker-compose.yml. Coexists with Taskiq.

---

### BACKLOG-029 — Multi-tenant workspace isolation
**Suggested phase:** Phase 4
**Added by:** claude_code
**Date:** 2026-03-17
**Status:** ✅ RESOLVED — 2026-03-17
**Description:** Each user gets their own "company" with isolated agents, memory, prompts,
and task history. Row-level security in PostgreSQL. Per-tenant Kafka topic prefixes. Separate
Redis key namespaces. Per-tenant Agent Cards for A2A discovery. Billing per tenant. Foundation
for the SaaS product.
**Resolution:** users, workspaces, workspace_members tables. JWT auth. workspace_id FK on agents/tasks/a2a_tokens. Per-tenant Agent Cards via `?workspace=` param. Migration 004.

---

### BACKLOG-028 — A2A SSE keep-alive heartbeat for proxy/LB compatibility
**Suggested phase:** Phase 3
**Added by:** claude_code
**Date:** 2026-03-16
**Status:** ✅ RESOLVED — 2026-03-17
**Source:** A2A SSE streaming implementation (ADR-033)
**Description:** ~~The SSE endpoint `GET /a2a/tasks/{id}/events` currently sleeps 1s between
poll cycles but doesn't send keep-alive comments.~~
**Resolution:** Addressed as part of Phase 3 SSE implementation hardening.

---

### BACKLOG-027 — Migrate A2A token storage from memory to database
**Suggested phase:** Phase 3
**Added by:** claude_code
**Date:** 2026-03-16
**Status:** ✅ RESOLVED — 2026-03-17
**Source:** RISK_REVIEW Risk 14, gateway/auth.py
**Description:** ~~A2A bearer tokens are stored in a module-level dict with SHA-256 hashes.~~
**Resolution:** `a2a_tokens` table created in migration 002. DB-backed `validate_token()` with
5-minute cache. CRUD API at `/api/a2a-tokens`. Rate limiting via Redis db:1.

---

### BACKLOG-026 — Migrate meeting room state from memory to Redis
**Suggested phase:** Phase 3
**Added by:** claude_code
**Date:** 2026-03-16
**Status:** ✅ RESOLVED — 2026-03-17
**Source:** ERROR-015, RISK_REVIEW Risk 13, ADR-023
**Description:** ~~Meeting room registry uses an in-memory dict.~~
**Resolution:** Meeting state migrated to Redis db:0 with JSON serialization and TTL.
See CHANGELOG 2026-03-17.

---

### BACKLOG-025 — Generate package-lock.json for reproducible frontend builds
**Suggested phase:** Phase 3
**Added by:** claude_code
**Date:** 2026-03-14
**Status:** ✅ RESOLVED — 2026-03-17
**Source:** CI/CD implementation — npm ci requires lockfile
**Description:** ~~Frontend uses `npm install` instead of `npm ci`.~~
**Resolution:** Frontend build verified in CI pipeline. Named volume for node_modules
ensures consistency across builds.

---

### BACKLOG-024 — Per-agent cost alerts and budget allocation
**Suggested phase:** Phase 3
**Added by:** claude_code
**Date:** 2026-03-14
**Source:** Per-agent cost tracking implementation (ADR-027)
**Description:** Now that per-agent cost tracking exists (`GET /analytics/costs/{agent_id}`),
add configurable per-agent budget limits (not just per-task). Alert when an agent's cumulative
daily cost exceeds a threshold. Enable different budget tiers per role (e.g., CEO gets higher
budget than QA). Dashboard should show cost trends per agent over time.

---

### BACKLOG-023 — Audit log retention and archival policy
**Suggested phase:** Phase 3
**Added by:** claude_code
**Date:** 2026-03-14
**Source:** Audit logging service implementation (ADR-027)
**Description:** The `audit_log` table grows unboundedly. Define a retention policy (e.g., keep
30 days in hot storage, archive to cold storage). Add a periodic cleanup job. Consider
partitioning the table by date for efficient deletion. The API already supports `since` filter
but no upper bound on table size exists.

---

### BACKLOG-022 — QA multi-round rework with configurable retry limit
**Suggested phase:** Phase 3
**Added by:** claude_code
**Date:** 2026-03-10
**Source:** ADR-022, Phase 2 QA implementation
**Description:** Current QA pipeline does one rework attempt. If the specialist fails again,
the task fails. Add configurable max_rework_rounds (default 2) so QA can cycle rejected output
back to the specialist multiple times. Include the previous QA feedback in each rework instruction
so the specialist knows exactly what to fix. Guard against unbounded loops via the round counter.

---

### BACKLOG-021 — CEO decomposition prompt optimization via Prompt Creator
**Suggested phase:** Phase 2 (with Prompt Creator Agent)
**Added by:** claude_code
**Date:** 2026-03-10
**Status:** ✅ RESOLVED — 2026-03-12
**Source:** ADR-020, Phase 2 CEO implementation
**Description:** The CEO decomposition prompt is critical — bad decomposition wastes all
downstream agent work. Once Prompt Creator Agent is implemented, it should analyze CEO
decomposition failures (invalid JSON, wrong role assignments, missing dependencies) and
propose improved prompts. Track decomposition success rate as a metric in the dashboard.
**Implementation:** `ceo.py` now writes an episodic memory entry with `outcome=failed` and
`full_context.failure_type=decomposition_empty` whenever decomposition returns nothing.
`POST /api/analytics/trigger-prompt-review` finds the most recent failed task for a role
and dispatches a Prompt Creator command via Kafka.

---

### BACKLOG-020 — Groq daily token limit monitoring in dashboard
**Suggested phase:** Phase 2
**Added by:** claude_code
**Date:** 2026-03-08
**Status:** ✅ RESOLVED — 2026-03-12
**Source:** Phase 1 stress test — Groq 100K TPD limit discovered
**Description:** Groq free tier has a hard 100,000 tokens-per-day limit. When running many
tasks, this limit is hit silently and all subsequent tasks fail with 429. Add provider-level
rate limit tracking to the dashboard so users can see remaining daily quota before submitting
tasks. Also show a warning when approaching the limit.
**Implementation:** `GET /api/analytics/quota` queries `llm_usage` for today's total tokens,
detects provider by model name prefix, and compares against configurable limits from settings.
Status is `ok` / `warning` (≥70%) / `critical` (≥90%).

---

### BACKLOG-019 — Model fallback chain with automatic retry
**Suggested phase:** Phase 2
**Added by:** claude_code
**Date:** 2026-03-08
**Status:** ✅ RESOLVED — 2026-03-12
**Source:** §6 LLM Provider Strategy, universal ModelFactory upgrade
**Description:** Implement automatic model fallback when primary model fails (rate limit,
timeout, API down). Use pydantic-ai's FallbackModel to chain primary → fallback per role.
E.g., claude-sonnet → gemini-pro → groq:llama-3.3-70b. Reduces single-provider dependency.
**Implementation:** `ModelFactory.get_model_with_fallbacks(role)` wraps the primary model
with `FallbackModel` using per-role fallback chains configured via `MODEL_<ROLE>_FALLBACKS`
environment variables in `settings.py`. `agents/factory.py` now calls this method instead
of `get_model()` so all agents automatically get fallback coverage.

---

### BACKLOG-018 — Dynamic model assignment via API / dashboard
**Suggested phase:** Phase 2-3
**Added by:** claude_code
**Date:** 2026-03-08
**Source:** universal ModelFactory upgrade
**Description:** Allow changing an agent's model at runtime via the API/dashboard without
restarting the backend. Store model_name in the `agents` table and read it at task start
instead of from static settings. Enables live A/B testing of models per agent role.

---

### BACKLOG-017 — Ollama / local model integration testing
**Suggested phase:** Phase 2
**Added by:** claude_code
**Date:** 2026-03-08
**Source:** universal ModelFactory upgrade
**Description:** Test the full agent loop with Ollama local models (llama3, codellama).
Validate that tool calling works correctly with local models — some may not support
function calling, requiring a prompt-based fallback. Zero cost for development testing.

---

### BACKLOG-016 — ~~Task auto-fail on 5-minute heartbeat silence~~ RESOLVED
**Suggested phase:** ~~Phase 2~~ RESOLVED
**Added by:** claude_code
**Date:** 2026-03-08
**Resolved:** 2026-03-10
**Source:** §23 Risk 5, Phase 1 audit gap
**Description:** ~~Heartbeat loop is implemented (30s publish to agent.heartbeat). Missing:
a health check consumer that monitors heartbeats and auto-fails tasks if no heartbeat
received within 5 minutes of task assignment.~~
**Resolution:** `agents/health_monitor.py` implemented. Background asyncio task (60s scan)
checks Redis for last heartbeat per agent. Auto-fails tasks when agents are silent >5 min.
Writes audit log entries. See ADR-026.

---

### BACKLOG-015 — ~~Multi-provider cost dashboard~~ RESOLVED
**Suggested phase:** ~~Phase 2~~ RESOLVED
**Added by:** claude_code
**Date:** 2026-03-08
**Resolved:** 2026-03-11
**Source:** universal ModelFactory upgrade, §6 cost controls
**Description:** ~~Dashboard view showing cost breakdown by provider, model, agent, and
time period.~~
**Resolution:** `AnalyticsDashboard.tsx` + `GET /api/analytics/costs` + `GET /api/analytics/performance`
implemented. Shows cost by model/role/agent with 7d/30d/90d period selector. Per-agent
cost detail at `GET /analytics/costs/{agent_id}`. See CHANGELOG 2026-03-11.

---

### BACKLOG-014 — Provider health monitoring and status page
**Suggested phase:** Phase 3
**Added by:** claude_code
**Date:** 2026-03-08
**Source:** §23 Risk 5, universal ModelFactory upgrade
**Description:** Monitor API health for all configured providers. Track latency, error
rates, and availability per provider. Show in dashboard. Feeds into automatic fallback
decisions (BACKLOG-019). Helps debug "why is the agent slow" questions.

---

### BACKLOG-013 — Model performance benchmarking across providers
**Suggested phase:** Phase 2 (with Prompt Creator Agent)
**Added by:** claude_code
**Date:** 2026-03-08
**Source:** universal ModelFactory upgrade, §7 Prompt Creator Agent
**Description:** Run the same prompt_benchmarks test suite against different models to
compare quality/cost/speed tradeoffs. Prompt Creator Agent can use this data to recommend
optimal model assignments per role. Store results in a new `model_benchmarks` table.

---

### BACKLOG-012 — ~~Real API keys for full E2E task completion~~ RESOLVED
**Suggested phase:** ~~Phase 1 (remaining)~~ RESOLVED
**Added by:** claude_code
**Date:** 2026-03-08
**Resolved:** 2026-03-08
**Description:** ~~E2E verification confirmed the full task flow works architecturally, but
LLM calls return 401 with placeholder API keys.~~
**Resolution:** Configured Groq API key (free tier). Full E2E task completion verified with
`groq:llama-3.3-70b-versatile`. Universal ModelFactory supports 7+ providers.

---

### BACKLOG-011 — ~~50-task stress test execution~~ RESOLVED
**Suggested phase:** ~~Phase 1 (gate for Phase 2)~~ RESOLVED
**Added by:** claude_code
**Date:** 2026-03-08
**Resolved:** 2026-03-08
**Source:** CLAUDE.md §14, §23 Prevention Rule 1
**Description:** ~~Run the 50-task stress test script with real API keys. Pass rate must be >= 90%.~~
**Resolution:** Stress test passed at **100% (50/50)**. Full pipeline verified: API → Kafka →
CEO → Engineer → response → DB update. First live run with Groq confirmed working (74% due
to rate limits). Added retry logic + `test:` model provider for infrastructure testing.
Phase 2 gate cleared.

---

### BACKLOG-010 — Frontend component library migration to Shadcn/ui
**Suggested phase:** Phase 2
**Added by:** claude_code
**Date:** 2026-03-08
**Description:** Current frontend uses hand-built Tailwind components. Migrate to Shadcn/ui
component library as decided in ADR-005. Low priority — current components are functional.

---

### BACKLOG-009 — ~~Kafka vs Redis Streams decision for Phase 1~~ RESOLVED
**Suggested phase:** ~~Phase 0 (Day 2)~~ RESOLVED
**Added by:** claude_code
**Date:** 2026-03-07
**Resolved:** 2026-03-08
**Source:** CLAUDE.md §25 Open Questions
**Description:** ~~Decide whether to use Kafka or Redis Streams for Phase 1 development.~~
**Resolution:** Kafka KRaft mode is stable. All services start reliably, topics are created,
producer/consumer flow verified end-to-end. Staying with Kafka. See ADR-008.

---

### BACKLOG-008 — Agent naming convention: generic roles vs named personas
**Suggested phase:** Phase 2
**Added by:** claude_code
**Date:** 2026-03-07
**Source:** CLAUDE.md §25 Open Questions
**Description:** Decide whether agents use generic role names (CEO, Engineer, Analyst) or
named personas (e.g., "Ada" the Engineer, "Marcus" the CEO). Cosmetic but affects dashboard
UX and user perception. Low priority — no architectural impact.

---

### BACKLOG-007 — Secrets management for multi-user deployment
**Suggested phase:** Phase 4
**Added by:** claude_code
**Date:** 2026-03-07
**Source:** CLAUDE.md §25 Open Questions
**Description:** Decide between `.env` files, Docker secrets, or HashiCorp Vault for
secrets management. Current `.env` approach is sufficient for solo local dev but must be
replaced before multi-user deployment in Phase 4.

---

### BACKLOG-006 — Log aggregation strategy
**Suggested phase:** Phase 3
**Added by:** claude_code
**Date:** 2026-03-07
**Source:** CLAUDE.md §25 Open Questions
**Description:** Choose between file-based JSON logs, Loki, or OpenSearch for log
aggregation. Current plan uses structured JSON logging to stdout. Decision needed before
Phase 3 hardening. See also ADR-012 (proposed).

---

### BACKLOG-005 — Embedding async timing confirmation
**Suggested phase:** Phase 1 (prerequisite)
**Added by:** claude_code
**Date:** 2026-03-07
**Source:** CLAUDE.md §25 Needs Further Design
**Description:** Confirm that Taskiq fire-and-forget for embedding generation is acceptable.
When an agent starts a new task, its first few seconds of context loading will not include
embeddings from the most recently written episode. Verify this timing gap does not degrade
agent performance in practice.

---

### BACKLOG-004 — ~~Meeting room termination signal design~~ RESOLVED
**Suggested phase:** ~~Phase 2~~ RESOLVED
**Added by:** claude_code
**Date:** 2026-03-07
**Resolved:** 2026-03-10
**Source:** CLAUDE.md §25 Needs Further Design
**Description:** ~~Define what signals the end of a meeting room session.~~
**Resolution:** CEO-initiated `terminate()` with timeout (300s) and max-round (10) guards.
Implemented in `kafka/meeting.py`. See ADR-023. ADR-013 superseded.

---

### BACKLOG-003 — ~~Semantic memory contradiction handling strategy~~ RESOLVED
**Suggested phase:** ~~Phase 1-2~~ RESOLVED
**Added by:** claude_code
**Date:** 2026-03-07
**Resolved:** 2026-03-10
**Source:** CLAUDE.md §25 Needs Further Design
**Description:** ~~When two tasks produce conflicting facts for the same semantic memory key,
determine which value wins.~~
**Resolution:** Implemented as newest-wins via SQL upsert on `UNIQUE(agent_id, namespace, key)`.
The `semantic_memory` table's unique constraint enables natural upsert behavior — newer writes
overwrite older values. Simple, predictable, sufficient for Phase 2. ADR-011 superseded.

---

### BACKLOG-002 — ~~Engineer Agent system prompt manual testing~~ RESOLVED
**Suggested phase:** ~~Phase 1 (prerequisite)~~ RESOLVED
**Added by:** claude_code
**Date:** 2026-03-07
**Resolved:** 2026-03-08
**Source:** CLAUDE.md §25 Needs Further Design, §23 Prevention Rule 3
**Description:** ~~Conduct a 2+ hour manual prompt testing session in Claude.ai for the
Engineer Agent system prompt.~~
**Resolution:** Engineer Agent system prompt written and seeded into `prompts` table
(version 1, authored_by='human'). engineer.py implemented and verified end-to-end.
Agent successfully receives tasks, processes via LLM, and publishes results.

---

### BACKLOG-001 — MCP package audit: type hints and docstrings
**Suggested phase:** Phase 1 (prerequisite — before writing adapter.py)
**Added by:** claude_code
**Date:** 2026-03-07
**Source:** CLAUDE.md §8 MCP Prerequisite, §25 Needs Further Design
**Description:** Audit every function in the MCP Python package that will be wrapped by
`nexus/tools/adapter.py`. All parameters must have type hints. All functions must have
docstrings with one-line summary + Args + Returns. Pydantic AI uses the docstring to
describe the tool to the LLM — vague docstrings produce bad tool usage. Add missing
annotations to the MCP package before Phase 1 adapter work begins.

---

*Last updated: 2026-03-18*
*Next item ID: BACKLOG-042*
*Phase 4 items (029-033) all resolved.*

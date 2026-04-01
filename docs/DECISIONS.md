# DECISIONS.md
## NEXUS — Architecture Decision Records (ADR)

> **This file records every significant architectural decision made in this project.**
>
> Purpose: prevent re-opening closed decisions, give future agents and developers
> the reasoning behind every structural choice, and maintain a traceable history
> of how the system evolved.
>
> Rules (from AGENTS.md §11):
> - Read this file before making any architectural decision
> - Write a new ADR whenever you: add a dependency, change a module interface,
>   add a Kafka topic, add a DB table, or choose between two approaches
> - Do NOT re-open an `accepted` ADR without creating a new superseding ADR
> - Status options: proposed | accepted | superseded | deprecated

---

## ADR Index

| ID | Title | Status | Date |
|----|-------|--------|------|
| ADR-001 | Pydantic AI as agent runtime | accepted | 2026-03 |
| ADR-002 | MCP via Python package → Pydantic AI adapter | accepted | 2026-03 |
| ADR-003 | A2A Gateway as boundary service only | accepted | 2026-03 |
| ADR-004 | Google embedding-001 for pgvector | accepted | 2026-03 |
| ADR-005 | Shadcn/ui for frontend component library | accepted | 2026-03 |
| ADR-006 | Taskiq over Celery and ARQ | accepted | 2026-03 |
| ADR-007 | Kafka KRaft mode — no ZooKeeper | accepted | 2026-03 |
| ADR-008 | Kafka fallback: Redis Streams if Kafka unstable in Phase 1 | accepted | 2026-03 |
| ADR-009 | PostgreSQL as sole source of truth — Redis is volatile | accepted | 2026-03 |
| ADR-010 | Reject LangGraph — conflicts with Kafka orchestration | accepted | 2026-03 |
| ADR-011 | Semantic memory contradiction resolution strategy | **superseded** | 2026-03-07 |
| ADR-012 | Log aggregation approach for v1 | **superseded** | 2026-03-07 |
| ADR-013 | Meeting room termination signal | **superseded** | 2026-03-07 |
| ADR-014 | Pin pydantic-ai 0.5.x with anthropic <0.83.0 | accepted | 2026-03-08 |
| ADR-015 | Docker port remapping for local dev | accepted | 2026-03-08 |
| ADR-016 | Explicit DB commit before Kafka publish | accepted | 2026-03-08 |
| ADR-017 | Universal ModelFactory — multi-provider prefix registry | accepted | 2026-03-08 |
| ADR-018 | Test model provider for infrastructure testing | accepted | 2026-03-08 |
| ADR-019 | LLM retry logic with exponential backoff | accepted | 2026-03-08 |
| ADR-020 | CEO LLM-based task decomposition with dependency tracking | accepted | 2026-03-10 |
| ADR-021 | Subtask forwarding via result consumer | accepted | 2026-03-10 |
| ADR-022 | QA approve/reject pipeline with rework routing | accepted | 2026-03-10 |
| ADR-023 | Meeting room — in-memory state with Kafka transport | accepted | 2026-03-10 |
| ADR-024 | Prompt Creator — never auto-activate proposed prompts | accepted | 2026-03-10 |
| ADR-025 | A2A Gateway — inbound only for Phase 2 | accepted | 2026-03-10 |
| ADR-026 | Health monitor auto-fail for silent agents | accepted | 2026-03-10 |
| ADR-027 | Centralized audit logging service | accepted | 2026-03-14 |
| ADR-028 | Tool call limit (20/task) with counting wrapper | accepted | 2026-03-14 |
| ADR-029 | Prompt versioning with DB sync and hot-reload | accepted | 2026-03-14 |
| ADR-030 | Output validation guardrail (secrets, size, empty) | accepted | 2026-03-14 |
| ADR-031 | Multi-stage Docker builds (dev/prod targets) | accepted | 2026-03-14 |
| ADR-032 | GitHub Actions CI/CD with security scanning | accepted | 2026-03-14 |
| ADR-033 | A2A SSE streaming via Redis pub/sub | accepted | 2026-03-16 |
| ADR-034 | Prompt benchmark seeding strategy | accepted | 2026-03-16 |
| ADR-035 | A2A gateway Task DB persistence before Kafka publish | accepted | 2026-03-16 |
| ADR-036 | Multi-tenant via workspace_id FK (nullable for backward compat) | accepted | 2026-03-17 |
| ADR-037 | JWT auth with SHA-256 password hashing (stdlib) | accepted | 2026-03-17 |
| ADR-038 | Temporal coexists with Taskiq (not replaces) | accepted | 2026-03-17 |
| ADR-039 | Marketplace rating via incremental average on review | accepted | 2026-03-17 |
| ADR-040 | LangFuse integration as non-blocking, graceful degradation | accepted | 2026-03-17 |
| ADR-041 | Per-tenant Agent Cards via query parameter | accepted | 2026-03-17 |
| ADR-042 | Core/integrations module separation | accepted | 2026-03-18 |
| ADR-043 | Circuit breaker pattern for LLM providers | accepted | 2026-03-18 |
| ADR-044 | API rate limiting middleware | accepted | 2026-03-18 |
| ADR-045 | Prompt injection defense layers | accepted | 2026-03-18 |
| ADR-046 | Performance indexes strategy | accepted | 2026-03-18 |
| ADR-047 | LLM-powered agent tools for planning and design | accepted | 2026-03-18 |
| ADR-048 | PostgreSQL RLS for multi-tenant isolation | accepted | 2026-03-19 |
| ADR-049 | OAuth2/OIDC alongside JWT auth | accepted | 2026-03-19 |
| ADR-050 | Stripe billing integration with graceful degradation | accepted | 2026-03-19 |
| ADR-051 | LLM-based prompt injection classifier (second layer) | accepted | 2026-03-19 |
| ADR-052 | Webhook notifications with HMAC signing | accepted | 2026-03-19 |
| ADR-053 | Per-agent cost alerts with three-layer budget enforcement | accepted | 2026-03-19 |
| ADR-054 | Provider health monitoring with ring buffer | accepted | 2026-03-19 |
| ADR-055 | Model benchmarking reusing prompt_benchmarks test cases | accepted | 2026-03-19 |
| ADR-056 | Cron-based task scheduling via croniter | accepted | 2026-03-19 |
| ADR-057 | QA multi-round rework with escalation guard | accepted | 2026-03-19 |
| ADR-058 | ANP evaluation — defer adoption until IETF RFC published | accepted | 2026-03-21 |
| ADR-059 | AP2 evaluation — adopt only if paid A2A marketplace launches | accepted | 2026-03-21 |
| ADR-060 | Federation registry — centralized first, DID-based later | accepted | 2026-03-21 |
| ADR-061 | Reaffirm Pydantic AI over LangChain/LangGraph | accepted | 2026-04-01 |
| ADR-062 | E2B Firecracker microVM for agent sandbox execution | accepted | 2026-04-01 |
| ADR-063 | Uptime Kuma + SLA engine for platform monitoring | accepted | 2026-04-01 |
| ADR-064 | Wire existing OTel stub into agent/LLM/Kafka code | accepted | 2026-04-01 |
| ADR-065 | Temporal deep integration — child workflows, signals, sagas | accepted | 2026-04-01 |
| ADR-066 | Workspace API keys for programmatic access | accepted | 2026-04-01 |
| ADR-067 | Team invitations and RBAC enforcement | accepted | 2026-04-01 |

---

## ADR Template

Copy this for every new decision.

```markdown
## ADR-{NNN} — {short title}

**Date:** YYYY-MM-DD
**Status:** proposed | accepted | superseded | deprecated
**Decided by:** {agent_name | human | claude}
**Relates to:** {CLAUDE.md §N or ADR-NNN}
**Supersedes:** {ADR-NNN or n/a}

### Context
{What situation or constraint forced this decision?
What problem were you trying to solve?
What were the stakes if the wrong decision was made?}

### Decision
{What was decided? Be specific and unambiguous.
Future readers should be able to implement this without asking questions.}

### Alternatives considered

**Option A: {name}**
- Pros: {list}
- Cons: {list}
- Why rejected: {reason}

**Option B: {name}**
- Pros: {list}
- Cons: {list}
- Why rejected: {reason}

### Consequences

**Positive:**
- {what this decision enables}

**Negative / tradeoffs:**
- {what becomes harder or more expensive}
- {what this decision constrains}

**Future implications:**
- {what this decision means for Phase 2, 3, 4}
- {migration path if this decision needs to be reversed}
```

---

## Decisions

---

## ADR-001 — Pydantic AI as agent runtime

**Date:** 2026-03
**Status:** accepted
**Decided by:** human + claude
**Relates to:** CLAUDE.md §5
**Supersedes:** n/a

### Context

We needed an agent runtime to handle: typed LLM calls with structured outputs,
multi-provider model abstraction (Claude + Gemini), async-native tool/function calling,
and Pydantic validation of all inputs/outputs. The runtime needed to integrate cleanly
with Litestar and our Kafka-native architecture without creating competing orchestration layers.

### Decision

Use Pydantic AI as the agent runtime. It handles LLM calls, tool calling with Pydantic
validation, and model abstraction. It does NOT handle orchestration, memory, or agent
communication — those are owned by Kafka, PostgreSQL, and Taskiq respectively. Pydantic AI
is isolated inside AgentBase. All other layers are independent of it.

### Alternatives considered

**LangChain + LangGraph**
- Pros: Large ecosystem, LangSmith integration, graph-based orchestration
- Cons: LangGraph would create a second orchestration system competing with Kafka.
  LangChain adds heavy abstraction layers. Async support historically inconsistent.
- Why rejected: Two orchestration systems (LangGraph + Kafka) in the same codebase
  fight each other. The graph IS our Kafka topics — already designed better.

**Raw OpenAI/Anthropic SDK calls**
- Pros: Maximum control, zero abstraction
- Cons: No multi-provider abstraction, no structured output typing, no tool calling
  framework — would build all of this manually.
- Why rejected: Significant reinvention of already-solved problems.

### Consequences

**Positive:**
- Type-safe LLM interactions with automatic Pydantic validation
- Single model abstraction layer — swapping Claude for Gemini is one config change
- Async-native, integrates with Litestar dependency injection cleanly

**Negative / tradeoffs:**
- Smaller ecosystem than LangChain
- Custom Kafka consumer loop (not provided by framework)

**Future implications:**
- If Pydantic AI proves limiting, only AgentBase changes — Kafka, PostgreSQL, Taskiq,
  the API, frontend, MCP tools, and A2A gateway are all unaffected

---

## ADR-002 — MCP via Python package → Pydantic AI adapter

**Date:** 2026-03
**Status:** accepted
**Decided by:** human + claude
**Relates to:** CLAUDE.md §8
**Supersedes:** n/a

### Context

The project has an existing MCP tools project structured as a Python package that can
be imported directly. We needed to decide how to connect it to agents.

Three options were evaluated: direct import inside agent code, HTTP sidecar service,
or wrapping as Pydantic AI native tools via an adapter layer.

### Decision

Wrap the MCP Python package as Pydantic AI native tools via `nexus/tools/adapter.py`.
The adapter is three files: `adapter.py` (wraps functions), `registry.py` (access map
per role), `guards.py` (irreversibility gate). Agents receive their tools injected at
construction time from the registry. Agents never import MCP directly.

### Alternatives considered

**Direct import in agent code**
- Pros: Zero overhead, simplest implementation
- Cons: No access control per role, no centralized irreversibility gate,
  agents can call any tool regardless of their role definition
- Why rejected: Violates the principle that tool access is enforced by the system,
  not voluntarily by the agent's own code.

**HTTP sidecar service**
- Pros: Complete separation, language-agnostic, could be swapped without touching Python
- Cons: Extra Docker service, latency on every tool call, more infrastructure to operate,
  no benefit when both sides are already Python
- Why rejected: Unnecessary complexity when the MCP package is Python and importable directly.

### Consequences

**Positive:**
- No extra infrastructure (no new Docker service)
- Per-role tool access enforced centrally in registry.py
- Irreversibility gate (`require_approval()`) enforced in adapter.py — agents cannot bypass
- Single point to add new tools, modify access, or add new guards

**Negative / tradeoffs:**
- Agents depend on the adapter interface — MCP package changes require adapter updates

**Future implications:**
- To add a new tool: add to MCP package → wrap in adapter.py → add to registry.py per role
- `tool_hire_external_agent` (A2A outbound) follows the same pattern in Phase 3

---

## ADR-003 — A2A Gateway as boundary service only

**Date:** 2026-03
**Status:** accepted
**Decided by:** human + claude
**Relates to:** CLAUDE.md §9
**Supersedes:** n/a

### Context

We decided to support Google's A2A protocol for external agent interoperability. The
question was where in the system to implement it: inside existing agents, as a middleware
layer, or as a dedicated boundary service.

### Decision

A2A is implemented exclusively in `nexus/gateway/`. The gateway translates inbound A2A
requests into Kafka messages (`a2a.inbound`) and streams results back via SSE from Redis
pub/sub. Agents receive tasks from `a2a.inbound` exactly like any other Kafka message —
they cannot and need not know whether a task originated from a human or an external agent.
No A2A-specific code exists anywhere outside `nexus/gateway/`.

### Alternatives considered

**A2A-aware agents**
- Pros: Agents could customize behavior for external vs internal callers
- Cons: Every agent needs A2A knowledge. Adding A2A requires changing every agent.
  External task format leaks into internal agent logic.
- Why rejected: Violates the separation of concerns principle. Agents should not care
  about their task's origin.

**A2A as middleware in the API layer**
- Pros: Simpler — one fewer service
- Cons: Mixes A2A protocol handling with REST API handling. A2A endpoint security model
  (per-external-agent tokens, skill authorization) is different from user auth model.
- Why rejected: Different security models should be in different services.

### Consequences

**Positive:**
- Zero changes to agent code to support A2A
- A2A security model (bearer tokens, rate limiting, skill authorization) is isolated
- External agent failure cannot corrupt internal agent state

**Negative / tradeoffs:**
- One additional service to maintain
- SSE streaming is routed through Redis pub/sub (additional hop vs direct)

**Future implications:**
- Phase 3: `tool_hire_external_agent` adds the outbound path (gateway/outbound.py)
- Phase 4: Per-tenant Agent Cards — gateway generates cards dynamically per user
- If A2A protocol changes: only `nexus/gateway/` needs updating

---

## ADR-004 — Google embedding-001 for pgvector

**Date:** 2026-03
**Status:** accepted
**Decided by:** human + claude
**Relates to:** CLAUDE.md §12
**Supersedes:** n/a

### Context

Episodic and semantic memory tables use pgvector for similarity search. We needed to
choose an embedding model. The system already uses two LLM providers (Anthropic Claude
and Google Gemini). Adding a third provider (e.g. OpenAI for text-embedding-3-small)
would require a third API key, third client library, third billing account.

### Decision

Use Google `embedding-001` via the existing Gemini API client. Dimension: 1536 vectors.
This uses the same API key already in use for Gemini models. No third provider needed.

### Alternatives considered

**OpenAI text-embedding-3-small**
- Pros: Strong benchmark performance, widely used, well-documented
- Cons: Requires a third API provider (OpenAI key + client library + billing account).
  Three API keys to manage for a solo internal tool is unnecessary overhead.
- Why rejected: Complexity cost not justified when Google embedding-001 is sufficient.

**Local embedding model (e.g. sentence-transformers)**
- Pros: No API cost, no third-party dependency, works offline
- Cons: Requires GPU or significant CPU overhead. Local model adds Docker complexity.
  Performance for code and business text is lower than API-based models.
- Why rejected: Infrastructure complexity not worth it for v1.

### Consequences

**Positive:**
- No third API provider — only two keys to manage (ANTHROPIC_API_KEY, GOOGLE_API_KEY)
- Consistent vendor relationship

**Negative / tradeoffs:**
- If we change embedding models later, all existing vectors must be re-generated
  (the entire episodic_memory and semantic_memory tables must be re-embedded)
- Vendor lock-in on Google for the embedding dimension (1536)

**Future implications:**
- Embedding generation is async via Taskiq. Model can be swapped with a one-time
  re-embedding job — expensive but not architecturally breaking.

---

## ADR-005 — Shadcn/ui for frontend component library

**Date:** 2026-03
**Status:** accepted
**Decided by:** human + claude
**Relates to:** CLAUDE.md §4
**Supersedes:** n/a

### Decision

Use Shadcn/ui as the primary component library. It is Tailwind-based, composable,
and copies components into the project (no runtime dependency). This means full control
over component code and no risk of breaking upstream changes.

**Rejected alternatives:** Radix UI (headless only, requires more styling work),
Material UI (not Tailwind-based, heavier), custom Tailwind (more work than needed for v1).

---

## ADR-006 — Taskiq over Celery and ARQ

**Date:** 2026-03
**Status:** accepted
**Decided by:** human + claude
**Relates to:** CLAUDE.md §13
**Supersedes:** n/a

### Decision

Use Taskiq for the async task queue. It has an official `taskiq-kafka` broker plugin,
is designed async-native from the start (not bolted-on like Celery), and integrates
cleanly with Litestar dependency injection. Task signatures are designed to be
Temporal-compatible — when migrating in Phase 4, only the decorator changes.

**Rejected alternatives:** Celery (sync-era design, async bolted on, fights event loop),
ARQ (no official Kafka backend, risky for long-running tasks).

---

## ADR-007 — Kafka KRaft mode — no ZooKeeper

**Date:** 2026-03
**Status:** accepted
**Decided by:** human + claude
**Relates to:** CLAUDE.md §22
**Supersedes:** n/a

### Decision

Run Kafka in KRaft mode (`KAFKA_PROCESS_ROLES: broker,controller`). This eliminates the
ZooKeeper dependency, reducing Docker Compose from 6 services to 5. KRaft is stable as of
Kafka 3.3 and is the direction Kafka has officially moved.

**Risk:** KRaft has subtleties in local dev. If Kafka is unstable after 1 day of setup,
fall back to Redis Streams (see ADR-008).

---

## ADR-008 — Kafka fallback: Redis Streams if Kafka unstable in Phase 1

**Date:** 2026-03
**Status:** accepted
**Decided by:** human + claude
**Relates to:** CLAUDE.md §23, Prevention Rule 7
**Supersedes:** n/a

### Decision

If Kafka is unstable after 1 day of local setup during Phase 1, switch to Redis Streams
as the message broker for Phase 1 development. Migrate back to Kafka in Phase 3 when the
message patterns are proven and scale is needed.

The `Topics` class constants and `KafkaMessage` Pydantic schema remain identical regardless
of broker. Only the producer/consumer client changes. This is intentional design.

**Trigger condition:** Kafka cannot reliably produce + consume a test message after
1 full day of debugging KRaft configuration.

---

## ADR-009 — PostgreSQL as sole source of truth — Redis is volatile

**Date:** 2026-03
**Status:** accepted
**Decided by:** human + claude
**Relates to:** CLAUDE.md §3, §11
**Supersedes:** n/a

### Decision

PostgreSQL is the only source of truth. Redis is a speed layer (working memory, caching,
pub/sub, locks) and is treated as volatile — if Redis is wiped, the system must be able
to recover fully from PostgreSQL without data loss. No durable state lives only in Redis.

**This means:** Redis keys have TTLs. Working memory is flushed to PostgreSQL on task
completion before deletion. Rate limiting state and session state are acceptable to lose
on Redis wipe (they self-heal on next request).

---

## ADR-010 — Reject LangGraph — conflicts with Kafka orchestration

**Date:** 2026-03
**Status:** accepted
**Decided by:** human + claude
**Relates to:** CLAUDE.md §5
**Supersedes:** n/a

### Decision

LangGraph is not used in this project. LangGraph's graph-based state machine would
create a second orchestration system that competes with our Kafka-native design.
The "graph" in our system is Kafka topics — agent.commands, agent.responses,
meeting.room, a2a.inbound are the edges. Adding LangGraph on top creates two systems
that fight each other for ownership of the same orchestration problem.

This decision is final. Do not propose LangGraph integration without creating a
superseding ADR with clear justification of how it avoids the dual-orchestration problem.

---

## ADR-011 — Semantic memory contradiction resolution strategy

**Date:** 2026-03-07
**Status:** **superseded** — implemented as newest-wins upsert on `UNIQUE(agent_id, namespace, key)`. See BACKLOG-003 resolution.
**Decided by:** claude_code
**Relates to:** CLAUDE.md §12, §25
**Supersedes:** n/a

### Context

The `semantic_memory` table has a UNIQUE constraint on `(agent_id, namespace, key)`, which
means writes to the same key are upserts. When two tasks produce conflicting values for the
same semantic fact (e.g., "preferred_testing_framework" set to "pytest" by one task and
"unittest" by another), we need a deterministic resolution strategy.

This must be decided before agents start writing semantic memory in Phase 1, otherwise
conflicting writes will silently overwrite each other with no traceability.

### Options under consideration

**Option A: Newest wins (simple upsert)**
- Pros: Simplest implementation — just overwrite on conflict. No extra logic needed.
- Cons: A later task with bad information silently overwrites correct knowledge.
  No way to detect or recover from an incorrect overwrite.

**Option B: Highest confidence wins**
- Pros: Each write carries a `confidence` float (0-1). Higher confidence overwrites lower.
  Allows the system to express certainty levels.
- Cons: Confidence is set by the agent — an agent that's wrong but confident wins.
  Requires a confidence calibration strategy.

**Option C: Human resolves conflicts**
- Pros: Safest — publish to `human.input_needed` when a conflict is detected.
  Human picks the correct value. Zero risk of silent corruption.
- Cons: Slowest. Creates friction if conflicts are frequent. May not scale in Phase 4.

**Option D: Newest wins + audit trail**
- Pros: Same simplicity as Option A, but the old value is logged to `audit_log` before
  overwrite. Humans can review overwrites asynchronously. Balances speed and safety.
- Cons: Slightly more write overhead. Requires monitoring audit log for suspicious overwrites.

### Recommended direction

Option D (newest wins + audit trail) appears to balance simplicity with traceability.
Awaiting human review before accepting.

---

## ADR-012 — Log aggregation approach for v1

**Date:** 2026-03-07
**Status:** **superseded** — implemented as file-based structured JSON via structlog to stdout. Docker captures logs. See BACKLOG-006 for Phase 3 aggregation decision.
**Decided by:** claude_code
**Relates to:** CLAUDE.md §25, §23 Prevention Rule 5
**Supersedes:** n/a

### Context

CLAUDE.md specifies structured JSON logging with `task_id` on every line. The open question
is where these logs go: file-based JSON, Loki, or OpenSearch. This decision is marked
"Medium priority — decide before Phase 3" in CLAUDE.md §25 but the logging infrastructure
should be in place from Phase 0.

### Options under consideration

**Option A: File-based JSON logs (stdout + Docker log driver)**
- Pros: Zero infrastructure. Docker captures stdout automatically. Can use `docker compose logs`
  and `jq` for filtering. No new services in docker-compose.yml.
- Cons: No search UI. Hard to query across multiple services. Logs rotate and disappear.
  Not suitable for production.

**Option B: Loki + Grafana**
- Pros: Purpose-built for log aggregation. Grafana provides search UI. Lightweight compared
  to OpenSearch. Docker Compose compatible.
- Cons: Two additional services (Loki + Grafana). Configuration overhead. Overkill for solo v1.

**Option C: OpenSearch**
- Pros: Full-text search, rich dashboards, handles high volume.
- Cons: Heavy resource usage (Java-based). Three additional services (OpenSearch + Dashboards +
  log shipper). Significant infrastructure overhead for v1.

### Recommended direction

Option A for Phases 0-2 (file-based JSON to stdout, query with `jq`). Revisit for Loki in
Phase 3 when observability hardening begins. See BACKLOG-006.

---

## ADR-013 — Meeting room termination signal

**Date:** 2026-03-07
**Status:** **superseded** by ADR-023. Implemented as CEO-initiated `terminate()` with timeout (300s) and max-round (10) guards.
**Decided by:** claude_code
**Relates to:** CLAUDE.md §10, §25
**Supersedes:** n/a

### Context

The meeting room pattern uses temporary Kafka topics (`meeting.room.{task_id}`) for multi-agent
collaboration. When agents join a meeting to discuss and resolve a complex task, something must
signal that the meeting is over and the result should be finalized. Without a clear termination
signal, meetings can run indefinitely, consuming tokens and blocking task completion.

### Options under consideration

**Option A: CEO-initiated timeout**
- Pros: Simple — CEO sets a max duration or max rounds when creating the meeting.
  When the limit is reached, CEO summarizes and closes.
- Cons: Fixed timeout may cut off productive discussions early or wait too long for
  simple decisions.

**Option B: Explicit consensus vote**
- Pros: Each agent signals "I'm done" when they have nothing more to contribute.
  Meeting closes when all participants have signaled.
- Cons: Requires a voting protocol. An agent that never signals blocks everyone.
  Needs a fallback timeout anyway.

**Option C: CEO decides + timeout fallback**
- Pros: CEO monitors the discussion and closes the meeting when it judges the question
  is resolved. If CEO doesn't close within a configurable timeout, the meeting auto-closes
  with a summary of what was discussed.
- Cons: Requires CEO to actively monitor meeting topics (additional consumer subscription).

### Recommended direction

Option C (CEO decides + timeout fallback) provides the most natural flow. CEO is already
the orchestrator — it should own meeting lifecycle. Timeout provides a safety net.
See BACKLOG-004.

---

## ADR-014 — Pin pydantic-ai to 0.5.x with anthropic <0.83.0

**Date:** 2026-03-08
**Status:** accepted
**Decided by:** claude_code
**Relates to:** CLAUDE.md §4, §5
**Supersedes:** n/a

### Context

During E2E verification, pydantic-ai 0.6+ failed to import due to a breaking change in
the anthropic SDK. pydantic-ai 0.6.x imports `UserLocation` from
`anthropic.types.beta.beta_web_search_tool_20250305_param`, but anthropic 0.84.0 renamed
this to `BetaUserLocationParam`. This causes an `ImportError` at startup.

Additionally, pydantic-ai 0.5.x changed the `AnthropicModel` constructor — it no longer
accepts an `api_key` parameter. API keys are read from environment variables automatically.

### Decision

Pin `pydantic-ai[anthropic,google]>=0.5.0,<0.6.0` and `anthropic>=0.80.0,<0.83.0` in
`pyproject.toml`. Remove `api_key` parameter from `ModelFactory.get_model()` calls.

### Alternatives considered

**Upgrade to pydantic-ai 0.6+ with matching anthropic SDK**
- Pros: Latest features, maintained version
- Cons: No compatible anthropic SDK version exists — 0.6+ requires the renamed class
  that doesn't exist in any stable anthropic release.
- Why rejected: No working combination available at time of decision.

**Use raw Anthropic SDK without pydantic-ai**
- Pros: Direct control, no version conflict
- Cons: Loses structured output typing, tool calling framework, multi-provider abstraction
- Why rejected: Would require rewriting AgentBase and all agent implementations.

### Consequences

**Positive:**
- Stable, tested combination that works end-to-end
- API keys managed via env vars (cleaner than passing explicitly)

**Negative / tradeoffs:**
- Locked to older pydantic-ai version until upstream resolves the import issue
- Must monitor pydantic-ai releases for a fix

**Future implications:**
- When pydantic-ai releases a version compatible with latest anthropic SDK, update both
  pins together and test before merging

---

## ADR-015 — Docker port remapping for local dev

**Date:** 2026-03-08
**Status:** accepted
**Decided by:** claude_code
**Relates to:** CLAUDE.md §22
**Supersedes:** n/a

### Context

The host machine runs local PostgreSQL (port 5432) and Redis (port 6379). Docker Compose
services using the same ports fail to bind, preventing `make up` from working.

### Decision

Remap Docker host-exposed ports to avoid conflicts:
- PostgreSQL: `5433:5432` (host:container)
- Redis: `6380:6379` (host:container)

Internal Docker networking is unaffected — containers still communicate on standard ports
via Docker DNS (e.g., `postgres:5432`, `redis:6379`).

### Consequences

**Positive:**
- `make up` works on machines with local PostgreSQL/Redis running
- No changes needed to application code — only docker-compose.yml host port mapping

**Negative / tradeoffs:**
- Direct host access to Docker postgres/redis uses non-standard ports (5433, 6380)
- `make shell-db` and `make shell-redis` still work (they exec into the container)

---

## ADR-016 — Explicit DB commit before Kafka publish

**Date:** 2026-03-08
**Status:** accepted
**Decided by:** claude_code
**Relates to:** CLAUDE.md §16, §19
**Supersedes:** n/a

### Context

When creating a task via `POST /api/tasks`, the handler flushes the task to the database
then publishes to Kafka. The Kafka consumer (CEO agent) processes the message and queries
the database for the task. With Litestar's auto-commit, the transaction was not committed
before the Kafka message was consumed, causing the CEO to find no task in the database.

### Decision

Add explicit `await db_session.commit()` after `db_session.flush()` and before any Kafka
`publish()` call in API handlers. Do not rely on Litestar's auto-commit for operations
where downstream consumers need the data immediately.

### Consequences

**Positive:**
- Task is guaranteed to be in the database before any Kafka consumer processes it
- Eliminates a race condition between API commit and Kafka consumer query

**Negative / tradeoffs:**
- Manual commit management in some handlers (slightly more code)
- If the Kafka publish fails after commit, the task exists in DB but was never queued
  (acceptable — can be retried or cleaned up)

---

## ADR-017 — Universal ModelFactory — multi-provider prefix registry

**Date:** 2026-03-08
**Status:** accepted
**Decided by:** claude_code
**Relates to:** CLAUDE.md §6
**Supersedes:** n/a

### Context

The original `ModelFactory` only supported Anthropic Claude and Google Gemini. For Phase 1
testing, free-tier providers (Groq) and local models (Ollama) were needed. The factory needed
to support any LLM provider without changing agent code.

### Decision

Rewrite `llm/factory.py` with a prefix-based provider resolution registry. Model names are
strings like `groq:llama-3.3-70b-versatile` or `ollama:llama3`. The factory checks prefixes
in order against a resolver list. First match wins. All provider imports are lazy (inside
function bodies) to avoid ImportErrors for uninstalled providers.

Supported providers: Anthropic (`claude-*`), Google Gemini (`gemini-*`), OpenAI (`openai:*`,
`gpt-*`, `o1-*`, `o3-*`), Groq (`groq:*`), Mistral (`mistral:*`), Ollama (`ollama:*`),
OpenAI-compatible (`openai-compat:*`), Test (`test:*`).

### Alternatives considered

**Per-provider factory methods**
- Pros: Explicit, easy to understand
- Cons: Adding a provider requires changing ModelFactory class
- Why rejected: Prefix registry is more extensible — add one tuple to the list.

**pydantic-ai auto-detection**
- Pros: Zero configuration
- Cons: pydantic-ai 0.5.x doesn't auto-detect from model name strings reliably
- Why rejected: Explicit is better than implicit. Provider prefix makes the intent clear.

### Consequences

**Positive:**
- Any agent can use any provider by changing one env var (`MODEL_ENGINEER=groq:llama-3.3-70b`)
- Zero code changes needed to switch providers
- Lazy imports mean uninstalled providers don't cause import errors

**Negative / tradeoffs:**
- Model name strings must follow the prefix convention
- Unknown prefixes raise ValueError (intentional — fail loud)

---

## ADR-018 — Test model provider for infrastructure testing

**Date:** 2026-03-08
**Status:** accepted
**Decided by:** claude_code
**Relates to:** CLAUDE.md §14, ADR-017
**Supersedes:** n/a

### Context

Running the 50-task stress test against Groq's free tier exhausted the daily token limit
(100K TPD) before completing. The stress test's purpose (per CLAUDE.md §14) is to verify
agent decision logic and infrastructure, not LLM output quality. We needed a way to run
infrastructure tests without API costs or rate limits.

### Decision

Add a `test:` prefix to the ModelFactory that creates pydantic-ai's built-in `TestModel`.
This model returns deterministic responses without making any API calls. Set
`MODEL_ENGINEER=test:mock` in `.env` to run infrastructure stress tests at zero cost.

### Consequences

**Positive:**
- Unlimited infrastructure testing with zero API cost
- Deterministic, reproducible test results
- 50-task stress test completes in ~106s instead of being blocked by rate limits

**Negative / tradeoffs:**
- Test model output is not meaningful — only tests the pipeline, not LLM quality
- LLM quality testing still requires real API keys (Layer 5 eval testing per §14)

---

## ADR-019 — LLM retry logic with exponential backoff

**Date:** 2026-03-08
**Status:** accepted
**Decided by:** claude_code
**Relates to:** CLAUDE.md §20, §23 Risk 2
**Supersedes:** n/a

### Context

During the first live stress test with Groq, 26% of tasks failed due to two transient error
types: (1) HTTP 429 rate limit errors from provider-side throttling, and (2) `tool_use_failed`
errors where the LLM model (llama-3.3-70b) malformatted tool call JSON for simple questions.

### Decision

Add `_run_with_retry()` to EngineerAgent with two strategies:
1. **Rate limit (429):** Retry up to 5 times with exponential backoff (5s, 10s, 20s, 30s, 45s)
2. **Tool call format error:** Create a temporary agent without tools and retry once

Other errors are not retried — they propagate immediately as task failures.

### Consequences

**Positive:**
- Transient rate limits are handled gracefully without task failure
- Simple questions that don't need tools can still succeed when the model malformats tool calls
- Retry logic is in the agent layer, not the factory — provider-agnostic

**Negative / tradeoffs:**
- Rate limit retries add latency (up to ~110s total backoff)
- Tool-less fallback loses tool calling capability for that specific request
- Retry logic should eventually be moved to AgentBase so all agents benefit (Phase 2)

---

## ADR-020 — CEO LLM-based task decomposition with dependency tracking

**Date:** 2026-03-10
**Status:** accepted
**Decided by:** claude_code
**Relates to:** CLAUDE.md §7, §10
**Supersedes:** n/a

### Context

Phase 1 CEO was a thin router that forwarded every task directly to the Engineer agent.
Phase 2 requires multi-agent collaboration: a task like "Research X and write an email"
must be split into subtasks for different specialist agents, with dependency ordering
(writer waits for analyst to finish before starting).

### Decision

CEO uses an LLM call to decompose tasks into a JSON array of subtasks:
`[{"role": "analyst", "instruction": "...", "depends_on": []}, {"role": "writer", "instruction": "...", "depends_on": [0]}]`.
Subtasks are created as Task records in PostgreSQL with `parent_task_id` linking them to the
parent. Tracking state (which subtasks are pending/complete) is stored in Redis working memory.
CEO dispatches subtasks whose dependencies are all satisfied, passing completed dependency
outputs as context. When all subtasks complete, CEO aggregates outputs and routes to QA.

If the LLM returns invalid JSON, CEO falls back to a single engineer subtask.
Invalid role names are normalized to "engineer".

### Alternatives considered

**Static routing table (role → agent mapping)**
- Pros: Simple, deterministic, no LLM cost for decomposition
- Cons: Cannot handle novel task compositions. Every new task pattern requires a code change.
- Why rejected: The whole point of an AI orchestrator is dynamic task understanding.

**LangGraph state machine for decomposition**
- Pros: Built-in dependency graph support
- Cons: Conflicts with Kafka orchestration (ADR-010). Would create dual orchestration.
- Why rejected: Already rejected in ADR-010. Kafka IS the orchestration layer.

### Consequences

**Positive:**
- CEO can handle arbitrary task compositions without code changes
- Dependency tracking ensures correct execution order
- Redis working memory enables stateless CEO restarts mid-task

**Negative / tradeoffs:**
- One extra LLM call per task for decomposition (adds cost + latency)
- JSON parsing from LLM is not 100% reliable — fallback logic required
- Subtask tracking in Redis adds complexity

**Future implications:**
- Meeting room pattern (Phase 2 later) can build on this decomposition infrastructure
- Prompt Creator Agent can optimize the CEO decomposition prompt based on failure patterns

---

## ADR-021 — Subtask forwarding via result consumer

**Date:** 2026-03-10
**Status:** accepted
**Decided by:** claude_code
**Relates to:** CLAUDE.md §10, ADR-020
**Supersedes:** n/a

### Context

When a specialist agent completes a subtask, its response goes to `agent.responses` and is
picked up by the result consumer. For top-level tasks, the result consumer updates the DB
and publishes to `task.results`. But subtasks must route back to CEO for aggregation —
not directly to results.

### Decision

The result consumer checks if a completed task has a `parent_task_id` in the database.
If yes, it's a subtask: update the subtask status in DB, then publish an aggregation
command to `task.queue` with `_response_aggregation: True` flag in the payload. CEO
detects this flag and enters its aggregation path (update tracking, dispatch unblocked
dependents, or aggregate-and-route-to-QA if all done).

CEO orchestration actions (`decomposed`, `subtask_tracked`, `aggregated_and_sent_to_qa`)
are skipped by the result consumer — they are internal state transitions, not final results.

### Alternatives considered

**Direct CEO-to-CEO Kafka topic**
- Pros: Dedicated channel, no result consumer modification needed
- Cons: New topic just for internal routing. Result consumer still needs to know about subtasks.
- Why rejected: Adds a topic without solving the core problem. Result consumer must still
  distinguish subtasks from top-level tasks.

**Agent responses go directly to CEO**
- Pros: Simpler routing — CEO consumes all agent.responses
- Cons: CEO would process ALL agent responses, even those not related to its tasks.
  High noise. No separation of concerns.
- Why rejected: CEO should only see responses to its own subtasks, not all agent traffic.

### Consequences

**Positive:**
- Clean separation: result consumer handles routing, CEO handles orchestration
- Existing result consumer infrastructure is reused
- `_response_aggregation` flag makes the routing explicit and debuggable

**Negative / tradeoffs:**
- Result consumer now has DB queries (to check parent_task_id) — slightly heavier
- Potential race condition if subtask completes before CEO finishes writing tracking state

---

## ADR-022 — QA approve/reject pipeline with rework routing

**Date:** 2026-03-10
**Status:** accepted
**Decided by:** claude_code
**Relates to:** CLAUDE.md §7, §10
**Supersedes:** n/a

### Context

Per CLAUDE.md §7, QA reviews all outputs before delivery. The QA agent needs a structured
way to approve good output (send to user) or reject bad output (send back for rework).

### Decision

QA receives aggregated output on `task.review_queue`. It uses an LLM call to evaluate
the output and returns a JSON response: `{"approved": bool, "score": float, "feedback": str, "issues": []}`.

- **Approved:** QA publishes a TaskResult to `task.results` with the aggregated output.
- **Rejected:** QA publishes a rework command to `agent.commands` targeting the original
  specialist role, with the QA feedback included in the instruction.

If the LLM returns non-JSON, QA defaults to approved (fail-open for v1 — revisit in Phase 3).

### Alternatives considered

**QA as a scoring-only agent (no routing)**
- Pros: Simpler — QA just scores, someone else routes
- Cons: Requires another component to read QA scores and decide routing. More moving parts.
- Why rejected: QA is the natural decision point — it already has the evaluation context.

**Automatic multi-round rework loop**
- Pros: Rejected work automatically cycles back and forth until QA approves
- Cons: Unbounded loop risk. Could cycle indefinitely with cost explosion.
- Why rejected: v1 does one rework attempt. If still rejected, task fails. Multi-round
  rework with configurable limits is a Phase 3 feature.

### Consequences

**Positive:**
- Clean approve/reject flow with structured feedback
- Rework routing reuses existing `agent.commands` infrastructure
- QA feedback is included in rework instructions, improving specialist output

**Negative / tradeoffs:**
- Fail-open default (non-JSON → approved) could pass bad output in edge cases
- Single rework attempt may not be enough for complex tasks

---

## ADR-023 — Meeting room — in-memory state with Kafka transport

**Date:** 2026-03-10
**Status:** accepted
**Decided by:** claude_code
**Relates to:** CLAUDE.md §10 (Kafka Design), §7 (Agent Roster)
**Supersedes:** ADR-013 (meeting room termination — resolved)

### Context

The meeting room pattern enables multi-agent debates. CEO poses a question, invited agents
respond, and CEO terminates when satisfied. We needed to decide: (a) where meeting state lives,
and (b) how messages flow.

### Decision

Meeting state lives **in-memory** in the Python process (module-level `_meeting_registry` dict).
Meeting messages are published to the `meeting.room` Kafka topic, partitioned by meeting_id
for ordering guarantees. Guard rails: 300s timeout, 10 max rounds.

This is a Phase 2 simplification. Phase 3 will migrate meeting state to Redis for cluster safety
(see ERROR-015 in ERRORLOG.md).

### Alternatives considered

**Redis-backed meeting state from the start**
- Pros: Cluster-safe, survives process restarts
- Cons: More complexity for v1, serialization of MeetingRoom objects
- Why deferred: Only one backend worker in Phase 2. Redis migration is a clean Phase 3 task.

### Consequences

**Positive:** Simple, fast, no extra Redis round-trips per message
**Negative:** Single-worker only. Meeting state lost on process restart. Documented in ERROR-015.

---

## ADR-024 — Prompt Creator — never auto-activate proposed prompts

**Date:** 2026-03-10
**Status:** accepted
**Decided by:** claude_code
**Relates to:** CLAUDE.md §7 (Prompt Creator Agent)
**Supersedes:** n/a

### Context

The Prompt Creator Agent analyzes failure patterns and drafts improved system prompts.
The question: should it auto-deploy prompts that score well on benchmarks, or always
require human approval?

### Decision

**Always require human approval.** Proposed prompts are stored with `is_active=false`.
Activation requires an explicit `POST /api/prompts/{id}/activate` call from the dashboard.
The PromptDiffView shows a side-by-side diff with benchmark scores for informed decisions.

### Alternatives considered

**Auto-activate prompts above a score threshold (e.g., 0.8)**
- Pros: Faster improvement loop, less human intervention
- Cons: LLM self-evaluation is unreliable. A bad prompt could silently degrade all tasks
  for a role. Recovery requires reverting to a previous version.
- Why rejected: The cost of a bad auto-deployed prompt is too high. Human review takes
  minutes but prevents potential hours of wasted compute.

### Consequences

**Positive:** Humans maintain control over agent behavior. No risk of cascading prompt failures.
**Negative:** Slower improvement cycle. Prompts wait for human review.

---

## ADR-025 — A2A Gateway — inbound only for Phase 2

**Date:** 2026-03-10
**Status:** accepted
**Decided by:** claude_code
**Relates to:** CLAUDE.md §9 (A2A Gateway)
**Supersedes:** n/a

### Context

The A2A protocol supports both inbound (external agents hiring NEXUS) and outbound
(NEXUS hiring external agents). Which should be implemented first?

### Decision

**Inbound only in Phase 2.** Outbound placeholder exists (`gateway/outbound.py`) but raises
`NotImplementedError`. Inbound flow: `/.well-known/agent.json` → bearer token auth →
`POST /a2a/tasks` → validates skill access → publishes to `a2a.inbound` Kafka topic →
CEO picks up → normal multi-agent flow.

### Alternatives considered

**Full A2A (inbound + outbound) in Phase 2**
- Pros: Complete A2A capability
- Cons: Outbound requires discovering external agents, managing external auth, handling
  external failures, result aggregation from untrusted sources. Significantly more complexity.
- Why rejected: No current external A2A agents to call. Inbound provides immediate value
  (others can call NEXUS). Outbound is Phase 3 work.

### Consequences

**Positive:** Focused scope. NEXUS is callable by external agents today.
**Negative:** NEXUS cannot delegate to external agents yet.

---

## ADR-026 — Health monitor auto-fail for silent agents

**Date:** 2026-03-10
**Status:** accepted
**Decided by:** claude_code
**Relates to:** CLAUDE.md §23 Prevention Rule (Risk 5), RISK_REVIEW.md
**Supersedes:** n/a

### Context

Risk 5 ("Agents fail silently") was partially mitigated — heartbeat loop existed but no
auto-fail mechanism. A hung agent's task would stay "running" indefinitely.

### Decision

Implement a `HealthMonitor` as a background asyncio task. It:
1. Consumes `agent.heartbeat` Kafka messages, tracks last-seen in Redis
2. Every 60 seconds, scans all tracked agents for staleness (>5 minutes)
3. For stale agents: auto-fails their active tasks (DB update to `failed`),
   publishes audit log entry, logs warning

### Alternatives considered

**Cron job instead of background task**
- Pros: Decoupled from the main process
- Cons: Requires additional deployment configuration. Adds latency (cron granularity).
- Why rejected: Background task is simpler and responds within 60 seconds.

### Consequences

**Positive:** Tasks no longer hang indefinitely. Silent agents are detected and their tasks fail cleanly.
**Negative:** 5-minute window before detection. Longer-running tasks need heartbeat extensions (Phase 3).

---

## ADR-027 — Centralized audit logging service

**Status:** accepted
**Date:** 2026-03-14
**Context:** Agent actions, prompt changes, budget events, and approval flows need a unified
audit trail for risk management and debugging.

### Decision

Create `audit/service.py` with `AuditEventType` enum (13 event types) and `log_event()` function.
All audit events write to the existing `audit_log` table via the active DB session. Events are
wired into: AgentBase guard chain, `llm/usage.py`, `tools/guards.py`, and `api/prompts.py`.

API endpoints: `GET /audit` (filterable list) and `GET /audit/{task_id}/timeline` (chronological).

### Consequences

**Positive:** Complete action trail for every agent. Prompt history, cost events, and approval
decisions are all queryable. Enables compliance auditing and debugging.
**Negative:** Additional DB writes per task (2-3 audit events). Acceptable for v1 volume.

---

## ADR-028 — Tool call limit (20/task) with counting wrapper

**Status:** accepted
**Date:** 2026-03-14
**Context:** CLAUDE.md §20 Rule 4 requires a maximum of 20 tool calls per task to prevent
infinite reasoning loops. Needs enforcement at runtime.

### Decision

Wrap all Pydantic AI tools with a counting decorator in `agents/factory.py`. Each wrapper
increments a shared counter dict. When count > limit, `ToolCallLimitExceeded` is raised.
Counter resets to 0 at the start of each task in `_execute_with_guards()`. The exception
handler publishes to `human.input_needed` (same as budget exceeded).

### Consequences

**Positive:** Prevents infinite tool loops. Agents fail safely with human escalation.
**Negative:** Adds one dict lookup per tool call. Negligible overhead.

---

## ADR-029 — Prompt versioning with DB sync and hot-reload

**Status:** accepted
**Date:** 2026-03-14
**Context:** Prompts were versioned in the `prompts` table but activating a prompt did not
update the agent's runtime behavior. The `agents.system_prompt` column was disconnected.

### Decision

Three changes: (1) `activate_prompt()` and `rollback_prompt()` now sync the prompt content
to `agents.system_prompt` via `_sync_agent_prompt()`. (2) AgentBase checks the DB for
system_prompt changes before each task (`_check_prompt_reload()`). If changed, it reconstructs
the PydanticAgent. (3) All prompt changes emit audit events for history tracking.

### Consequences

**Positive:** Prompt changes take effect on next task without restart. Full rollback support.
**Negative:** One extra DB query per task for reload check. Acceptable for v1.

---

## ADR-030 — Output validation guardrail (secrets, size, empty)

**Status:** accepted
**Date:** 2026-03-14
**Context:** Agent outputs could contain leaked secrets, be empty on success, or exceed
reasonable size limits without detection.

### Decision

Add `_validate_output()` to AgentBase, called after `handle_task()` and before memory write.
Three checks: (1) Empty output on success → downgrade to "partial". (2) Secret patterns
(9 patterns including API keys, tokens, private keys) → redact with `[REDACTED]`.
(3) Output > 100KB → add `_truncated` flag.

### Consequences

**Positive:** Prevents accidental secret leakage. Catches empty/oversized outputs.
**Negative:** String scanning adds minimal latency. False positives on legitimate
content containing pattern prefixes (e.g., "Bearer" in documentation) — acceptable
for security-first approach.

---

## ADR-031 — Multi-stage Docker builds (dev/prod targets)

**Status:** accepted
**Date:** 2026-03-14
**Context:** Frontend Docker image was 451MB because it included full Node.js runtime and
node_modules for production. No separation between dev and prod builds.

### Decision

Both backend and frontend Dockerfiles use multi-stage builds with named targets:
- `dev` — full development dependencies, hot-reload, used by docker-compose.yml
- `prod` — minimal runtime, no dev deps (backend: non-root user, 2 workers;
  frontend: nginx serving static files from Vite build output)

Frontend prod image: 62MB (vs 451MB dev). `docker-compose.prod.yml` overrides targets.

### Consequences

**Positive:** 86% smaller production images. Secure (non-root). Fast deploys.
**Negative:** Two compose files to manage. Mitigated by `make build-prod` / `make up-prod`.

---

## ADR-032 — GitHub Actions CI/CD with security scanning

**Status:** accepted
**Date:** 2026-03-14
**Context:** No automated CI/CD pipeline existed. Code quality, security, and Docker image
publishing were manual processes.

### Decision

Three GitHub Actions workflows:
1. **ci.yml** — Ruff lint, mypy type check, unit tests, behavior tests, frontend TS check + build
2. **docker-publish.yml** — Build prod images, push to DockerHub with SHA/branch/semver tags
3. **security.yml** — pip-audit, npm audit, TruffleHog secret detection, Trivy container
   scanning, CodeQL static analysis (Python + TypeScript). Runs on push/PR + weekly schedule.

### Consequences

**Positive:** Automated quality gates. Security scanning catches vulnerabilities early.
Docker images automatically published on merge to main.
**Negative:** CI run time (~5-10 min). DockerHub requires `DOCKERHUB_USERNAME` and
`DOCKERHUB_TOKEN` secrets configured in GitHub repo settings.

---

## ADR-033 — A2A SSE streaming via Redis pub/sub

**Status:** accepted
**Date:** 2026-03-16
**Context:** External agents need real-time task progress updates. The A2A protocol
supports Server-Sent Events (SSE) for streaming. We needed to choose between WebSocket,
SSE, or polling for the A2A event stream.

### Decision

SSE endpoint at `GET /a2a/tasks/{task_id}/events` using Litestar's `Stream` response
with `media_type="text/event-stream"`. Subscribes to Redis pub/sub channel
`agent_activity:{task_id}` — the same channel the `result_consumer.py` already publishes
to (line 130). Events streamed in standard SSE format (`data: {json}\n\n`). Stream
terminates on `task_result` or `task_failed` events, or after 10-minute timeout.

### Alternatives considered

1. **WebSocket** — More complex, requires connection upgrade, stateful. Overkill for
   unidirectional event streaming. Already used for dashboard (different use case).
2. **Long polling** — Simple but higher latency. Misses intermediate events. Poor UX.
3. **Dedicated event bus** — Separate from Redis. Unnecessary — Redis pub/sub already
   carries the exact events we need.

### Consequences

**Positive:** Reuses existing Redis pub/sub infrastructure. Standard SSE format compatible
with all A2A clients. Lightweight — no connection state to manage.
**Negative:** Redis pub/sub is fire-and-forget — if client connects after events are
published, they're missed. Proxies may timeout idle connections (see BACKLOG-028).

---

## ADR-034 — Prompt benchmark seeding strategy

**Status:** accepted
**Date:** 2026-03-16
**Context:** The Prompt Creator Agent needs benchmark test cases to evaluate prompt quality.
CLAUDE.md §24 requires "Write 10 benchmark test cases per agent role."

### Decision

60 fixed test cases seeded via `db/seed.py` (10 per role: CEO, Engineer, Analyst, Writer,
QA, Prompt Creator). Each benchmark has:
- `input`: A realistic test instruction the agent would receive
- `expected_criteria`: JSON with `must_contain`, `must_not_contain`, `output_format`,
  and `quality_markers` fields

Seeded idempotently using `(agent_role, input)` as the uniqueness check. Benchmarks are
evaluation scaffolding — they define what good output looks like without hardcoding exact
expected output (which would be too brittle for LLM evaluation).

### Consequences

**Positive:** Prompt Creator can now score prompt versions against fixed test cases.
Reproducible evaluation. Human-readable criteria.
**Negative:** 60 seed records is a starting point — will need expansion as agent
capabilities grow. `expected_criteria` format is flexible but not formally validated.

---

## ADR-035 — A2A gateway Task DB persistence before Kafka publish

**Status:** accepted
**Date:** 2026-03-16
**Context:** A2A gateway `submit_task` published to Kafka without creating a Task record
in PostgreSQL. This caused FK violations when CEO created subtasks and prevented
`result_consumer` from updating task status. See ERROR-018.

### Decision

All external-facing gateways (A2A, future webhooks) must follow the same
commit-then-publish pattern as the regular task API (`api/tasks.py`):

1. Create `Task` record with appropriate `source` and `source_agent`
2. `db_session.flush()` → `db_session.commit()`
3. THEN publish to Kafka

This is now documented as Pattern J in ERRORLOG.md.

### Consequences

**Positive:** Task records always exist when downstream consumers process them. FK
constraints satisfied. Status polling works immediately after submission.
**Negative:** Slightly more latency (DB write before Kafka). If DB write fails, task
is never published — but this is the correct behavior (fail early, fail visibly).

---

## ADR-042 — Core/integrations module separation

**Status:** accepted
**Date:** 2026-03-18
**Context:** The `integrations/` directory mixed core infrastructure (kafka, redis, llm) that the system cannot function without, alongside pluggable external services (keepsave, a2a, temporal, eval) that degrade gracefully. This made the dependency hierarchy unclear and complicated reasoning about system resilience.

### Decision

Create `nexus/core/` for kafka, redis, llm. Keep `nexus/integrations/` for keepsave, a2a, temporal, eval. Core modules are always available; integration modules may be unavailable.

### Consequences

**Positive:**
- Clear architectural boundary: if it's in `core/`, the system breaks without it. If it's in `integrations/`, the system degrades but continues.

**Negative / tradeoffs:**
- ~40 files needed import updates.

---

## ADR-043 — Circuit breaker pattern for LLM providers

**Status:** accepted
**Date:** 2026-03-18
**Context:** LLM providers occasionally go down. Without circuit breakers, agents retry indefinitely, consuming token budgets and blocking tasks. The existing 5-retry with backoff helped for transient errors but not for sustained outages.

### Decision

Implement per-provider circuit breaker in `core/llm/circuit_breaker.py` with 3 states (closed/open/half_open), 5-failure threshold, 60s recovery timeout. Integrate with ModelFactory fallback chains. Expose states via `/health` endpoint.

### Consequences

**Positive:**
- Fast failure on known-down providers. Automatic recovery testing. Dashboard visibility into provider health.

**Negative / tradeoffs:**
- No external dependency (stdlib only).

---

## ADR-044 — API rate limiting middleware

**Status:** accepted
**Date:** 2026-03-18
**Context:** Only A2A endpoints had rate limiting (per-token via Redis). General API endpoints had no protection against abuse, DoS, or runaway automated clients.

### Decision

Add `api/middleware.py` with sliding window counters in Redis db:1. Three tiers: 100 req/min (authenticated), 20 req/min (unauthenticated by IP), 10 req/min (task creation). Falls back to allowing requests if Redis is unavailable.

### Consequences

**Positive:**
- Protection against abuse without blocking legitimate use. Graceful degradation on Redis failure. Same sliding window pattern as A2A rate limiter (consistency).

**Negative / tradeoffs:**
- Additional Redis round-trip per request. Mitigated by pipelining.

---

## ADR-045 — Prompt injection defense layers

**Status:** accepted
**Date:** 2026-03-18
**Context:** User task instructions are passed to LLM prompts. Without validation, adversarial inputs could override system prompts, extract agent instructions, or manipulate agent behavior.

### Decision

Two-layer defense: (1) `validate_instruction()` in middleware.py rejects known injection patterns (5 regex patterns) and enforces 10K char limit. (2) `sandbox_instruction()` wraps user input with `<user_instruction>` delimiters so the system prompt can instruct the LLM to treat delimited content as untrusted.

### Consequences

**Positive:**
- Blocks common injection techniques. No false positives on legitimate instructions in testing.

**Negative / tradeoffs:**
- Novel attacks may bypass regex — LLM-based detection planned for Phase 5.

---

## ADR-046 — Performance indexes strategy

**Status:** accepted
**Date:** 2026-03-18
**Context:** Analytics and task replay endpoints showed increasing latency as data grew. Profiling identified missing composite indexes on frequently queried columns and N+1 query patterns in two endpoints.

### Decision

(1) Migration 005 adds 7 indexes: 6 composite (agent+created on tasks, llm_usage, audit_log, episodic_memory; status+requested on approvals; workspace+created on billing) + 1 partial index on active tasks. (2) Fix N+1 in analytics.py (batch GROUP BY) and tasks.py (batch IN clause). (3) Change all ORM relationship lazy loading from `selectin` to `raise`.

### Consequences

**Positive:**
- Query performance improves for analytics dashboards and task tracing.

**Negative / tradeoffs:**
- `lazy="raise"` may require explicit `selectinload()` in new queries — prevents accidental N+1 but requires developer awareness.

---

## ADR-047 — LLM-powered agent tools for planning and design

**Status:** accepted
**Date:** 2026-03-18
**Context:** Agents could search, read, write, and execute code but lacked structured planning and design capabilities. Users wanting architectural designs or project plans had to describe requirements in natural language and hope the agent produced structured output.

### Decision

Add 4 LLM-powered tools in `tools/adapter.py`: `tool_create_plan` (project plans with phases/milestones), `tool_design_system` (architecture with Mermaid diagrams), `tool_design_database` (schema with DDL), `tool_design_api` (REST endpoints with schemas). Tools return structured prompts that the agent's LLM processes into rich output. Registered for CEO and Engineer (all 4), Analyst (create_plan only).

### Consequences

**Positive:**
- Structured output format. Consistent design artifacts.

**Negative / tradeoffs:**
- Additional LLM token cost per tool call. Read-only tools — no approval required.

---

## ADR-048 — PostgreSQL RLS for multi-tenant isolation

**Status:** accepted
**Date:** 2026-03-19
**Context:** Application-level workspace_id filtering is fragile — ORM bugs or SQL injection could leak cross-tenant data. Need defense-in-depth for production multi-tenant deployment.

### Decision

Implement PostgreSQL Row-Level Security (RLS) on all workspace-scoped tables via migration 006. Every query is automatically filtered by `nexus.workspace_id` set via `SET LOCAL` at session start. Superuser bypass for admin operations.

### Consequences

**Positive:** Zero-trust isolation. Even raw SQL can't access other tenants' data.
**Negative:** Requires middleware to inject workspace_id into every DB session. Admin queries need superuser context.

---

## ADR-049 — OAuth2/OIDC alongside JWT auth

**Status:** accepted
**Date:** 2026-03-19
**Context:** JWT-only auth requires users to manage passwords. Enterprise customers need SSO via existing identity providers.

### Decision

Add OAuth2 authorization code flow for Google and GitHub in `api/oauth.py`. Auto-create users on first login. Link OAuth accounts to existing users. Issue JWT tokens after OAuth callback. Keep existing password auth as fallback.

### Consequences

**Positive:** SSO for enterprise. Better UX. No password management burden.
**Negative:** Additional complexity. Provider-specific callback handling. Token refresh needed.

---

## ADR-050 — Stripe billing integration with graceful degradation

**Status:** accepted
**Date:** 2026-03-19
**Context:** Internal billing_records table tracks costs but can't process payments. Production SaaS needs real payment processing.

### Decision

Integrate Stripe in `integrations/stripe/` with graceful degradation when unconfigured. Customer management, checkout sessions, subscription webhooks. Replace manual billing with Stripe-backed records. Stripe Connect for marketplace payouts.

### Consequences

**Positive:** Real payment processing. Usage-based billing. Invoice generation.
**Negative:** External dependency. Webhook reliability concerns (mitigated by retry + idempotency).

---

## ADR-051 — LLM-based prompt injection classifier (second layer)

**Status:** accepted
**Date:** 2026-03-19
**Context:** Regex-only injection defense (5 patterns in middleware.py) cannot catch novel attack techniques. Need stronger defense for production.

### Decision

Add LLM-based classifier using small/fast model (Haiku/Flash) in `middleware.py:classify_injection_llm()`. Runs after regex check passes. Gracefully degrades on classifier failure (allows request with warning log).

### Consequences

**Positive:** Catches novel injection techniques. Defense-in-depth.
**Negative:** Added latency (~200ms per request). Token cost for classifier calls.

---

## ADR-052 — Webhook notifications with HMAC signing

**Status:** accepted
**Date:** 2026-03-19
**Context:** Users need to integrate NEXUS task events into external workflows (Slack, CI/CD, monitoring).

### Decision

CRUD webhook subscriptions in `integrations/webhooks/`. HMAC-SHA256 signed payloads with `X-Nexus-Signature` header. Exponential backoff retry (3 attempts). Auto-deactivate after 10 consecutive failures.

### Consequences

**Positive:** Extensible notification system. Verifiable payloads.
**Negative:** Outbound HTTP calls from backend. Needs monitoring for delivery failures.

---

## ADR-053 — Per-agent cost alerts with three-layer budget enforcement

**Status:** accepted
**Date:** 2026-03-19
**Context:** Global daily spend cap ($5/day) and per-task token budgets exist, but no way to limit spending per individual agent. High-cost agents (CEO, Engineer) can consume disproportionate budget.

### Decision

Add `agent_cost_alerts` table with per-agent daily_limit_usd. Redis-cached spend counter with DB fallback. Integrated into `AgentBase._check_budget()` as third check layer (daily global → per-task → per-agent).

### Consequences

**Positive:** Granular cost control. Three independent budget layers.
**Negative:** Additional Redis key per agent per day. Query cost for DB fallback.

---

## ADR-054 — Provider health monitoring with ring buffer

**Status:** accepted
**Date:** 2026-03-19
**Context:** Circuit breaker catches failures but provides no latency or error rate visibility. Users can't answer "why is the agent slow?" without provider-level metrics.

### Decision

In-memory ring buffer (last 100 calls per provider) in `core/llm/provider_health.py`. Tracks latency + success/failure. Periodic flush to `provider_health` DB table. Status derived from error rate + circuit breaker state.

### Consequences

**Positive:** Real-time provider visibility. Historical health data.
**Negative:** In-memory state lost on restart (mitigated by periodic DB flush).

---

## ADR-055 — Model benchmarking reusing prompt_benchmarks test cases

**Status:** accepted
**Date:** 2026-03-19
**Context:** 60 prompt_benchmarks already exist (10 per role). No way to compare how different models perform on the same test cases.

### Decision

Reuse `prompt_benchmarks` table as test input. Run benchmarks against specified models. Score using keyword/format matching against expected_criteria. Store results in `model_benchmarks` table.

### Consequences

**Positive:** No duplicate test case maintenance. Directly comparable results.
**Negative:** Scoring is heuristic-based (not LLM-as-judge). Sufficient for cost/speed comparison.

---

## ADR-056 — Cron-based task scheduling via croniter

**Status:** accepted
**Date:** 2026-03-19
**Context:** Users need recurring tasks ("every Monday, compile a report"). Temporal handles durable execution but scheduling needs cron expression support.

### Decision

Add `task_schedules` table with cron_expression field. Use `croniter` library for cron parsing and next_run_at calculation. Scheduler tick checks for due schedules and creates tasks. CRUD API for schedule management.

### Consequences

**Positive:** Standard cron syntax. Familiar to users. Lightweight scheduling.
**Negative:** New dependency (croniter). Scheduler tick must run reliably (background task).

---

## ADR-057 — QA multi-round rework with escalation guard

**Status:** accepted
**Date:** 2026-03-19
**Context:** QA rejection triggers one rework attempt. If it fails again, the task fails permanently. No way for QA to give iterative feedback across multiple rounds.

### Decision

Add configurable `qa_max_rework_rounds` (default 2). Track round in payload. Accumulate previous QA feedback in each rework instruction. After max rounds, escalate to `human.input_needed` instead of failing.

### Consequences

**Positive:** Better output quality through iterative refinement. Human escalation prevents infinite loops.
**Negative:** Multi-round rework increases token cost. Needs monitoring for rework rate.

---

## ADR-058 — ANP evaluation — defer adoption until IETF RFC published

**Date:** 2026-03-21
**Status:** accepted
**Decided by:** claude
**Relates to:** CLAUDE.md §9, BACKLOG-044
**Supersedes:** n/a

### Context

The Agent Network Protocol (ANP) aims to be "the HTTP of the Agentic Web" with three layers:
identity (W3C DID), meta-protocol (negotiation), and application (semantic web). NEXUS currently
uses bearer tokens for A2A authentication. ANP's DID-based identity could provide stronger,
decentralized agent identity for federation. However, ANP's application layer is still in development.
The W3C AI Agent Protocol Community Group formed June 2025, IETF draft submitted October 2025
(draft-zyyhl-agent-networks-framework-01, expires April 2026). NIST CAISI launched February 2026
with AI agent identity as a focus area.

### Decision

Monitor ANP development. Do NOT adopt until IETF RFC is published (target 2026-2027).
Plan migration path from bearer tokens to DIDs as a future enhancement.
Current A2A bearer token authentication is sufficient for Phase 6 federation.

### Alternatives considered

**Option A: Adopt ANP now**
- Pros: Early mover advantage, future-proof identity layer
- Cons: Application layer incomplete, no production SDKs, spec may change
- Why rejected: Risk of building on unstable foundation

**Option B: Build custom DID layer**
- Pros: Full control, tailored to NEXUS needs
- Cons: Reinventing the wheel, won't interop with emerging standard
- Why rejected: ANP will provide this; wait for stability

### Consequences

**Positive:** Avoid building on unstable protocol. NEXUS federation works with bearer tokens today.
**Negative:** No decentralized identity until ANP matures. Bearer tokens require centralized trust.

---

## ADR-059 — AP2 evaluation — adopt only if paid A2A marketplace launches

**Date:** 2026-03-21
**Status:** accepted
**Decided by:** claude
**Relates to:** CLAUDE.md §9, BACKLOG-043
**Supersedes:** n/a

### Context

Google's Agent Payments Protocol (AP2) has matured significantly since Phase 5 assessment.
Full specification released September 2025 with 60+ supporting organizations (Adyen, Mastercard,
PayPal, American Express, Revolut, Salesforce). No longer Google-centric. Uses cryptographically-
signed "Mandates" as the trust primitive for agent-to-agent payments. Supports credit/debit,
stablecoins, real-time bank transfers, and crypto (A2A x402 extension). NEXUS currently uses
Stripe for user-to-NEXUS billing. AP2 would add agent-to-agent payment settlement.

### Decision

Do NOT adopt AP2 now. Evaluate only if NEXUS launches a paid A2A marketplace where external
agents charge for services. Current Stripe-based billing handles user-to-NEXUS payments.
AP2's Mandates pattern is interesting — study for potential `human_approvals` enhancement.

### Alternatives considered

**Option A: Integrate AP2 now**
- Pros: Ready for paid marketplace, industry-standard payment protocol
- Cons: No paid marketplace exists yet, adds complexity for unused feature
- Why rejected: YAGNI — build when needed

### Consequences

**Positive:** Simpler system. Stripe handles current billing needs. No unnecessary integration.
**Negative:** If paid marketplace launches, AP2 integration will be needed retroactively.

---

## ADR-060 — Federation registry — centralized first, DID-based later

**Date:** 2026-03-21
**Status:** accepted
**Decided by:** claude
**Relates to:** CLAUDE.md §9, BACKLOG-041, ADR-058
**Supersedes:** n/a

### Context

NEXUS needs multi-instance federation — multiple NEXUS deployments discovering each other's
capabilities and delegating tasks. Two approaches: (1) centralized registry where instances
register their Agent Cards, or (2) decentralized discovery via DID-based identity (ANP).
The A2A gateway infrastructure is fully operational (inbound + outbound) from Phase 2-3.
ANP is not yet stable (see ADR-058).

### Decision

Build a centralized federation registry (Phase 6). Each NEXUS instance registers its
Agent Card URL. The registry periodically refreshes cards and indexes capabilities.
New table: `federation_registry`. New service: `a2a/federation.py`. New API: `/api/federation/`.
When ANP matures (ADR-058), migrate to DID-based discovery as the identity layer,
keeping the centralized registry as a bootstrap/fallback mechanism.

### Alternatives considered

**Option A: Wait for ANP and skip centralized registry**
- Pros: Only build once (DID-based from the start)
- Cons: Federation blocked for 1+ years waiting for protocol stability
- Why rejected: Federation has immediate value; centralized registry ships now

**Option B: Full mesh (every instance knows every other)**
- Pros: No central point of failure
- Cons: Doesn't scale, requires gossip protocol
- Why rejected: Premature complexity

### Consequences

**Positive:** Federation available now. Simple HTTP-based discovery. Easy to operate.
**Negative:** Centralized registry is a single point of failure. Will need migration to DIDs later.

---

## ADR-061 — Reaffirm Pydantic AI over LangChain/LangGraph

| Field | Value |
|-------|-------|
| Status | accepted |
| Date | 2026-04-01 |
| Context | Phase 8 planning evaluated whether to switch from Pydantic AI to LangChain/LangGraph |

### Decision

Stay with Pydantic AI. Do NOT migrate to LangChain or LangGraph.

### Rationale

1. LangGraph would compete with Kafka for orchestration control — two orchestrators in one codebase fight each other
2. Pydantic AI is isolated inside `AgentBase` — if it ever needs replacing, nothing else changes
3. Pydantic AI v1.74 (March 2026) is classified "Production/Stable" on PyPI
4. ~75% less code than LangGraph for equivalent functionality
5. Switching = 2-3 weeks rewriting all agents for zero new features
6. Clear separation: Kafka (orchestration) + Temporal (durability) + Pydantic AI (structured LLM calls)

### Consequences

**Positive:** No migration cost. Architecture stays clean. Each layer has one job.
**Negative:** Smaller ecosystem than LangChain. Must build some utilities ourselves.
**Future:** Monitor Pydantic Deep Agents for checkpoint/rewind and native budget enforcement.

---

## ADR-062 — E2B Firecracker microVM for agent sandbox execution

| Field | Value |
|-------|-------|
| Status | accepted |
| Date | 2026-04-01 |
| Context | Agent Engineer needs isolated environments to clone repos, install deps, run tests |

### Decision

Integrate E2B (Firecracker microVMs) for agent code execution sandboxes.

### Alternatives considered

- Docker containers: weaker isolation (shared kernel), kernel escape risk
- Daytona: AGPL-3.0 license (restrictive for SaaS), Docker-based by default
- Docker Sandboxes: requires Docker Desktop 4.60+, not self-hostable

### Rationale

- Firecracker = same isolation as AWS Lambda (hardware-level)
- Apache-2.0 license — no SaaS restrictions, self-hostable for enterprise
- Python SDK integrates naturally as Pydantic AI tool
- ~$0.05/hour per sandbox — cost-effective, bill back to tenants

### Consequences

**Positive:** Agents can safely execute untrusted code, run test suites, build projects.
**Negative:** Requires E2B API key or self-hosted infrastructure. Adds latency (~200ms cold start).

---

## ADR-063 — Uptime Kuma + SLA engine for platform monitoring

| Field | Value |
|-------|-------|
| Status | accepted |
| Date | 2026-04-01 |
| Context | No platform-level uptime tracking exists; can't answer "what was our uptime last month?" |

### Decision

Two-layer approach: (1) Uptime Kuma for external monitoring, (2) custom SLA engine for per-tenant compliance.

### Rationale

- Uptime Kuma: MIT license, 60k+ stars, self-hosted, built-in status page
- SLA engine: 5-minute metric snapshots, rolling 30-day compliance, per-tier thresholds
- Separated because external monitoring should be independent of the platform itself

### Consequences

**Positive:** Can offer SLA guarantees per pricing tier. Status page for customers.
**Negative:** Additional Docker service. SLA snapshots grow over time (need retention policy).

---

## ADR-064 — Wire existing OTel stub into agent/LLM/Kafka code

| Field | Value |
|-------|-------|
| Status | accepted |
| Date | 2026-04-01 |
| Context | OTel decorators exist in tracing.py but were never called from production code |

### Decision

Wire existing OTel context managers into base.py (agents), adapter.py (tools), and consumer.py (Kafka). Add Kafka trace context propagation. Keep opt-in via `OTEL_EXPORTER_ENDPOINT`.

### Rationale

- OTel adds distributed traces (CEO→Engineer→QA as one trace with latency breakdown)
- Existing structlog logging is NOT replaced — OTel traces complement logs
- Zero overhead when disabled (no-op spans)
- Enterprise customers expect Jaeger/Datadog integration

### Consequences

**Positive:** Full distributed tracing when enabled. Enterprise-ready observability.
**Negative:** OTel SDK adds dependency weight. Kafka headers grow slightly with trace context.

---

## ADR-065 — Temporal deep integration — child workflows, signals, sagas

| Field | Value |
|-------|-------|
| Status | accepted |
| Date | 2026-04-01 |
| Context | Temporal integration was ~20% done — polling-based, no retries, no compensation |

### Decision

Rewrite Temporal integration with proper patterns: child workflows for CEO/subtask/QA phases, fan-out/fan-in for parallel execution, signals for human approval, queries for dashboard status, saga compensation for failure cleanup.

### Rationale

- Temporal is NEXUS's key differentiator vs CrewAI/AutoGen — durable, crash-recoverable workflows
- Polling-based approach was a PoC; production needs heartbeats, retry policies, compensation
- Signals enable proper human-in-the-loop without blocking worker threads

### Consequences

**Positive:** Crash-recoverable multi-agent workflows. Real-time status via queries.
**Negative:** More complex workflow code. Requires Temporal server infrastructure.

---

## ADR-066 — Workspace API keys for programmatic access

| Field | Value |
|-------|-------|
| Status | accepted |
| Date | 2026-04-01 |
| Context | No way to submit tasks programmatically — only dashboard UI |

### Decision

Add API key management: CRUD for per-workspace keys with scoping (read, submit, admin). Keys are hashed (SHA-256) in DB, raw key shown once on creation.

### Consequences

**Positive:** Enables CI/CD integration, webhooks, third-party tool access.
**Negative:** Must implement rate limiting per key. Key rotation needs UX.

---

## ADR-067 — Team invitations and RBAC enforcement

| Field | Value |
|-------|-------|
| Status | accepted |
| Date | 2026-04-01 |
| Context | Workspaces exist but can't invite members; role field in workspace_members is never enforced |

### Decision

Add invitation flow (email-based with token, 7-day expiry) and enforce RBAC roles: owner, admin, member, viewer.

### Consequences

**Positive:** Teams can collaborate. Proper access control per role.
**Negative:** Email delivery infrastructure needed for invitations at scale.

---

<!-- New ADR entries go above this line, with the next ID number -->
<!-- Next ID: ADR-068 -->

---

*Last updated: 2026-03-21*
*Next ADR ID: ADR-061*
*Decision count: 51 accepted, 3 superseded*

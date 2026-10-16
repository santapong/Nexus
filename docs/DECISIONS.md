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
| ADR-127 | Preserve exact native manager histories with a distinct unconfigured full method | accepted | 2026-10-15 |
| ADR-126 | Require native dual-output publication and independent acceptance under own scope | accepted | 2026-10-15 |
| ADR-125 | Preserve truthful generated HTML with derived-only company016 persistence | accepted | 2026-10-15 |
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
| ADR-077 | MessageBus abstraction — broker-agnostic Protocol + adapters | proposed | 2026-07-10 |
| ADR-078 | Transport strategy — pluggable, PoC-decided (Kafka/Redpanda/NATS/Redis) | proposed | 2026-07-10 |
| ADR-079 | Agent harness (staged) — guard-chain contract → `Agent.iter()` loop | proposed | 2026-07-10 |
| ADR-080 | Loop engineering — unified `LoopPolicy` + embedding convergence | proposed | 2026-07-10 |
| ADR-081 | Durable execution — DBOS for intra-task; Temporal scoped to >1hr | proposed | 2026-07-10 |
| ADR-082 | Observability — Logfire + OTel GenAI semantic conventions | proposed | 2026-07-10 |
| ADR-083 | A2A v1.0 upgrade — LF-hosted spec + official SDK | proposed | 2026-07-10 |
| ADR-084 | AG-UI adoption for dashboard streaming (Pydantic AI native) | proposed | 2026-07-10 |
| ADR-085 | MCP auth modernization — OAuth/OIDC + PKCE + CIMD | proposed | 2026-07-10 |
| ADR-086 | Supersede ADR-014 — Pydantic AI 1.x (unlocks `Agent.iter()`) | proposed | 2026-07-10 |
| ADR-087 | "Co" personal-assistant persona over the CEO orchestrator | proposed | 2026-07-12 |
| ADR-088 | VoiceFactory — provider-agnostic STT/TTS (browser/cloud/local) | proposed | 2026-07-12 |
| ADR-089 | User file-upload endpoint + `attachments` table | proposed | 2026-07-12 |
| ADR-090 | Document ingestion (PDF/Word/Excel/Parquet) via `core/ingest` | proposed | 2026-07-12 |
| ADR-091 | HTML presentation output — typed `presentation` field, sanitized | proposed | 2026-07-12 |
| ADR-092 | React Flow for the Co DAG canvas | proposed | 2026-07-12 |
| ADR-093 | Frontend modernization — React 19 + Compiler, Tailwind v4, Motion | proposed | 2026-07-12 |
| ADR-094 | DravenIQ company system as the first product | proposed | 2026-10-05 |
| ADR-095 | One DBOS execution engine for the company profile | proposed | 2026-10-05 |
| ADR-096 | Governed Pydantic AI 2.x harness and segmented approval | proposed | 2026-10-05 |
| ADR-097 | Native bounded Pi builder and portable deployment | proposed | 2026-10-05 |
| ADR-098 | Evaluated multi-provider routing and atomic cost reservations | proposed | 2026-10-05 |
| ADR-099 | Owner oversight, dashboard/email and deferred Meta Harness | proposed | 2026-10-05 |
| ADR-100 | Standalone company contracts and PostgreSQL approval/cost journal | accepted | 2026-10-13 |
| ADR-101 | Independent clean company-profile migration lineage | accepted | 2026-10-13 |
| ADR-102 | Pin the experimentally verified Pydantic AI 2.54 and DBOS 3.2 runtime | accepted | 2026-10-13 |
| ADR-103 | Registered authority, lifetime quotas and principal-bound effects | accepted | 2026-10-14 |
| ADR-104 | One non-retrying effect step for governed offline recovery | accepted | 2026-10-14 |
| ADR-105 | Required per-request model gate and local wire/schema validation | accepted | 2026-10-14 |
| ADR-106 | Native permission-bound Brain provenance | accepted | 2026-10-14 |
| ADR-107 | Supervised management and independent acceptance | accepted | 2026-10-14 |
| ADR-108 | Permanent notification ledger and separate native wake migration | accepted | 2026-10-14 |
| ADR-109 | Qualified native mapping preserves older physical profiles | accepted | 2026-10-14 |
| ADR-110 | Separate current model eligibility from immutable registrations | accepted | 2026-10-14 |
| ADR-111 | Bounded authenticated operator backup envelope | accepted | 2026-10-14 |
| ADR-112 | Explicit model-free mechanical engineering profiles | accepted | 2026-10-14 |
| ADR-113 | Owner-bound same-source PostgreSQL/DBOS recovery qualification | accepted | 2026-10-14 |
| ADR-114 | Explicit model-free owner notification admission | accepted | 2026-10-14 |
| ADR-121 | Separate fresh mixed sender authority from issued history | accepted (source) | 2026-10-15 |
| ADR-122 | Assemble complete private engineering bodies through native bounded reads | accepted (source) | 2026-10-15 |
| ADR-128 | Shared bounded mount reader with distinct current parent profiles | accepted (source) | 2026-10-15 |
| ADR-129 | Bind nominated image reference and configuration separately | accepted (source) | 2026-10-16 |

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

## ADR-068 — OAuth token encryption at rest via Fernet

| Field | Value |
|-------|-------|
| Status | accepted |
| Date | 2026-05-19 |
| PR | #29 |
| Context | OAuth refresh and access tokens were stored as plaintext in `oauth_tokens.access_token` / `refresh_token` columns. Audit war-room flagged this as P0: a Postgres dump or a compromised replica would leak every connected user's third-party identity. |

### Decision

Encrypt OAuth token columns at rest using **Fernet (AES-128-CBC + HMAC-SHA256)** keyed off the `NEXUS_ENCRYPTION_KEY` environment variable. Encryption/decryption happens in the model layer via a `TokenCipher` helper. Migration 011 backfills existing rows in place: SELECT → encrypt → UPDATE in a single transaction, then drops the legacy plaintext index.

### Alternatives rejected

- **AWS KMS / GCP KMS** — adds an operational dependency and a per-token API round-trip; key rotation gets caught up in cloud IAM. Not worth it for a single-key envelope.
- **pgcrypto / DB-native encryption** — key would have to live in the DB role's GUC or be passed via SQL each call. Key management ends up *harder*, not easier, and audit logs would show the key in plaintext.
- **Hashing only** — refresh tokens are reusable secrets that must be retrievable; one-way hashing breaks the refresh flow.

### Consequences

**Positive:** Database dumps no longer leak third-party tokens. `NEXUS_ENCRYPTION_KEY` rotation is a single in-process re-encryption job. Same primitive can be reused for other secrets-at-rest fields.
**Negative:** Loss of `NEXUS_ENCRYPTION_KEY` makes all stored tokens unrecoverable; key must be backed up in SOPS alongside infra secrets. CPU overhead on every token read (~50µs per token, negligible).

---

## ADR-069 — RLS context injection via SQLAlchemy `after_begin` listener

| Field | Value |
|-------|-------|
| Status | accepted |
| Date | 2026-05-19 |
| PR | #30 |
| Context | ADR-048 established PostgreSQL row-level security with `SET LOCAL nexus.workspace_id = '{uuid}'`. The original implementation relied on route handlers remembering to issue the `SET LOCAL` themselves. Audit found three handlers that forgot, leaking cross-tenant rows through `EXISTS` subqueries. RLS is only secure if it is unbypassable. |

### Decision

Inject the workspace UUID at the **SQLAlchemy session level** via an `after_begin` event listener. Every request-scoped session, before any route handler sees it, executes `SET LOCAL nexus.workspace_id = '{uuid}'` against the active connection. The UUID comes from a `ContextVar` populated by the auth middleware. Sessions without a workspace context fail fast.

### Alternatives rejected

- **Litestar middleware** — Litestar's middleware runs before dependency injection wires up the DB session, so the middleware couldn't reliably reach the session that the route would receive. Workarounds required a second DB connection.
- **Manual SET LOCAL in each handler** — exactly what got us into this audit finding. Forgetting one is silent and exploitable.
- **Per-query filtering in code** — defeats the purpose of RLS; one missed `.filter(workspace_id=...)` reopens the hole.

### Consequences

**Positive:** Forgetting the workspace filter is now impossible — the database refuses to return out-of-tenant rows regardless of application bugs. New code automatically inherits isolation.
**Negative:** Tasks running outside an HTTP request (Taskiq workers, agent loops) must explicitly call `set_workspace_context(uuid)` before opening a session, or queries 404. Documented in coding policy.

---

## ADR-070 — A2A token hashing via PBKDF2-HMAC-SHA256

| Field | Value |
|-------|-------|
| Status | accepted |
| Date | 2026-05-19 |
| PR | #31 |
| Context | A2A bearer tokens were stored as raw SHA-256 hashes. SHA-256 is too fast — a leaked DB dump is brute-force-able offline at billions of guesses per second on consumer GPUs. We need a slow hash with per-token salt, plus a way to look tokens up without scanning the whole table. |

### Decision

Use **PBKDF2-HMAC-SHA256** with **600,000 iterations** (current OWASP guidance) and a per-token 16-byte random salt for verification. For lookup, compute a separate **HMAC-SHA256 deterministic ID** keyed by a server-side pepper (`A2A_TOKEN_PEPPER`) — this is what the index sits on. Tokens carry a `hash_algo` column (`sha256` | `pbkdf2_sha256_600k`) so legacy tokens keep working until users rotate.

### Alternatives rejected

- **bcrypt** — verify cost is higher than necessary for our token-per-request usage, and bcrypt truncates input at 72 bytes which complicates long-token futures.
- **argon2** — strongest option but pulls in a C dependency that complicates our slim Docker image and slowed cold-starts in benchmarks by ~150ms.
- **Plain SHA-256** — the status quo; offline-crackable in hours.

### Consequences

**Positive:** Token DB dumps are no longer practically crackable. Deterministic lookup ID keeps `O(1)` validation despite the slow hash. Hash-algo column means rotation is gradual, not breaking.
**Negative:** Token verification is now ~50ms instead of ~50µs. At 1k req/s the verify cost is ~50 CPU-seconds/s — acceptable behind a rate limiter and Redis-cached "recently validated" set.

---

## ADR-071 — Audit log partitioning with per-partition immutability triggers

| Field | Value |
|-------|-------|
| Status | accepted |
| Date | 2026-05-19 |
| PR | #32 |
| Context | The `audit_log` table is documented as append-only in CLAUDE.md §12 ("never updated, never deleted"), but nothing in the schema actually enforced this. A compromised superuser or a buggy migration could rewrite history. The table is also growing fast — Phase 5 ships ~50k events/day per active workspace — and unpartitioned indexes are starting to slow inserts. |

### Decision

Convert `audit_log` to a `PARTITION BY RANGE (created_at)` table with **monthly partitions**. Attach a `BEFORE UPDATE OR DELETE` trigger to each partition that raises `EXCEPTION` unless the connection role is the dedicated `audit_archiver` (used only by the offline archival job). New partitions are pre-created by a monthly cron via `pg_cron`.

### Alternatives rejected

- **`pg_partman` extension** — adds an extension dependency that complicates managed-Postgres deployments (RDS, Cloud SQL) where superuser is restricted. Hand-rolling monthly partitions is ~30 lines of SQL.
- **Application-layer "soft delete"** — defeats the entire immutability claim. If the application can rewrite history, so can an attacker who pops the app.
- **Append-only via permissions alone** — Postgres role-based DELETE/UPDATE revocation can be re-granted; a trigger that errors regardless of role is harder to bypass quietly.

### Consequences

**Positive:** Audit log is now genuinely append-only at the DB level — a falsified row requires intent at the trigger level, which itself is audited. Old partitions can be detached and cold-archived to S3 cheaply. Insert latency improved ~3x on busy workspaces.
**Negative:** Cross-month range queries now hit multiple partitions; the planner handles this fine but EXPLAIN output is noisier. `audit_archiver` role must be carefully scoped and its credential stored only in SOPS.

---

## ADR-072 — Memory-write failures route to DLQ, never publish

| Field | Value |
|-------|-------|
| Status | accepted |
| Date | 2026-05-19 |
| PR | #33 |
| Context | CLAUDE.md §20 establishes the invariant: "Write episodic memory before publishing result. If memory write fails → task is failed, not published." But `AgentBase._execute_with_guards` was catching memory exceptions and warn-logging them, then publishing the result anyway. This is the most dangerous kind of "silent" — the user sees a successful task, but no episodic record exists, so future memory-recall can't learn from it and audits can't reconstruct what the agent did. |

### Decision

Introduce a `MemoryWriteFailed` sentinel exception. The inner `_write_memory()` call lets this exception propagate up through `_execute_with_guards`. The outer guard chain catches it, marks the task `failed`, writes the unsanitized output to the dead-letter queue (`{topic}.dead_letter`), and crucially **does not publish to `agent.responses`**. The user-facing failure message points to the audit log for triage.

### Alternatives rejected

- **Silent retry** — papers over real schema/embedding-service problems and can publish the result eventually anyway, violating the "memory before publish" ordering.
- **Warn-and-publish** — the previous broken behavior. Hides side-effecting tool calls from history; "agent did something, no record".
- **Fail open with a sentinel "memory_failed=true" flag in the published result** — pollutes the result envelope; consumers would have to special-case it.

### Consequences

**Positive:** Restores the §20 invariant. Memory write failures are now loud and surface in the DLQ dashboard. No task ever publishes a result without a matching `episodic_memory` row.
**Negative:** Memory subsystem outages now visibly fail user tasks instead of degrading silently. This is correct behavior but raises the operational bar for memory-store availability. Mitigation: memory writes already retry 3x with backoff before raising.

---

## ADR-073 — Plugin `requires_approval` enforcement with dangerous-name regex force-flip

| Field | Value |
|-------|-------|
| Status | accepted |
| Date | 2026-05-19 |
| PR | #34 |
| Context | Phase 5 introduced third-party plugin tools via `PluginRegistry`. Manifests declare a `requires_approval: bool` per tool. A malicious or naive plugin author could declare `requires_approval: false` on a destructive tool — e.g. `delete_user(id)` — bypassing `require_approval()` and silently letting agents do irreversible things. The guard chain trusts the manifest, which is the wrong trust boundary. |

### Decision

Enforce two layers in the plugin loader:

1. **Whitelist explicit:** `requires_approval` must be present in every tool manifest. Missing field is a load-time error.
2. **Force-flip on dangerous names:** any tool whose name (case-insensitive) matches the regex `(delete|remove|drop|push|send|pay|charge|deploy|publish|destroy)` is silently re-flagged `requires_approval = true` regardless of what the manifest claims. A warning is logged and written to `audit_log` so plugin authors see it.

### Alternatives rejected

- **Trust manifest authors** — first-party plugins are fine; third-party plugins are exactly the threat model. Trusting a string in JSON is not security.
- **Sandbox all plugin calls behind approval** — too noisy; read-only plugin tools (search, lookups) would generate constant approval prompts.
- **Semantic / LLM-based classifier on tool description** — non-deterministic and slow at load time. The regex covers the high-blast-radius verbs cheaply; a classifier can be layered on later if needed.

### Consequences

**Positive:** Plugins cannot quietly bypass human-in-the-loop on irreversible actions. The list of dangerous verbs is centralized and reviewable.
**Negative:** False positives are possible — a plugin named `send_notification_to_dashboard` (read-only WebSocket push) gets flagged. Plugin authors can use synonyms (`dispatch`, `emit`) to avoid the regex, which is fine: the regex is a safety net, not the only line of defense (`require_approval` itself is still enforced by `guards.py`).

---

## ADR-074 — Director synthesis with plan-scope HALT routes to human

| Field | Value |
|-------|-------|
| Status | accepted |
| Date | 2026-05-19 |
| PR | #35–#36 |
| Context | The Director (Phase 7) synthesizes specialist outputs into a single high-quality result. Audit war-room asked: what happens if a specialist's output references a subtask the CEO never planned, or contains content matching `security_blocked_patterns` (PII, secret-shaped strings, jailbreak signatures)? Previous behavior was to forward everything to QA and rely on QA to catch it. QA's job is *quality*, not *security* — and a quality reviewer is the wrong filter for a leaked API key. |

### Decision

The Director performs a **plan-scope check** before synthesis:

- Every subtask-ID referenced in a specialist's output must appear in the CEO's execution plan. Unknown IDs → HALT.
- Every output is run through `core/sanitization.py` against `security_blocked_patterns`. Match → HALT.

HALT outcomes route to `human.input_needed` with the offending excerpt redacted, instead of being forwarded to `task.review_queue` (QA). The original output is preserved in `audit_log` for forensics but never reaches QA or the user without explicit human approval.

### Alternatives rejected

- **Forward everything to QA** — QA agents are LLM-based quality reviewers, not security filters. They will sometimes "approve through" content that pattern-matches a leak.
- **Drop silently and proceed with partial synthesis** — loses the signal that the system might be under attack or a specialist is misbehaving. Always log, always escalate.
- **Auto-redact and continue** — fine for incidental PII (e.g. an email in a test fixture), but for plan-scope violations (specialist referencing tasks it wasn't assigned), redaction hides a real correctness bug.

### Consequences

**Positive:** Security checks happen at the synthesis bottleneck, where every result must pass. Plan-scope violations are caught immediately rather than surfacing as anomalies in audit log review weeks later. Clear separation: Director = security review, QA = quality review.
**Negative:** Adds latency on the Director's hot path (plan-scope check is ~5ms, pattern scan is ~20ms per 10KB of output). HALTs require human attention, so a flaky regex pattern could cause approval-queue noise — patterns are version-controlled and reviewed quarterly.

---

## ADR-075 — Stripe webhook idempotency via Redis event-ID lock

| Field | Value |
|-------|-------|
| Status | accepted |
| Date | 2026-05-19 |
| PR | #37–#38 |
| Context | Stripe delivers webhooks at-least-once and replays on any `5xx` response for up to ~3 days. ADR-050 (Stripe billing) didn't specify idempotency, so a network blip during a `customer.subscription.updated` could double-apply the change, charging the customer twice or duplicating an invoice row. |

### Decision

On every Stripe webhook handler entry, write `stripe:event:{event_id}` to Redis db:3 (idempotency keys) with `SETNX` and a **7-day TTL**. If the key already exists, return `200 OK` immediately without re-processing. Successful processing leaves the key in place; transient failures (e.g. downstream service unavailable) `DEL` the key so the next retry will be re-processed.

### Alternatives rejected

- **DB unique constraint on `stripe_event_id`** — works but adds a row write and unique-index lookup on every webhook before any business logic; under burst load (Stripe replays in bursts) this contends on the index. Redis SETNX is the right shape for "did I already see this exact event ID".
- **Application-level dedup cache without TTL** — never expires; memory leaks. Redis with TTL is bounded.
- **Trust Stripe's "won't retry within X seconds"** — Stripe's retry semantics are at-least-once, period. Don't build on a SLA we don't control.

### Consequences

**Positive:** Stripe replays are now safely no-ops. Double-charges and duplicate billing rows from network blips eliminated. 7-day TTL gives ample margin over Stripe's ~3-day retry window.
**Negative:** Idempotency lives in Redis db:3, which is treated as ephemeral elsewhere. If Redis is wiped during a Stripe replay window we could re-process — mitigated because Stripe's webhook signature timestamp lets us additionally reject events older than 5 minutes on first delivery. The 7-day TTL only matters for genuine replays.

---

## ADR-076 — Idempotent crash recovery via Redis lock, with DB column as future hardening

| Field | Value |
|-------|-------|
| Status | accepted |
| Date | 2026-05-19 |
| PR | #39–#40 |
| Context | Phase 7's crash-recovery service (`core/recovery.py`) scans for orphaned tasks (status=`running` with stale heartbeat) on every backend startup and re-queues or fails them. Under a restart loop — e.g. a misconfigured deployment crashing every 30 seconds — the recovery service was re-publishing the same task to Kafka on every boot, building up duplicate messages that the consumer then had to dedup via the existing `idempotency:{message_id}` keys. Cheaper to dedup at the source. |

### Decision

Wrap recovery actions in a Redis lock: `recovery_attempt:{task_id}` with a **1-hour TTL** in db:3. Recovery only fires for tasks whose lock can be acquired; an in-progress restart loop will see existing locks and skip. After recovery finishes (success or terminal fail), the lock stays in place for the full TTL so a subsequent same-hour restart doesn't re-attempt.

This is a near-term fix. The long-term plan is to add a `recovery_attempted_at: timestamptz` column to the `tasks` table so recovery state survives Redis wipes — but Redis is fine for now because the failure mode it prevents (restart-loop duplication) is itself ephemeral.

### Alternatives rejected

- **Skip idempotency entirely** — what we had. Generates Kafka spam during outages, hammers the DLQ.
- **DB column only (no Redis)** — correct in steady state but requires a `tasks` migration and adds DB writes to every recovery scan. Acceptable as Phase 8 hardening, not blocking.
- **Atomic CAS on `tasks.status`** — works but only covers the "don't re-queue" case; doesn't prevent re-emitting structural events like `audit_log` entries for the recovery attempt.

### Consequences

**Positive:** Restart loops no longer thrash the Kafka topology. Recovery is now an at-most-once-per-hour operation per task. Idempotency primitive matches existing Redis db:3 conventions (`idempotency:{message_id}`).
**Negative:** Redis wipe during an active recovery window could re-trigger recovery; in practice this is a controlled scenario (we restart Redis intentionally) and the existing message-ID idempotency catches the downstream duplication. Migration to a DB column is filed as a future ADR follow-up.

---

## ADR-077 — MessageBus abstraction — broker-agnostic Protocol + adapters

| Field | Value |
|-------|-------|
| Status | proposed |
| Date | 2026-07-10 |
| Relates to | CLAUDE.md §10, §3; REDESIGN.md §2; ADR-007, ADR-008 |
| Context | `nexus.core.kafka.*` is imported in 44 files with ~30 `publish()` calls, and `AgentBase.run()` *is* an `aiokafka` consumer loop. `producer.py`/`consumer.py` construct `aiokafka` objects directly and leak the `ConsumerRecord` shape (`msg.value`, `msg.topic`) into callers. The only broker-neutral pieces are the `KafkaMessage` envelope and the `Topics` constants. Re-evaluating the transport (ADR-078) is impossible while the whole system is welded to one client. |

### Decision

Introduce `nexus/core/bus/` with a `MessageBus` Protocol — `publish(topic, message, key)`,
`subscribe(*topics, group_id) -> AsyncIterator[InboundMessage]`, `ack/nack`, `dead_letter`, `health`,
`start/stop` — plus adapters `kafka_bus.py` (wraps today's aiokafka; also serves Redpanda unchanged),
`nats_bus.py` (JetStream), and `redis_bus.py` (XADD/XREADGROUP + XCLAIM). `factory.py::get_bus()` selects
on `settings.MESSAGE_BUS_BACKEND`. An `InboundMessage` value object normalizes `{topic, value, key,
headers, id}` so no adapter's native record shape leaks into `base.py`/`result_consumer.py`. The existing
`producer.publish` / `consumer.create_consumer` free functions are re-pointed to delegate to `get_bus()`,
so all 44 call sites keep working unchanged. Idempotency (`check_idempotency`, Redis `SET NX`) and
dead-letter routing lift into the bus layer so every adapter inherits them once. `Topics`, the
`KafkaMessage` envelope, and HMAC `signing.py` are reused as-is.

### Alternatives rejected

- **Leave Kafka hard-coupled** — the status quo; makes ADR-078 undecidable and blocks the light-weight-default goal.
- **Rewrite every call site to a new client** — 44 files of churn with no rollback story. The shim is reversible.
- **Adopt a framework message bus (Restate/Inngest)** — duplicates NEXUS's existing consumers + idempotency + guard chain, and reintroduces a second orchestrator (see ADR-010).

### Consequences

**Positive:** Transport becomes a deployment flag; the PoC (ADR-078) can measure all candidates behind one
interface; the aiokafka record shape stops leaking. **Negative:** the Protocol must faithfully cover every
current Kafka behavior (offset commit timing, partition keys, rebalance, reconnect) or an adapter will drift
— mitigated by shipping the Kafka adapter first (behavior-identical) before any alternative.

---

## ADR-078 — Transport strategy — pluggable, PoC-decided; candidates Kafka/Redpanda/NATS/Redis Streams

| Field | Value |
|-------|-------|
| Status | proposed |
| Date | 2026-07-10 |
| Relates to | CLAUDE.md §10; REDESIGN.md §2; ADR-077 |
| Supersedes | ADR-008 (on acceptance) — extends its Kafka↔Redis-Streams fallback into a general pluggable-transport decision |
| Context | The NEXUS workload is agent choreography (dispatch, request/reply, dashboard fan-out, meeting polling), not analytics streaming. LLM latency dominates wall-clock; broker throughput is nearly irrelevant. Kafka works but is over-provisioned (JVM weight, batching latency floor) for the current single-user reality, while its durability/replay is genuinely wanted for the multi-tenant vision. Unbiased research surfaced a real four-way choice. |

### Decision

Do **not** pre-commit to a broker. Behind the ADR-077 seam, treat transport as configurable
(`MESSAGE_BUS_BACKEND`) and decide the *default* with a proof-of-concept over **Kafka (baseline),
Redpanda, NATS+JetStream, and Redis Streams**. The PoC replays a realistic agent trace and measures
distributions (not averages) of: request/reply round-trip, meeting-room topic churn, durable-replay
correctness under broker-kill, duplicate/DLQ behavior under consumer crash, idle+load ops footprint, and
async-Python glue lines. Decision rule: pick the lightest backend that passes durable-replay and
delivery-under-chaos at NEXUS's real concurrency; escalate to Kafka/Redpanda only if the audit-replay SLA
demands it. **Apache Pulsar is ruled out** (broken async-Python client); RabbitMQ is out of the shortlist
(no decisive win on any axis NEXUS cares about).

### Alternatives rejected

- **Stay on Kafka by default, no evaluation** — ignores the ops-weight cost the user explicitly questioned.
- **Migrate wholesale to NATS now** — best architectural fit, but committing before the PoC repeats the original mistake of an unmeasured transport choice.
- **Redis Streams as the terminal answer** — cheapest now (already in-stack) but weakest durability; a poor fit exactly when the SaaS audit requirement matters.

### Consequences

**Positive:** the "does Kafka work well / is there an alternative" question is answered with evidence, and
the answer is reversible per-deployment. **Negative:** the PoC is real work (a later phase) and needs
honest controls (identical hardware, >12h runs) to avoid vendor-benchmark bias.

---

## ADR-079 — Agent harness (staged) — guard-chain contract → `Agent.iter()` instrumented loop

| Field | Value |
|-------|-------|
| Status | proposed |
| Date | 2026-07-10 |
| Relates to | CLAUDE.md §7 (AgentBase), §20, new §26; REDESIGN.md §4; ADR-001, ADR-086 |
| Context | NEXUS owns no inference loop — LLM+tool iteration is a black box inside `pydantic_ai.Agent.run()`. The "max 20 tool calls" rule is enforced by monkey-wrapping each tool with a shared counter in `agents/factory.py:36`, and budget/approval are side-effects rather than loop invariants. There is no place to inject per-step verification, context, or tracing. |

### Decision

Adopt an explicit two-stage **harness** (instrumented scaffolding around each LLM call). **Stage 1**
(no new loop): document the existing guard chain (`base.py::_execute_guarded_body`) as the canonical outer
harness contract; unify the 6 copy-pasted `_run_with_retry` onto `core/retry.py`; wire the dormant circuit
breaker into a shared `AgentBase._invoke_llm`; load semantic memory into `_load_memory`; promote the
workspace token-budgeted context packer into a general `ContextAssembler`. **Stage 2** (own the loop):
replace `Agent.run()` with an `Agent.iter()`/`AgentRun.next()` loop inside a `HarnessRunner`, making token
budget, tool gating (retiring the monkey-counter), context injection, verification, and OTel spans
first-class per-step invariants. Stage 2 is gated behind Stage 1.

### Alternatives rejected

- **Adopt LangGraph/CrewAI/OpenAI-Agents-SDK/Google-ADK for the loop** — each is a second orchestrator and/or a Pydantic-AI replacement; conflicts with Kafka (ADR-010) or forces a runtime swap.
- **Keep the black-box `Agent.run()`** — leaves budget/limits/approval as fragile side-effects with no per-step hook.
- **Custom hand-rolled LLM loop** — reinvents what `Agent.iter()` gives for free and diverges from the Pydantic AI update path.

### Consequences

**Positive:** per-step control (budget halt at 90%, in-loop approval, reflection) with zero new
infrastructure and no Kafka conflict; Stage-1 wins land even if Stage-2 slips. **Negative:** `Agent.iter()`
internals can shift across Pydantic AI minors — mitigated by version pinning and behavior tests.

---

## ADR-080 — Loop engineering — unified `LoopPolicy` + embedding-based convergence

| Field | Value |
|-------|-------|
| Status | proposed |
| Date | 2026-07-10 |
| Relates to | CLAUDE.md §7 (Director), §23 Risk 2, new §26; REDESIGN.md §5; ADR-079 |
| Context | NEXUS has four loop levels (inference, task/guard, QA-rework, meeting convergence) with bounds scattered across constants (`MAX_TOOL_CALLS=20`, `qa_max_rework_rounds`, meeting max-rounds). Meeting convergence uses lexical Jaccard similarity with an explicit `TODO` (`core/kafka/meeting.py`) to move to embeddings, so "the agents keep saying the same thing" is detected only crudely. |

### Decision

Introduce a single `LoopPolicy` model — every loop declares `max_iterations`, `token_budget`, `timeout`,
and a `termination_predicate` — and route all four loop levels through it. Replace `meeting.py`'s Jaccard
with embedding cosine similarity via the existing `memory/embeddings.py`, with documented
convergence/stagnation/oscillation thresholds. Publish a loop-guard catalog (convergence, stagnation,
oscillation, forced-termination → human escalation) cross-referenced to the §23 unbounded-loop **cost**
risk — loop bounds are a spend-safety control, not only a quality control.

### Alternatives rejected

- **Keep per-loop ad-hoc constants** — works but makes budget/termination invisible and untestable as a unit.
- **Self-verification inside the generator** — same blind spots in, same blind spots out; the evaluator-optimizer pattern (separate Director/QA with fresh context) is retained instead.
- **Embeddings for everything immediately** — blocked on BACKLOG-052 (embeddings are never generated today); convergence upgrade is sequenced after that fix.

### Consequences

**Positive:** uniform, testable loop termination; better convergence detection; explicit tie to cost
safety. **Negative:** embedding-based convergence depends on BACKLOG-052 landing first (embeddings
currently NULL) — documented as a sequencing constraint.

---

## ADR-081 — Durable execution — DBOS for intra-task durability; Temporal scoped to >1hr workflows

| Field | Value |
|-------|-------|
| Status | proposed |
| Date | 2026-07-10 |
| Relates to | CLAUDE.md §4, §5; REDESIGN.md §3.2, §4; ADR-065 (Temporal) |
| Context | Goal (b) of the redesign is durable, observable agent loops. A crashed agent mid-run currently loses in-flight LLM/tool progress (only the Kafka message is redelivered). Temporal exists (`integrations/temporal/`) but is a heavy separate cluster and tends to want to *be* the orchestrator, which would fight Kafka (ADR-010). |

### Decision

Use **DBOS** — a Postgres-backed durable-execution *library* with a native Pydantic AI `DBOSAgent` wrapper
— to checkpoint intra-task LLM/tool steps so a crashed run resumes from the last step. DBOS adds no new
service and no event router (it reuses NEXUS's existing Postgres), so it composes with Kafka rather than
competing with it. **Temporal stays strictly scoped to genuine >1hr durable workflows** (its existing
`integrations/temporal/` intent) and must not absorb the CEO→specialist→Director→QA choreography.

### Alternatives rejected

- **Temporal for intra-task durability** — heaviest option (cluster + workers + datastore) and blurs into the second-orchestrator anti-pattern for short tasks.
- **Restate / Inngest** — designed to own event consumption + orchestration, duplicating NEXUS's Kafka consumers/idempotency/guard chain; Inngest is also TS-first.
- **No durability (status quo)** — a mid-task crash wastes tokens already spent and restarts from zero.

### Consequences

**Positive:** crash-consistent agent loops reusing existing Postgres; revives the dormant retry/breaker
intent with real durability. **Negative:** one Postgres write per durable step — acceptable since Postgres
is already the source of truth; measured in rollout phase R4.

---

## ADR-082 — Observability — Logfire + OTel GenAI semantic conventions

| Field | Value |
|-------|-------|
| Status | proposed |
| Date | 2026-07-10 |
| Relates to | CLAUDE.md §4; REDESIGN.md §3.2, §4; ADR-064 (OTel), ADR-079 |
| Context | Phase 5 wired an OTLP exporter, but the new `Agent.iter()` harness needs per-step visibility (each model request + tool call as a span), and eval/prompt tooling should map onto the existing `prompts`/`prompt_benchmarks` tables without lock-in. |

### Decision

Adopt **Pydantic Logfire** as the trace layer (one-line `logfire.instrument_pydantic_ai()`, same vendor as
the agent runtime, OTel-native), and emit **OpenTelemetry GenAI semantic-convention** spans so storage/eval
backends are swappable. Self-hosted **Langfuse** or **Arize Phoenix** may be added later for eval storage
tied to `prompts`/`prompt_benchmarks`, without rework, because everything speaks OTel.

### Alternatives rejected

- **Bespoke structured logs only** — already present, but no per-step LLM span model or eval linkage.
- **A single proprietary platform (no OTel conventions)** — lock-in; can't self-host evals later.
- **LangSmith** — tied to the LangChain/LangGraph runtime NEXUS rejected (ADR-010).

### Consequences

**Positive:** the Stage-2 loop is observable per step; convention-compliant spans keep backends portable.
**Negative:** GenAI semconv is still marked experimental upstream — expect minor attribute churn; mitigated
by centralizing span emission.

---

## ADR-083 — A2A v1.0 upgrade — LF-hosted spec + official SDK

| Field | Value |
|-------|-------|
| Status | proposed |
| Date | 2026-07-10 |
| Relates to | CLAUDE.md §9; REDESIGN.md §3.1; ADR-003 |
| Context | NEXUS's A2A gateway is built against the **April-2025 pre-1.0** Google spec. A2A has since been donated to the **Linux Foundation** and shipped **v1.0** (~Apr 2026) with 150+ orgs and 5 official SDKs. NEXUS carries a hand-rolled implementation against a superseded spec. |

### Decision

Upgrade the A2A gateway from the pre-1.0 spec to **A2A v1.0** and adopt the official Python SDK, keeping
the existing boundary-only gateway architecture (ADR-003) unchanged — agents still receive tasks on
`a2a.inbound` and cannot tell A2A tasks from human tasks. This closes a version gap and reduces custom
protocol code.

### Alternatives rejected

- **Stay on the April-2025 spec** — drifts further from an ecosystem now standardized at v1.0.
- **Also adopt ACP (IBM)** — ACP merged into A2A under the LF; adopting A2A covers it. Remove ACP from the watch list.
- **Wait for the next A2A version** — v1.0 is the stable, foundation-governed baseline; no reason to defer.

### Consequences

**Positive:** interoperability with the 150+ org A2A ecosystem; less bespoke code via the official SDK.
**Negative:** a migration of the gateway's schemas/auth to the SDK's shapes — contained to
`integrations/a2a/*`.

---

## ADR-084 — AG-UI adoption for dashboard streaming (Pydantic AI native)

| Field | Value |
|-------|-------|
| Status | proposed |
| Date | 2026-07-10 |
| Relates to | CLAUDE.md §3, §11 (db:2 pub/sub), §17 (frontend); REDESIGN.md §3.1 |
| Context | The dashboard receives agent activity via bespoke plumbing: Kafka → Redis pub/sub (db:2) → Litestar WebSocket. **AG-UI** is an emerging, framework-backed standard for exactly this agent→UI event stream, and **Pydantic AI supports it natively** — making it the lowest-friction new standard NEXUS could add. |

### Decision

Pilot **AG-UI** on the dashboard as the agent→UI streaming protocol, using Pydantic AI's native support.
Run it alongside the existing WebSocket path first; if the pilot succeeds, AG-UI standardizes (and can
retire) the bespoke streaming glue for the frontend layer. Pairs with the React 18→19 modernization.

### Alternatives rejected

- **Keep the bespoke Kafka→Redis→WebSocket stack** — works but is non-standard and reinvents a solved problem.
- **Build a custom SSE protocol** — more code, no ecosystem, no framework support.

### Consequences

**Positive:** a standard, framework-native UI transport; less custom frontend/streaming code.
**Negative:** AG-UI is younger and more vendor-driven (CopilotKit) than MCP/A2A — piloted behind the
existing path, not a hard cutover.

---

## ADR-085 — MCP auth modernization — OAuth/OIDC + PKCE + CIMD

| Field | Value |
|-------|-------|
| Status | proposed |
| Date | 2026-07-10 |
| Relates to | CLAUDE.md §8; REDESIGN.md §3.1; ADR-002 |
| Context | MCP's 2025-11 spec overhauled authorization: OAuth 2.0/OIDC alignment, **mandatory PKCE**, `iss` validation (RFC 9207), and **CIMD** (OAuth Client ID Metadata Documents) URL-based client registration replacing fragile Dynamic Client Registration. NEXUS integrates MCP as a local Python package today, so direct exposure is low — but any MCP-over-HTTP to an external server must use the new model. |

### Decision

Align NEXUS's MCP integration to the 2025-11 auth model (OAuth/OIDC, mandatory PKCE, `iss` validation,
CIMD client registration) **before** NEXUS speaks MCP over HTTP to any external server. While MCP remains a
local package, this is a readiness/documentation item; it becomes blocking at the first remote MCP server.

### Alternatives rejected

- **Ignore until needed** — invites a rushed, insecure integration under deadline when a remote MCP server appears.
- **Build a custom OAuth proxy** — CIMD's URL-based registration specifically removes the need for proxies.

### Consequences

**Positive:** remote-MCP-ready with standards-aligned auth; no proxy required. **Negative:** work is
partly speculative while MCP stays local — scoped as readiness, not immediate rewrite.

---

## ADR-086 — Supersede ADR-014 — Pydantic AI 1.x (unlocks `Agent.iter()`)

| Field | Value |
|-------|-------|
| Status | proposed |
| Date | 2026-07-10 |
| Relates to | CLAUDE.md §5; REDESIGN.md §6; ADR-001, ADR-079 |
| Supersedes | ADR-014 (on acceptance) |
| Context | ADR-014 recorded pinning `pydantic-ai 0.5.x` with `anthropic <0.83.0` to work around an `UserLocation`/`BetaUserLocationParam` import break. But `pyproject.toml` has since moved to `pydantic-ai >=1.56.0,<2.0` — the ADR is stale and no longer describes reality. Pydantic AI v1 also ships `Agent.iter()`/`AgentRun.next()`, the exact API the Stage-2 harness (ADR-079) depends on. |

### Decision

Supersede ADR-014. Record that NEXUS runs **Pydantic AI 1.x** (`>=1.56,<2.0`) with the current `anthropic`
ceiling pin, and that `Agent.iter()` is the supported mechanism for owning the inference loop. Document the
dependency-refresh pass (revisit pre-1.0 pins on `aiokafka`, `taskiq`; keep the `anthropic` ceiling pin
with its rationale).

### Alternatives rejected

- **Leave ADR-014 as-is** — actively misleading; future agents would re-pin to 0.5.x and break the harness plan.
- **Downgrade code to match ADR-014** — regresses off a working 1.x baseline and forfeits `Agent.iter()`.

### Consequences

**Positive:** the ADR record matches the code; the Stage-2 harness has a documented, supported API.
**Negative:** none material — this is reconciliation of an already-shipped reality.

---

## ADR-087 — "Co" personal-assistant persona over the CEO orchestrator

| Field | Value |
|-------|-------|
| Status | proposed |
| Date | 2026-07-12 |
| Relates to | CLAUDE.md §7; ASSISTANT.md §4.4; ADR-003 |
| Context | NEXUS is being repurposed as the owner's personal assistant fronted by a single orchestrator, "Co." The CEO agent (`agents/ceo.py`) already plans → decomposes → delegates → aggregates with a parent-task response loopback — i.e. it is already the central orchestrator. Introducing a distinct "Co" role would require a new `AgentRole` enum value and a custom-role runtime (which doesn't exist — `build_agent()` hard-fails on non-enum roles). |

### Decision

Add "Co" as a **persona over the existing CEO orchestrator**, not a new role: reframe the CEO system
prompt as a personal chief-of-staff and surface the name "Co" in the seed and UI. The role enum, routing
topics, and result-consumer loopback are unchanged. Add a **`PERSONAL_MODE`** flag that, with the existing
`NEXUS_SEED_DEMO` default workspace/user, auto-scopes every request to the single owner's workspace
(removing the multi-tenant JWT requirement in `api/tasks.py::_require_workspace_id`).

### Alternatives rejected

- **New dedicated `co` role above the CEO** — needs the custom-role runtime + a second orchestration layer; duplicates the CEO for no functional gain.
- **Rename CEO → Co everywhere** — churns seeds, prompts, tests, and migrations for a cosmetic change.

### Consequences

**Positive:** the personal-assistant framing ships with zero role/runtime churn and full reuse of the
orchestration pipeline. **Negative:** internal artifacts still say "CEO" (role value, topics); the persona
layer must map CEO↔Co in the UI. Custom user-defined agents remain blocked until the Phase-C custom-role runtime.

---

## ADR-088 — VoiceFactory — provider-agnostic STT/TTS (browser/cloud/local)

| Field | Value |
|-------|-------|
| Status | proposed |
| Date | 2026-07-12 |
| Relates to | CLAUDE.md §6; ASSISTANT.md §4.2; ADR-017 (ModelFactory pattern) |
| Context | The assistant needs voice input (STT) and voice output (TTS). None exists today. The owner wants all three backend styles available — browser-native (zero cost), cloud (best quality), and local (private) — rather than committing to one. |

### Decision

Add `core/voice/` with a **`VoiceFactory`** mirroring `core/llm/factory.py`'s prefix-registry pattern:
`STTProvider` and `TTSProvider` protocols, concrete backends selected by `VOICE_STT_BACKEND` /
`VOICE_TTS_BACKEND` settings — **browser** (Web Speech API, client-side, default), **cloud** (Whisper/Deepgram
STT; ElevenLabs/OpenAI/Google TTS), **local** (faster-whisper STT; Piper TTS). Endpoints `api/voice.py`:
`POST /api/voice/transcribe` and `POST /api/voice/speak`, invoked only for non-browser backends. Voice code
never names a provider directly — same isolation rule as the LLM ModelFactory.

### Alternatives rejected

- **Commit to one cloud vendor** — cost + privacy lock-in; the owner explicitly wanted all three.
- **Browser-only** — free and simplest but inconsistent voices/quality across browsers and no server-side TTS for automation.
- **Bolt STT/TTS into agent code** — violates the provider-isolation rule and can't be swapped per deployment.

### Consequences

**Positive:** voice becomes a config flag; MVP ships on the free browser backend while cloud/local drop in
unchanged. **Negative:** three backends to test; audio format normalization (webm/opus ↔ wav) lives in the factory.

---

## ADR-089 — User file-upload endpoint + `attachments` table

| Field | Value |
|-------|-------|
| Status | proposed |
| Date | 2026-07-12 |
| Relates to | CLAUDE.md §12, §15; ASSISTANT.md §4.1; ADR-090 |
| Context | Task input is text-only (`CreateTaskRequest.instruction: str`); there is no multipart upload route (`workspace_files.py` is read-only). A personal assistant must accept images and documents from the user. |

### Decision

Add `api/uploads.py` — `POST /api/uploads` (multipart; `python-multipart` is already transitive via
`litestar[standard]`). Persist bytes via the git-backed `core/workspace/storage.py::write_file` (already
accepts `bytes`) or a local object dir, and return an `AttachmentRef`. New **`attachments`** table (id, mime,
size, storage path, parsed-text ref, `task_id`/`trace_id` link) via Alembic migration 016. Extend
`CreateTaskRequest` with `attachments: list[AttachmentRef]`; `AgentBase._load_memory` loads attachment text
into task context.

### Alternatives rejected

- **Base64 in the task JSON** — bloats Kafka messages and the DB; breaks the small-envelope model.
- **Reuse `workspace_files` write path directly** — that path is git-commit-per-file (agent/workspace semantics), too heavy for arbitrary user attachments.

### Consequences

**Positive:** a single ingress for all user files, linked to tasks for audit. **Negative:** introduces
binary storage lifecycle (retention, cleanup) — deferred to Phase C; MVP keeps files in the workspace store.

---

## ADR-090 — Document ingestion (PDF/Word/Excel/Parquet) via `core/ingest`

| Field | Value |
|-------|-------|
| Status | proposed |
| Date | 2026-07-12 |
| Relates to | CLAUDE.md §8; ASSISTANT.md §4.1; ADR-089 |
| Context | No document parsing exists — files are only readable as raw UTF-8 text or sent whole to a vision model. The assistant must extract text/tables from PDF, Word, Excel, CSV, and Parquet to feed agents. |

### Decision

Add `core/ingest/` plus a `tool_read_document` tool (registered in `tools/adapter.py` + `registry.py`).
Parsers: PDF (**pypdf** / **PyMuPDF**), Word (**python-docx**), Excel (**openpyxl**), CSV/Parquet
(**pandas + pyarrow**). Output = normalized markdown + extracted tables. Large documents are chunked and
summarized via the redesign's `ContextAssembler` before entering agent context. Parsing runs at
upload/ingest time; parsed text is cached on the `attachments` row.

### Alternatives rejected

- **`unstructured` mega-library** — heavy dependency tree + native builds; overkill for the core formats.
- **LLM-only extraction (send whole file to a vision model)** — costly, lossy for tables/spreadsheets, and useless for Parquet.
- **Parse lazily at agent runtime** — repeats work per subtask and blocks the agent loop on I/O.

### Consequences

**Positive:** deterministic, cheap, offline-capable extraction with table fidelity for spreadsheets/Parquet.
**Negative:** adds data-libs (pandas/pyarrow) to the backend image; scanned-PDF OCR is out of scope for MVP.

---

## ADR-091 — HTML presentation output — typed `presentation` field, sanitized

| Field | Value |
|-------|-------|
| Status | proposed |
| Date | 2026-07-12 |
| Relates to | CLAUDE.md §10; ASSISTANT.md §4.3; ADR-084 (AG-UI) |
| Context | Task results are a plain JSON dict; there is no rich/HTML output. The owner wants Co to present results as HTML (reports, tables, charts) and to be read aloud. |

### Decision

Extend the task result envelope with a typed **`presentation`** field:
`{ format: "html"|"markdown"|"mermaid", content, speech_text }`. Writer/Co produces the artifact;
HTML is **sanitized server-side** (nh3/bleach; strip scripts/handlers, allow-list tags/attrs) before
publishing to `TaskResponse.output.presentation` and the WebSocket stream. `speech_text` is the plain-text
summary handed to `VoiceFactory` TTS. Rendering in the frontend uses a sandboxed container.

### Alternatives rejected

- **Return raw HTML unsanitized** — stored-XSS risk on render.
- **Markdown only** — insufficient for charts/rich layout the owner asked for.
- **Client-only rendering with no server sanitization** — pushes the security boundary into the browser; sanitize at the source instead.

### Consequences

**Positive:** rich, safe presentation + a clean hook for TTS; composes with the AG-UI pilot (ADR-084).
**Negative:** a sanitization allow-list to maintain; interactive JS in results is intentionally not supported.

---

## ADR-092 — React Flow for the Co DAG canvas

| Field | Value |
|-------|-------|
| Status | proposed |
| Date | 2026-07-12 |
| Relates to | CLAUDE.md §17; ASSISTANT.md §2.1 |
| Context | The front-end needs a single central "Co" node that expands into a live-animated DAG of agents (nodes show idle/thinking/tool-calling; edges animate on delegation), at tens–low-hundreds of nodes with premium custom branded node design. No graph engine is installed today. |

### Decision

Adopt **React Flow (`@xyflow/react`)** as the graph engine. Rationale (from a surveyed comparison): it
renders **React-component nodes**, so Tailwind styling and the existing Zustand `agentEventStore` live state
work natively (React Flow itself uses Zustand internally); it ships built-in animated edges, pan/zoom,
expand/collapse, and dagre/elk auto-layout; it is MIT (all features free) and the best-maintained option.
At NEXUS node counts it is nowhere near its DOM performance ceiling. New `components/co/CoCanvas.tsx` with
`CoNode`/`AgentNode` types bound to the event store.

### Alternatives rejected

- **tldraw SDK** — highest custom-design ceiling but a paid commercial license and no built-in DAG layout (kept as a premium alternative).
- **Reaflow** — React nodes + built-in ELK, but smaller community / slower cadence.
- **WebGL engines (Sigma/Reagraph/Cosmograph)** — for 1k–1M nodes; can't render custom React nodes — a future escape hatch, not MVP.
- **Cytoscape/GoJS/JointJS** — Canvas/SVG-template nodes (not React components), fighting the Tailwind custom-design workflow; GoJS/JointJS+ also carry license cost.

### Consequences

**Positive:** canonical "expandable orchestrator → live agent DAG" pattern, native to the React+Tailwind+Zustand
stack, MIT. **Negative:** auto-layout is bring-your-own (add dagre/elk); a WebGL migration would be needed only
if the graph ever exceeds ~1–2k live nodes.

---

## ADR-093 — Frontend modernization — React 19 + Compiler, Tailwind v4, Motion

| Field | Value |
|-------|-------|
| Status | proposed |
| Date | 2026-07-12 |
| Relates to | CLAUDE.md §4, §17; ASSISTANT.md §2.2; ADR-005 (shadcn/ui) |
| Context | The owner asked for a modern, best-design frontend. A full reframework (SolidJS/Svelte/Next) was evaluated: it costs ~4–16 weeks, degrades AI-assisted coding output, and discards the existing live event store + hooks — for marginal runtime gains a WebSocket assistant UI won't perceive. |

### Decision

**Stay on React + Vite; modernize in place.** Upgrade **React 18 → 19 + React Compiler** (auto-memoization
suits a high-churn WebSocket UI; codemod-assisted), **Tailwind 3 → v4** (CSS-first `@theme`, ~100× faster
incremental builds), add **Motion** (ex-Framer Motion) + **AutoAnimate** for transitions/live lists, keep
**shadcn/ui** now riding on **Base UI** plus **React Aria** for hard-a11y widgets, and use **GSAP /
Aceternity / Magic UI** surgically for the Co hero only. **React Three Fiber + drei** is an optional,
code-split 3D central-node hero. Keep **Vite + TanStack Query + Zustand**.

### Alternatives rejected

- **Reframework to SolidJS / Svelte 5 / Qwik** — 4–16 week rewrite, smaller ecosystem, worse AI-assist, discards the live event store; benefit is marginal perf not needed here.
- **Next.js 15 (App Router/RSC)** — RSC benefits the shell/SEO an internal real-time app doesn't need and adds a new bug class.
- **Marketing kits (Aceternity/Magic UI) for working surfaces** — bundle-size/accessibility overkill; reserve for the hero.

### Consequences

**Positive:** a modern, animated, accessible design system built on the existing investment; React Compiler
removes most manual memoization. **Negative:** Tailwind v4 and React 19 are breaking upgrades (codemods cover
most); marketing-kit effects must be quarantined to the hero to protect bundle size and a11y.

---

## ADR-094 — DravenIQ company system as the first product

**Date:** 2026-10-05\
**Status:** proposed\
**Direction confirmed by:** Santapong during the Nexus design discussion\
**Relates to:** ADR-009, ADR-048, ADR-069, ADR-087; [SDD §§1–8](sdd/NEXUS_SDD_v0.2.md#1-purpose-and-product-direction)\
**Supersession:** none activated; reframes ADR-087's personal-assistant direction for the company program.

### Context

The owner wants Nexus to operate DravenIQ across management, strategy, engineering, presentation, support and operations, with close initial supervision and periodic board review later. Existing agent-owned memory and chat orchestration do not establish shared evidence-backed company operation.

### Decision

Design an internal Company Brain + management + Action Harness. Use typed PostgreSQL entities, temporal claims with provenance, decisions and commitments, a separate work dependency DAG, and one permission-aware ContextAssembler. Co becomes the owner's entry point into company work. Prove StockFlow customer readiness first. Keep the native builder inside Nexus as selected by the owner.

### Alternatives considered

- A personal assistant is useful as an interface but does not own company goals, commitments and departmental outcomes.
- Immediate SaaS/marketplace scope adds external tenancy and commercial requirements before internal operation is proven.
- Neo4j/Graphiti as the initial database adds infrastructure before measured traversal demands justify it; typed PostgreSQL relationships are sufficient for the first acceptance pack.

### Consequences

Existing PostgreSQL/RLS investment is retained. The new company/domain contracts require explicit migration from legacy workspaces, source provenance and evaluation fixtures. Graphiti remains a deferred measured option. A document or generated graph is not proof of operation. Track implementation in BACKLOG-068, 070, 071 and 073.

---

## ADR-095 — One DBOS execution engine for the company profile

**Date:** 2026-10-05\
**Status:** proposed\
**Relates to:** ADR-006–009, ADR-016, ADR-038, ADR-065, ADR-076–081; [SDD §9](sdd/NEXUS_SDD_v0.2.md#9-harness-engineering-and-durable-execution)\
**Supersession:** on validated company-profile cutover, replaces overlapping legacy queue/transport orchestration and the proposed DBOS-plus-Temporal split for that profile. Legacy paths retain their history until migrated.

### Context

The first host is a shared Pi. Kafka, Redis, Taskiq and optional Temporal divide execution ownership and add recovery boundaries. The reviewed Temporal class is rejected by the installed SDK; its presence does not prove durability. A small company profile needs one execution owner.

### Decision

Use DBOS 3.2.0 with dedicated PostgreSQL for the proposed profile, subject to M1 compatibility/recovery validation. Persist business state and continuation enqueue atomically in the same database. Use stable workflow/model IDs, compatible version draining, durable application deduplication, fenced ownership, explicit effect intent and receipt records. Split approval waiting into committed, capacity-releasing segments.

External actions require provider idempotency or reconciliation. Keep `outcome_unknown` when an effect cannot be confirmed; do not claim universally exactly-once external execution. Redis locks/seen markers and queue deduplication cannot replace the ledger.

### Alternatives considered

- Retaining all four legacy systems spreads ownership across unproven boundaries and increases Pi operations cost.
- DBOS for short tasks plus Temporal for long tasks requires two execution engines without a demonstrated first-pilot requirement.
- A generic MessageBus/broker PoC does not itself solve durable actions, exact approval or uncertain effects.

### Consequences

DBOS replay and transactional integration must be proven with real PostgreSQL/process-kill tests. PostgreSQL becomes an operationally important execution dependency; backup and upgrade discipline are mandatory. Legacy services are removed from the new profile only after migration gates, never merely because this ADR is written. BACKLOG-069 and 074 own delivery. References: [DBOS outbox](https://docs.dbos.dev/python/examples/outbox), [queues](https://docs.dbos.dev/python/tutorials/queue-tutorial), [upgrades](https://docs.dbos.dev/python/tutorials/upgrading-workflows).

---

## ADR-096 — Governed Pydantic AI 2.x harness and segmented approval

**Date:** 2026-10-05\
**Status:** proposed\
**Relates to:** ADR-001, ADR-014, ADR-019, ADR-022, ADR-024, ADR-028, ADR-057, ADR-061, ADR-073, ADR-079, ADR-080, ADR-086; [SDD §§8–10](sdd/NEXUS_SDD_v0.2.md#8-context-engineering)\
**Supersession:** on M1 validation, updates the company-profile runtime pin, retry/limit policy and harness design; prior runtime records remain historical.

### Context

The baseline locks Pydantic AI 1.107.1. Context binding, pending approval transactions and optional QA fail-open behavior are not resolved by passing unit checks. Pydantic AI 2.x changes hooks/capabilities and API families, so an untested upgrade is insufficient.

### Decision

Target `pydantic-ai-slim[openai,google,dbos]==2.54.0` with DBOS 3.2.0 after a compatibility spike. Register durability capabilities before launch, checkpoint custom consequential I/O explicitly, and keep all adapters behind one typed harness. The shared stages validate context, authority, cost, action parameters and source preconditions before execution; independent verification follows.

Commit pending approval before ending a segment. Approval binds a canonical proposal revision/hash, approver, expiry and single-use identity; a new segment rechecks policy/resource/budget at execution. Limits default to 12 model requests, 20 tool attempts, two rework rounds and two plan revisions per logical work item across retries, children and segments. Failure or uncertainty never defaults to approval.

### Alternatives considered

- Per-tool optional approval wrappers leave mutation paths inconsistent and cannot prove complete policy coverage.
- Blocking the only execution queue slot while waiting for the owner starves unrelated work.
- Similarity-only loop termination can stop valid empty rounds or allow boundedness to depend on model behavior; counters and explicit conditions remain authoritative.

### Consequences

Two-session approval tests, adapter conformance, stable serialization boundaries and crash/replay evidence are M1 gates. Plans and old approvals cannot create standing authority automatically. The dependency dry run resolved, but no upgraded runtime is yet verified. BACKLOG-069 owns implementation. References: [Pydantic AI migration](https://pydantic.dev/docs/ai/overview/migration/), [DBOS integration](https://pydantic.dev/docs/ai/capabilities/durable_execution/dbos/).

---

## ADR-097 — Native bounded Pi builder and portable deployment

**Date:** 2026-10-05\
**Status:** proposed\
**Choices confirmed by:** Santapong: native Nexus builder, Pi first, one bounded worker\
**Relates to:** ADR-031, ADR-062; [SDD §§12 and 15](sdd/NEXUS_SDD_v0.2.md#12-native-builder-and-tool-harness)\
**Supersession:** E2B is no longer the primary sandbox for this proposed company profile when M4 activates; optional legacy/cloud use is not removed by this document.

### Context

The owner selected engineering inside Nexus rather than Accretion delegation. The Pi is ARM64 with 16 GiB RAM and existing services. Docker is present; rootless Podman is not installed. The inspected service-data path is root-backed, so an independent backup is still needed.

### Decision

Use a restricted runner and one rootless Podman sandbox, default 2 CPUs/4 GiB plus explicit time/disk/output quotas. Jobs use approved committed revisions, isolated workspaces and narrow mounts/network policy. Keep model/database credentials and production repositories outside jobs. Capture commands, diffs and artifacts for independent verification. Prepare plain-Git review packages; GitHub-only PR creation remains a manual review step until an authorized connector is designed.

Design a private dedicated PostgreSQL/profile, independent encrypted backup and portable cloud/VPS deployment. Install/deploy actions occur only in the separately authorized deployment stage.

### Alternatives considered

- Accretion delegation conflicts with the selected first native builder direction; a future reviewed adapter remains possible.
- A cloud-only E2B dependency bypasses the owner's Pi-first choice and adds initial operating cost.
- Privileged host builds with owner-home/production mounts defeat the intended isolation boundary.

### Consequences

ARM64 toolchains, Playwright, representative StockFlow builds and resource fit require live proof. Rootless Podman is a proposed prerequisite, not a claim of an installed service or hardened hostile tenancy. Resource-heavy jobs block or move through a revised approved hosting plan. BACKLOG-072 and 074 own delivery.

---

## ADR-098 — Evaluated multi-provider routing and atomic cost reservations

**Date:** 2026-10-05\
**Status:** proposed\
**Choices confirmed by:** Santapong: multiple providers and US$5/day initial cap\
**Relates to:** ADR-017–019, ADR-043, ADR-053–055; [SDD §11](sdd/NEXUS_SDD_v0.2.md#11-model-methods-routing-and-cost-control)\
**Supersession:** none activated; refines company-profile routing and accounting after conformance tests.

### Context

Provider availability and model capabilities differ. Historical prefixes and prices cannot be assumed valid after an SDK upgrade. Concurrent workers, retries and uncertain billing need a shared allowance rather than independent per-agent estimates.

### Decision

Register explicit model IDs/API families, capabilities, data-policy eligibility, dated price versions and evaluation evidence. Define Reasoning, Engineering, Routine, Verification and Embeddings profiles. Filter eligible models and select the lowest estimated cost with stable tie priority; use at most two registered fallback alternatives under unchanged policy and counters.

Atomically reserve estimated upper-bound call cost against the Asia/Bangkok daily ledger and work lineage before calling. Proposed work cap is US$1; the owner-confirmed company cap is US$5/day. Include embeddings/failures/rework, hold uncertain charges and stop paid routing when pricing is unsupported. A new day never resets a work item's request/tool limits.

### Alternatives considered

- One provider conflicts with the selected provider-neutral direction.
- Automatic cheapest-model discovery risks adopting unevaluated capabilities/prices and silently weakening policy.
- Post-hoc alerts alone cannot prevent concurrent over-allocation.

### Consequences

Conformance and budget-race tests are M1 gates. Provider billing remains externally determined; local reservations are not a promise of exact final invoice totals. No model or paid provider is activated by this documentation change. BACKLOG-069 owns delivery.

---

## ADR-099 — Owner oversight, dashboard/email and deferred Meta Harness

**Date:** 2026-10-05\
**Status:** proposed\
**Choices confirmed by:** Santapong: internal work/drafts first, dashboard/email, defer self-improvement\
**Relates to:** ADR-024, ADR-052, ADR-056, ADR-087, ADR-091, ADR-092; [SDD §§2, 13 and 18](sdd/NEXUS_SDD_v0.2.md#2-company-organization-and-authority)\
**Supersession:** none activated; company-profile scheduling/notification authority becomes explicit at M3/M5.

### Context

The owner expects increasingly independent operation and meaningful reports. The current email adapter is unconfigured. Automatic prompt activation or self-assessed authority expansion would contradict the selected initial scope.

### Decision

Use Supervised, Delegated and Board oversight policies with explicit owner-approved transitions. Show goals, decisions, work, verified outcomes and exceptions in the dashboard. Use a durable notification ledger and configured Resend sender/allowlisted owner for meaningful alerts and digests, with delivery reconciliation. Approval links require authenticated dashboard decisions and cannot grant authority by email reply.

Require at least 20 reviewed completed work items, recovery drills and no unresolved unauthorized/missing outcomes before an owner decision on Delegated mode. Board oversight follows stable approved cycles. Collect versioned feedback, but defer Meta Harness optimization, prompt promotion and fine-tuning. Future promotion needs frozen offline evaluation plus explicit owner review.

### Alternatives considered

- Notifying every idle cycle creates noise without new company information.
- Provider acceptance alone cannot establish delivery or long-term deduplication.
- Automatic self-improvement and autonomy promotion conflict with the owner's chosen first-period supervision and deferral.

### Consequences

Notification configuration/live proof and authority-delta review remain delivery gates. Customer messaging and deployment stay separately governed actions. BACKLOG-071, 073, 074 and deferred 075 own delivery. Reference: [Resend idempotency retention](https://resend.com/docs/dashboard/emails/idempotency-keys).

---

## ADR-100 — Standalone company contracts and PostgreSQL approval/cost journal

**Date:** 2026-10-13
**Status:** accepted for the initial implementation slice
**Decided by:** Codex under Santapong's request to implement the company-system plan
**Relates to:** ADR-094–099; BACKLOG-068–069

### Context

The owner authorized implementation and requested feature/time estimates. The existing runtime remains at July HEAD; a simultaneous full SDK/engine/API cutover would obscure the first proof of exact approvals and cost persistence.

### Decision

Implement strict versioned company contracts, validated work DAGs, source/context manifests, server-owned canonical action snapshots, exact approval policy, fail-closed lifecycle and serializable loop counters. Freeze synthetic Brain questions and the StockFlow readiness checklist before retrieval/prompt optimization.

Add a standalone PostgreSQL journal via additive migration 017. Company-scoped row policies, immutable action/decision snapshots, single-use consumption, persisted owner pause, and daily/work cost holds protect the foundation. Serialize mutations through a company-row transaction lock for the one-worker pilot. Retain holds for unknown billing and reconcile actual cost idempotently; record real cost even if it exceeds an earlier estimate.

Keep this component unmounted from legacy endpoints and agents. Its input scope is trusted internal context, not a self-issued external authority token. DBOS integration, request authentication, standing department grants, fenced effect execution, parent quotas and live provider conformance remain M1 work. No dependency or production schema cutover occurs in this slice.

### Alternatives considered

- An in-memory approval or cost fixture cannot prove cross-session visibility or concurrency.
- Upgrading every engine and provider before freezing business contracts makes regression causes harder to isolate.
- Fine-grained budget locks offer more throughput, but increase lock-order complexity before the single Pi worker needs it.

### Consequences

Real disposable PostgreSQL tests must prove separate sessions, competing consumers, spend races, persisted pause, immutable snapshots, RLS and unknown-cost reconciliation. The migration and its metadata must stay consistent. Coarse locking limits per-company throughput; partition lock ownership when measured concurrency requires it. These tests do not prove DBOS replay, complete HTTP authorization or external exactly-once effects. The full runtime gate remains open.

---

## ADR-101 — Independent clean company-profile migration lineage

**Date:** 2026-10-13
**Status:** accepted for release implementation
**Decided by:** root after the release-planner's independent source review and real migration preflight
**Relates to:** ADR-095, ADR-100; release execution plan

### Context

Fresh 001–017 replay on disposable PostgreSQL 17 fails at 003: a VARCHAR task foreign key references a UUID primary key. Further source defects include 006 policies using missing workspace columns and additional incompatible identity keys. A later revision cannot repair an earlier revision that never executes. Existing merged migrations must remain immutable; evolving ORM create_all plus stamp would not install migration-managed security/schema behavior.

### Decision

Use `alembic_company.ini`, `company_alembic/`, and `company_alembic_version` for the new profile. Install an explicit reviewed baseline of company-owned directory, registered-work, journal, quota and later execution tables with consistent native UUID FKs, RLS and immutable identities. Apply future additive company revisions normally. Scope autogeneration to owned objects and reject unversioned conflicting company tables.

Preserve legacy 001–016 bytes and their version history. Migration 017's standalone evidence remains valid within its recorded scope, but the supervised company profile uses the independent baseline. Legacy tables are not implicitly imported; an explicit idempotent import preserves source IDs/provenance and does not promote seen markers or old approvals to verified completion/authority. The clean profile does not start legacy Kafka/Redis agents or require their migration chain.

### Alternatives considered

- Repairing old files rewrites published history and hides uncertainty about existing deployments.
- A late 018 cannot be reached after the 003 failure.
- Intercepting/reinterpreting historical operations creates a second implicit migration language.
- Whole-application squash is larger than the supervised release and needs a full RLS/partition/FK inventory.
- ORM create_all plus stamp falsely certifies absent security behavior and is rejected.

### Consequences

Prove clean install, idempotent upgrade, metadata/FK consistency, non-superuser RLS and downgrade on disposable DBs; also prove additive preservation of unrelated legacy sentinel data/version history. Legacy fresh-replay defects remain open. Real import needs a read-only source snapshot and separate evidence before production activation. Profile configuration must select its database explicitly; no silent fallback to the legacy URL.

References: [Alembic independent bases](https://alembic.sqlalchemy.org/en/latest/branches.html#working-with-multiple-bases), [version table configuration](https://alembic.sqlalchemy.org/en/latest/api/runtime.html), [stamp](https://alembic.sqlalchemy.org/en/latest/api/commands.html#alembic.command.stamp).

---

## ADR-102 — Pin the experimentally verified Pydantic AI 2.54 and DBOS 3.2 runtime

**Date:** 2026-10-13
**Status:** accepted for implementation after isolated compatibility/recovery proof
**Relates to:** ADR-095, ADR-096, ADR-100; SDK spike evidence

### Context

The selected SDK combination now passes an actual 15-assertion PostgreSQL process-kill/restart test, registered model/tool execution, one-slot approval segmentation, version isolation and transactional enqueue. This is stronger than dependency resolution, but does not establish whole-application compatibility or live provider behavior.

### Decision

Pin Pydantic AI 2.54.0, DBOS 3.2.0 and Pydantic 2.13.4 with the validated API/ORM versions; update the lockfile. Preserve legacy chat API semantics through explicit OpenAIChatModel; support Responses only through an explicit binding. Replace removed Google aliases. Migrate usage property/input-output token names with regression tests so a SDK error cannot fabricate zero cost.

Register named agents/steps before DBOS launch, queues after launch through the actual pinned async API, and pin application/executor recovery policy. Custom I/O steps remain explicit. Keep portable application contracts separate from native trusted DBOS agent history. Paid provider conformance and governed effect replay remain gates.

### Consequences

Run the whole relevant unit/type/lint regression against the new lockfile and retain isolated spike evidence. Resolve compatibility failures before activating the company profile. The successful test reused completed model/tool checkpoints; interrupted steps may rerun, so external idempotency/reconciliation remains required.

Evidence: `/mnt/data/nexus-implementation-evidence-2026-10-13/dbos-spike/README.md` and acceptance result. Primary reference: [Pydantic migration map](https://pydantic.dev/docs/ai/overview/migration/).

---

## ADR-103 — Registered company authority, lifetime quotas and principal-bound effects

**Status:** accepted
**Date:** 2026-10-14
**Context:** user-authorized supervised company implementation and milestone integration review; complements target ADR-095/096. This accepts a local implementation boundary, not production or Board activation.

### Decision

Derive company/work scope from signed identity and current directory/membership. Register immutable work and permanently partition parent USD and per-kind attempt slices. CompanyControl is the first lock. Owner controls use a distinct operation identity before work exists; owner READ can audit inactive work while new execution remains denied.

Exact approvals and explicit standing capabilities authorize immutable action snapshots once. Standing grants bind owner/actor/work, owner-declared plan/charter revisions, exact reviewed internal tool/resource versions, expiry and price/policy; model/extracted content never creates grants. Persist which grant authorized an action. At effects, recheck current authority, resource state, owner pause, counters, lease principal/fence and actual Bangkok-day allowance. Unknown effects and billing retain holds until evidence-based reconciliation.

Commit permanent action-to-segment dispatch and DBOS SQL enqueue together with consumed authority/source/cost hold. A new segment/run ID cannot create allowance or repeat authorization. Trusted per-request validators compose under the same transaction before intent; no network I/O or serialized callables are allowed there.

### Consequences and evidence

Company001–006 extends the independent lineage with native scoped FKs, RLS, immutable snapshots/history, monotone counters/fences and explicit lease principal. Upgrading a populated installation requires drained workers and refuses live leases; expired old owners are fenced/unknown rather than assumed current. Blocked work persists honestly; rollback deactivates blocked work instead of allowing an older worker to restart it.

Registered/control42PG, standing55unit+11PG, consumed standing5PG, exact/standing atomic queue/day12PG, runtime27PG, owner-reconcile/hook12PG, actual API16PG and clean/populated migration tests prove their individual offline boundaries. Counts overlap; whole final integration is tracked separately. Known-receipt cost-only evidence and persistent model gating are still being completed. Owner-declared plan/charter binding is not an M3 plan proof; candidates are not independent completed-work evidence.

---

## ADR-104 — One fresh non-retrying effect step for the first governed offline worker

**Status:** accepted
**Date:** 2026-10-14
**Context:** real SDK/DBOS spike showed replay of completed steps and possible repeat of interrupted I/O; caching a one-time permit independently would create unsafe recovery.

### Decision

Register a named portable-JSON company workflow and ordinary TestModel before DBOS launch; register its bounded single queue afterward. The first offline integration uses one non-retrying DBOS I/O step for fresh dispatch/lease/authority checks, committed intent/attempt, bounded fake invocation, saved result and receipt. Do not checkpoint permit=True as a reusable authorization token.

Protect/hash a command/proposal-bound output envelope before recording its receipt. After a real process kill, missing output remains unknown and produces no new model/tool call; a preserved result can be reconciled under a new fence without invoking again. Resource revisions come from the server registry, never echoed caller preconditions. Keep verifier candidates inconclusive/verifying until independent acceptance exists.

### Consequences and evidence

Nine initial worker cases (two contract + seven actual DBOS/process cases) cover exact/standing authority, three SIGKILL points, pause and stale-source denial. A subsequent seven-process-case c006 regression proves persistent blocked state and lease-principal compatibility. This is ordinary TestModel inside a durable effect step, not Pydantic durability-capability replay inside that governed path, live vendor conformance, receiver fencing or completed company operation. The separate SDK spike's replay result remains separately scoped.

Evidence: `/mnt/data/nexus-implementation-evidence-2026-10-13/company-worker/README.md`; source manifests record their checked versions. Workflow version/drain, ARM64 and live adapter gates remain.

---

## ADR-105 — Required per-request model gate and local schema/wire validation

**Status:** accepted
**Date:** 2026-10-14
**Context:** SDK usage defaults and multi-call/retry behavior cannot serve as price or attempt evidence. Native Model.request returns parts without full application schema/semantic validation.

### Decision

Use explicit OpenAI Responses and Google GenerateContent adapters for the new two-provider package; preserve legacy Chat behavior in its existing factory. Each governed call makes one SDK Model.request, with no Agent.run, SDK retries, implicit fallback or tool execution. A mandatory trusted authorizer binds the exact request/scope/action/attempt/catalog/price/reservation; it must implement persistent intent/counter/cost before wire I/O. Caller-declared input tokens alone cannot prove the reservation covers rendered text/tools/schema/SDK framing.

Validate actual provider wire model/usage before SDK default extraction; missing/malformed/unsupported counts produce unknown billing. Preserve supported known usage even when business output fails. Return function proposals; actual tools use a separate policy gate. Resolve secrets/endpoints only from server configuration and exclude them from serialized outputs, metadata and error logs.

Add jsonschema4.26.0 for bounded native/function schema validation plus its typing dependency. Canonicalize schemas, permit local pointer references only, forbid remote retrieval/cycles/oversized or nonfinite structures. Pydantic domain validation still enforces semantic invariants; a schema match alone cannot establish goal/authority/verification truth. [JSON Schema validation reference](https://python-jsonschema.readthedocs.io/en/stable/validate/).

### Consequences and evidence

Fifty-six actual-SDK/offline-HTTP cases prove two explicit families, one request, output caps, retries0/attempts1, missing wire usage/timeout/cancellation, native/function validation and credential exclusion. Coverage92.46% across four modules. No live model, price or alias is enabled. Persistent per-request authorizer/result envelopes and current input-estimator conformance are in progress; budgeted live activation remains separate.

---

## ADR-106 — Native permission-bound Brain provenance with separate execution authority

**Date:** 2026-10-14
**Status:** accepted for local implementation; release activation remains gated
**Relates to:** ADR-095/096/101/103/105; M2 integration checkpoint

### Decision

Use26 native company-scoped PostgreSQL tables in normal company008 for immutable
source/artifact/parse/evidence/claim/entity/relationship/derivation/event history,
with mutable heads, ACL generations and consumer cursors. Current signed
membership plus explicit resource grants and complete contributor intersection
filter candidates before rank, counts or traversal. Blob reads happen outside
the company lock; final publication rechecks current provenance and access.

The first retrieval recipe uses bounded simple FTS, exact IDs and closed typed
relationships. Vectors, reranking and Thai semantic search remain unqualified.
Server policy supplies source classification, authority and context byte limits.
Readonly rendering does not invent token allowance; model use still requires
M1's exact approved request/profile/recipe, full-input estimator and USD hold.

Model-derived claims/relationships remain proposed. Native budget/policy/work
references do not mutate their authoritative stores. A stored verification
candidate is representational, not completed work; verified_outcome and
source-report verified_by publication stay disabled until an independent trusted
publisher validates actual acceptance. Current entity endpoints conflict when
support becomes historical/stale; explicit history remains labelled.

### Consequences and evidence

The normal43-table company install/repeat/metadata/downgrade and actual restricted
ACL/SQL/SDK probes provide offline integration evidence. The original30 scorer
stays independent of its source-derived baseline; live model quality, full
business operation and release approval are separate gates. Company locks do not
freeze time: refresh distinct resource grants and exact/standing authority after
bounded preparation, before returning protected content or creating an intent.

See M2_INTEGRATION_2026-10-14.md and ERROR-051–054 for executed scope and fixes.

---

## ADR-107 — Supervised management contracts, stable procedure allowance and independent acceptance

**Date:** 2026-10-14
**Status:** Accepted for local supervised implementation; execution packages still being qualified

A goal has one non-executing procedure root. Approved plan revisions preserve
that root's lifetime USD and per-kind quota partitions. Initial approval uses no
revision attempt; later actual owner revisions consume bounded immutable
administrative events. Proposed plans and Brain statements confer no execution
or management authority. Charter/goals/mandate replacement preserves revoked
heads until an explicit current-version owner operation.

Verification is a separate approved child with actual receipt/protected evidence
bindings and a trusted publisher. Pure checks, verifier candidates and successful
effect receipts cannot satisfy independently accepted dependencies. Scope/source
permission and registered freshness must still hold at actual intents and result
publication. Native report loaders use actual signed readers and native ledgers;
no synthesized owner identity or caller-supplied verdict is accepted.

Normal company009 holds22 management tables; additive010 holds one immutable
scheduler receipt. Existing opaque company/consumer/recipe cursors use separate
Brain/control namespaces. Atomic dispatch identity is retained by M1; scheduler
scan records confer no call permit. Bounded due scans cover changes without a
sequenced outbox until their real emitters are integrated.

M3-A owner/schema review and normal profile tests are scoped evidence. Plan,
acceptance, event/dispatch, report/UI and the full offline workflow require their
own actual acceptance before activation. See MANAGEMENT_IMPLEMENTATION_PLAN.md.

---

<!-- New ADR entries go above this line, with the next ID number -->
<!-- Next ID: ADR-122 -->

---

*Last updated: 2026-10-14 (supervised company integration)*
*Next ADR ID: ADR-123*
*Company-program additions: six proposed ADRs (094–099); older statuses are preserved, not a runtime cutover claim.*
*Note: on acceptance, ADR-078 supersedes ADR-008 and ADR-086 supersedes ADR-014.*


## ADR-108 — Permanent owner notification ledger and separate native wake migration

**Date:** 2026-10-14
**Status:** accepted within the approved supervised company programme

Install the four immutable notification histories in normal014 with exact native
event/intent references and a deferred intent FK. A trusted M1 before-intent check
may bind one draft in the same transaction as the actual intent; ambiguity or
provider24h key expiry cannot create another local attempt. Provider acceptance,
delivery and financial reconciliation stay distinct. Delivery is disabled by
default and pure/mocked adapter output cannot confer a send permit.

Install new decision/block/cap/digest wakes separately in additive015 with actual
source emitters and explicit old-profile compatibility. Existing Brain readers
use the old six event kinds/columns; partially adding ORM columns while older
profiles are still supported would break those readers. Ledger validation and
native store work can proceed while015 is qualified. Both steps and every
required notification signal remain mandatory before NOTIFY-01 acceptance.

See NOTIFICATION_014_EVENT_PLAN.md and NOTIFICATION_LEDGER_CHECKPOINT_2026-10-14.md
for schema/effect boundaries, scoped actual evidence and remaining activation gates.

## ADR-109 — Qualified native event mapping preserves older physical profiles

**Date:** 2026-10-14
**Status:** accepted within the supervised company programme

Keep the original BrainEvent mapper's instrumented columns unchanged. Append
seven reviewed Core columns and exact constraints to its shared Table, then map
a separate NativeBrainEvent for full015 reads. Existing old-kind inserts explicitly
select original columns. New-kind writes and full reads first qualify the actual
physical columns and independent migration version. Partial schemas fail closed.

Adding nullable/deferred mapped attributes alone was rejected: generated ORM
INSERT/RETURNING or eager reads can reference columns absent from008/014. Actual
pinned SQLAlchemy2.0.51 old-profile event SELECT/INSERT/append/replay/consume proof
passes2PG;014 real ingestion passes separately. Full008 ingestion has an unrelated
pre-existing012 artifact classification read gap and is not claimed compatible.

Normal015 binds decision events to exact company/action/task, work events to
RegisteredWork, digest events to saved reports, and company cap events to actual
daily budgets. New kinds carry state hashes, never arbitrary body/owner authority.
Downgrade refuses existing new-kind events before removing their columns, retaining
durable evidence. Real source emitters, final privacy/time checks and delivery
remain separate required implementation gates.

## ADR-110 — Separate current model eligibility from immutable registrations

**Status:** accepted
**Date:** 2026-10-14

### Context
An actual next sibling plan denied after its offline registry eligibility expired.
Every existing child pins the original registry revision and permanent registration;
relabeling the registry or replacing those children would erase identity continuity.
Original positive observation dates cannot be silently extended.

### Decision
Allow bounded explicit server catalog ModelEligibilityObservation records pinned
to company, original registry revision/model ID and full original registration SHA.
Keep original registry bytes intact. Resolve only fresh health/profile evaluations,
retaining new observation/receipt identity and clocks. Current negative/stale/future
observations deny rather than falling back to the original positive observation.
No default observations, automatic refresh, allowance, authority or model call.
Current native admission and final notification/fact deadlines share the resolver.

### Consequences
Existing work, parent slices and registration hashes remain unchanged. Trusted
configuration must accompany genuine newly checked evidence; decoding an observation
is not evidence of checking a provider. Actual routine TestModel conformance cannot
prove live provider quality, code/reasoning or structured-output capability. Model
routing/client evidence integration remains separately qualified before use; no
observation silently changes a request's registered model/endpoint/price/schema.

## ADR-111 — Bounded authenticated operator backup envelope

**Status:** accepted
**Date:** 2026-10-14

### Context
The release requires matching encrypted database/artifact restore. A hash manifest
alone cannot authenticate a private recovery archive. The verified runtime already
contains cryptography49.0.0; PostgreSQL client/server is17.6. Production capture,
key custody and independent storage need separate actual operating evidence.

### Decision
Pin the existing cryptography version as a direct dependency. Use its AESGCM with
an externally supplied256-bit key and fresh96-bit nonce per envelope. Authenticate
format/version/length, verify tag before unpacking, and retain bounded ordinary ZIP
contents with complete typed dump/artifact SHA/length manifest. Initial packed/plain
limit256MiB rejects rather than truncates larger captures. Keys never enter bundle,
manifest, command line or logs. Restore writes only a new private empty tree after
all contents match; it never overwrites or normalizes unsafe paths.

### Evidence and consequences
[Version49 primary API](https://cryptography.io/en/49.0.0/hazmat/primitives/aead/)
and installed API signatures checked2026-10-14. Initial codec header arithmetic
failed roundtrip and was corrected to derive lengths from magic/nonce/length fields;
original failure retained. Local codec/path checks are not proof of capture
consistency, independent devices, production RPO/RTO or durable process recovery.
Direct pin does not change the already selected runtime package version; lock
metadata must be checked without upgrading the surrounding SDKs.

## ADR-112 — Explicit model-free mechanical engineering profiles

**Status:** accepted within the supervised implementation programme
**Date:** 2026-10-14

### Context
A fixed mechanical build/check recipe requires no model call. Requiring a model
evaluation for that job would confuse mechanical execution with evidence of LLM
coding ability. Existing routine text conformance cannot qualify engineering.

### Decision
Add default-empty server-configured native profiles, excluded from serialization
when empty. Pin company, canonical SHA of the exact original model catalog,
catalog revision, closed workflow/profile identity, recipe and builder tool tuples.
The initial native plan is exactly one author/verifier pair with seven engineering
criteria and one matching edge. Its non-executing procedure and all registered
ancestors retain zero model allowance, usage and delegation. Deny model tools and
attempt kinds; retain current charter, source, owner approval, lease and budget
gates. Ordinary LLM profiles keep their genuine current model evidence checks.
No registration schema, provider profile enum or generic runner changes are needed.

### Evidence and consequences
Root's isolated package passed 9 restricted normal015 PG cases and 1,501 units;
the combined gateway/native snapshot passed 1,514 units and strict types on 28
files. After application, unchanged native PG cases passed 9/26.94s. Independent
review verified all eight native source hashes and rejected an unselected
conflicting tuple. These are admission checks, not engineering acceptance.
Existing immutable registration rejected a test's attempted quota alteration;
the corrected test preserves that safeguard and a genuine publicly registered
positive ancestor separately demonstrates native denial. New private CSV work
still requires actual module regression, patch, independent process/protected
proof and recomputed acceptance. No live model quality, ARM64 or release claim
follows from these profiles. See NATIVE_ENGINEERING_PROFILE_PLAN.md.

## ADR-113 — Owner-bound same-source PostgreSQL/DBOS recovery qualification

**Status:** accepted for the operator-local qualification scope
**Date:** 2026-10-14

Use one actual exported PostgreSQL snapshot for the complete database/DBOS state
and registered immutable artifact inventory. Require current native owner pause,
quiescent leases and exact registered OS-process exit/wait witnesses before and
after staging; absence of leases alone is insufficient. An external key provider
seals the existing authenticated envelope. Descriptive metadata grants no authority.

Bind the owner transaction to the adapter's actual SOURCE DB/port/Unix transport
and live backend. A wrong supplied factory was reproduced and corrected without
an app-role privilege grant. Private asyncpg0.31 transport access is isolated and
fails closed when unsupported. Restore into the configured empty target with
single-transaction fail-on-error semantics and a new protected file tree. Never
rewrite stored workflow inputs or silently reconnect to the source on replay.

The amended actual pair2 drill passes26.67s: target executes the same workflow,
conserves the intent/one attempt/unknown cost, advances the fence, denies the old
lease and issues no new effect. Source fingerprints remain unchanged. Both pairs
and byte-verified artifacts are preserved. These tests require a live unchanged
source for authorization and comparison. Lost/changed-source or older-backup
recovery, independent storage/key custody, production service RTO and OPS02 remain
unqualified; they require a separate operator authority and operating design.

## ADR-114 — Explicit model-free owner notification admission

**Status:** accepted as an opt-in admission foundation
**Date:** 2026-10-14

A fixed owner notification send requires no LLM model health or evaluation.
Add a separate default-empty notification profile tuple pinned to company, exact
original registry digest/revision, fixed workflow/tool and configured target.
Keep the engineering pair closed and ordinary LLM evidence gates unchanged.
Validate all original tuples before selection; derived model views exclude
unrelated tuples only after validation. Initial notification plans contain one
sender/no verifier edge and zero models through the actual immutable ancestry.
Actual execution additionally requires work.actor_id equal current control.owner_id.
Current member/source/charter/exact approval/lease/budget/recipient/digest checks
remain; standing notification sends are not added.

Move Catalog/NamedResource declarations into a focused module with old public
imports reexported and default serialization preserved. This requires no migration,
portable permit or provider enum change. Raw quota values are checked before JSON
serialization to prevent copied bool/float/string normalization (ERROR-083).

Forty-three pure cases, independent coexistence probes and twelve distinct actual
normal015PG cases across11+1calls support admission. Root's full integrated1614
units/15.60s and strict13files pass. This is generic M1 notification intent/unknown
conservation, not native draft/POST/GET/delivery, real credential provisioning or
durable worker activation. Those remain separate implementation and release gates.

## ADR-115 — Recompute protected engineering acceptance during reconciliation

**Status:** accepted for the known-issued recovery slice
**Date:** 2026-10-14

Keep the existing execute-only acceptance path unchanged. A separate service
requires a current reconcile lease and actual succeeded native receipts, unique
author identity, approved verification edge and exact retained result/spec/witness.
Count all succeeded identities before validating the unique candidate; never pick
the latest or discard malformed candidates to obtain a passing pair. Recompute
mechanical evidence, stage proof bytes, and publish proof/acceptance under the
company mutex after repeated current checks and final source/grant/lease clocks.

Recovery cannot issue another effect or change budget/attempt/registration facts.
Known acceptance remains separate from billing and M1's verifying state. Portable
segment observations carry only descriptive evidence identities, with verdict
derived from WorkAcceptance. The six actual PG cases and Root's1,680unit gate
support this slice; durable worker/process restart and release are separate gates.

## ADR-116 — Retain sealed worker authentication at native notification boundaries

**Status:** accepted for the opt-in owner-only local composition
**Date:** 2026-10-15 (Asia/Bangkok)

Reuse the signature-verified process-local identity/expiry witness; role claims,
owner IDs and portable expiry DTOs provide no authentication. Keep existing native
source/current owner/exact decision/budget/lease gates. Credential time participates
in final intent clocks and the request boundary. Full current precall follows
awaited client setup. Known receipt replay remains current protected read only;
it cannot resend or resolve unknown outcomes by assumption.

Consume an existing exact owner approval for the deterministic prepared sender in
one CompanyControl transaction with complete current plan/source/draft/proposal
binding, cost reservation, final native/credential/approval windows and synchronous
recipient pin. Existing issued intents deny this authorization entry. No decision,
grant, work, queue entry or effect is created. Standing sends and non-owner service
admission remain outside this slice. Production credential provisioning and durable
worker activation require their separate gates. Frozen wrapper14checks, actual
authorization10PG and Root's1,703unit gate support this local implementation only.

## ADR-117 — Explicit complete CSV Node recipe and receipt-backed consistency checks

**Status:** accepted as an opt-in mechanical implementation
**Date:** 2026-10-15 (Asia/Bangkok)

Keep v3/default and all historical pins unchanged. Nodev4 requires reviewed source/
test/mapping/wrapper pins, complete shared/web report inventories and fixed methods.
Use a bounded owned scratch probe for baseline-module/new-test failure, then remove
it before complete post checks. No Python dependency or secrets enter the Node image.

Qualify actual report bytes against protected source witnesses and actual native
receipt/output/spec bindings for distinct author/verifier actions. Captured wrapper
observations bind canonical staged pins and exact paths/hashes/lengths/exits. Reject
inconsistent captures without claiming that jointly writable outputs authenticate
test truth. Reviewed source/test bodies and fixed commands remain required. A new
runner composes existing Node execution and engineering witness/recovery rather
than copying generic permits. Native PG/process and full StockFlow evidence must
follow; unit/synthetic success cannot close those release gates.


## ADR-118 — Compose a bounded native notification read/preparation tick

**Date:** 2026-10-15
**Status:** accepted for local default-disabled implementation; activation gated

Use the existing qualified native stores, concrete sealed configuration/identity
and current sender admission. One tick emits finite configured facts, consumes one
bounded cursor batch and prepares at most one existing pending draft. Each operation
retains its own sender/source/recipient/credential deadlines through the inherited
final clock. Default consumers keep their original handler through a narrow factory
seam. Scan progress is private process state, resets on restart/config change/full
cycle and grants no permission or public cursor.

The tick can commit an earlier phase before a later phase fails; exact persisted
wake/draft/action identities make the next tick reconcile that progress. This is
not an all-phases atomic transaction or automatic approval/external send. Transport,
queue dispatch, work/allowance allocation and daemon activation remain separate.
Current non-digest subjects use the exact configured facts.resource; dynamically
mapped actions on another resource deny before emission.

Source/static tests and one real first/replay PG case qualify this slice. Concurrent,
late-expiry, self-wake, page/restart and digest composition need actual evidence
before enabling a recurring worker. See the dated notification tick checkpoint.

## ADR-119 — One current native notification effect step and immutable history

**Date:** 2026-10-15 (Asia/Bangkok)
**Status:** accepted for local default-disabled implementation; runtime qualification pending
**Decided by:** Root after independent source review
**Relates to:** ADR-104, ADR-114, ADR-116, ADR-118

Use one fixed portable command workflow and one nonretry effect step. Reconstruct
the actual permanent registration/journal/dispatch and genuine sealed credential
inside the step. Fresh execution requires SDK PENDING on the fixed queue; exact
issued history may have terminal or cleared queue metadata but grants no fresh call.
Any original intent suppresses POST regardless of the newly acquired lease mode.
Bounded acquisition waits for only the same live segment and keeps current owner,
member/configuration and fresh admission windows through its last actual clock.

Return actual body-free native history before releasing the exact acquired lease.
Succeeded receipt with an actual UUID remains submitted when observation append
failed. A collapsed failed receipt is rejected only with a validated rejected
submission observation; otherwise classification remains unavailable. Missing
outcome and unknown billing remain explicit, with no retry, allowance reset or refund.

Trusted startup uses one bounded explicit system engine passed to DBOS and requires
restricted role and actual business/system endpoint/backend identity before launch.
Freeze2 implements the endpoint witness with mocked qualification; actual SQL/SDK
proof remains pending. The original passing freeze1 is retained separately.
An unrelated singleton is denied. Source and pure tests qualify the implementation;
actual SDK dispatch/replay, OS restart and production email remain separate gates.

## ADR-120 — Separate selected actor proof from owner choice and fresh effect issuance

**Date:** 2026-10-15 (Asia/Bangkok)
**Status:** accepted for source implementation; actual selected SQL/runtime qualification pending
**Decided by:** Root after bounded implementation and independent review
**Relates to:** ADR-103, ADR-106, ADR-107, ADR-112, ADR-117

Share native Strategy material/equality assembly behind distinct owner and actual
E/EV actor gates. Derive selected choice from the current approved revision2 and
registered full family; never pass an owner flag/credential or supplied choice into
the actor API. Two reads retain original proof/fences/windows through current task
READ and the last database clock. Pure proof observations convey no permission.

Construct the final concrete selected source guard in engineering context. Require
that guard plus the real contained-parent check, in exact order, before a fresh
mixed E/EV intent can reserve or consume anything. Bind complete trusted template
and separate exact approved action to the current work/lease/spec. Keep originally
eligible model-family windows and all first/current disclosure windows through
later awaits. A resolver subclass alone was rejected because the credential wrapper
copies base fields and discards overrides; a callback/boolean attestation would not
establish actual selected proof or parent observation.

Known issued history returns before fresh selection checks and cannot create a
second call or refund unknown money. Ordinary catalogs retain their existing path;
mixed sender ordering remains separately closed. No schema/dependency/allowance or
production activation follows. Source/mock gates qualify the implementation only;
actual SQL READ, genuine-parent intent and native E/EV evidence must follow.

## ADR-121 — Separate fresh mixed sender authority from native issued history

**Date:** 2026-10-15
**Status:** accepted for source implementation; actual mixed qualification pending
**Decided by:** Root after independent combined source review
**Relates to:** ADR-103, ADR-114, ADR-116, ADR-119, ADR-120

Acquire the actual sealed owner credential against the original complete server
registration before mixed metadata. Fresh work requires current full partition/
source/action authority and a concrete config/action native check at actual begin.
Final wrapper pins retain original check/preparation/catalog after later awaits;
per-operation dispatcher factories keep that check through the HTTP seam.

Actual intent+slot+attempt chooses a separate read-only recorded-family verifier.
It retains current owner/member/credential/config and immutable chronology/quota/
identity/counter facts, without a private body, new call, refund or refill. Current
active source approval is not historical evidence; deterministic IDs do not rewrite
original facts. Existing issuance suppresses POST and bypasses fresh intent checks.

A caller issued flag, permissive mode on active partition and a discarded resolver
subclass were rejected. No schema/dependency changed. Source/mock tests qualify
the integration only; actual SQL, SDK queue/replay, crash recovery and live email
remain separate gates before release.


## ADR-122 — Assemble complete private engineering bodies through native bounded reads

**Date:** 2026-10-15
**Status:** accepted for source; actual restricted-SQL/timing gate pending
**Decided by:** Codex under the approved bounded reader plan

Engineering summaries may exceed a single public16KiB slice. Preserve the native
public contract and assemble complete private bytes through sequential current
READs, keeping the genuine first slice and original qualified freshness. Bound
body size/pages/attempts and use one fixed30s collection ceiling without extending
authority. Only exact native UTF8 endpoint splits permit bounded same-offset retry.

CompleteEngineeringBody is process-local descriptive material. Both consumers
retain native slice checks AND full-reference stored-tail hashing under the same
transaction; first windows and actual composition remain required at the final
clock. PreparedEngineeringInput and public/proof/result caps remain unchanged.

Widening the public DTO or direct blob reads would weaken the existing boundary;
marking a first page complete would misrepresent integrity. Keeping a single-page
restriction would reject valid existing result references. Sequential reads cost
extra snapshot/I/O work, so real restricted-SQL timing remains an explicit next
qualification rather than an assumed fit for the StockFlow600s source window.
No schema, dependency, native job or service activation follows from this source.

Validation:77focused/2.18s, Root3,753unit/67.03s, strict/lint/format6 and favorable
independent file review; see ENGINEERING_COMPLETE_BODIES_SOURCE_CHECKPOINT_2026-10-15.md.


## ADR-123 — Separate current family facts from native execution membership

**Date:** 2026-10-15
**Status:** accepted for source; P/C consumers and actual execution remain separate
**Decided by:** Codex under the approved P/C prerequisite plan

Expose one descriptive locked read for an exact configured child and its complete
current owner-approved family. Retain company-first scope, head2/governance,
original revision event, all twelve rows and permanent registration/quota checks.
Extract the four existing row helpers without changing their AST behavior.

Keep native E/EV/sender membership and zero model limit/usage/delegation in the
existing execution wrapper. A neutral fact read cannot authorize P/PV/C/CV native
execution. Their forthcoming reader needs a separate exact partition and its own
lease/credential/protected evidence. Do not introduce an allow-model/role flag.

Validation:44 focused,264 compatibility and3,758 exact-source unit tests pass;
configured strict/lint/format3 and independent file review pass. See
CYCLE_FAMILY_READ_SOURCE_CHECKPOINT_2026-10-15.md. No schema/dependency or new active
tool route is introduced.


## ADR-124 — Read accepted engineering evidence under each downstream actor's own scope

**Date:** 2026-10-15
**Status:** accepted for dormant source; native P/C publication remains separate
**Decided by:** Codex under the approved P/C prerequisite plan

Use a distinct P/PV/C/CV partition and current credential/original lease to read
actual accepted E/EV evidence. Capture original grants/source/profile windows
before material READ. Preserve complete native receipts/attempts, independent
acceptance, exact provenance, full protected bytes/results, source witnesses and
actual containment sidecars. Recompute engineering and selected Strategy facts.

Retained-proof validation rereads both sidecars as well as public references and
body tails, and retains the original store/composition and final clock checks.
The process-local result is descriptive; readers do not issue or write acceptance.
Do not widen the E-only input reader or borrow the verifier's identity/lease.

This adds five dormant production modules and five unit/support files, without
schema, dependency or active route changes.319 focused and3,813 full unit tests,
configured strict/lint/format13 and independent review pass. Real accepted E/EV,
P/C publication and the full-goal SQL/runtime gates remain separate. See
CYCLE_ENGINEERING_PREREQUISITE_SOURCE_CHECKPOINT_2026-10-15.md.

## ADR-125 — Preserve truthful generated HTML with derived-only persistence

**Date:** 2026-10-15
**Status:** accepted

Generated presentations retain text/html. Source policy requires derived origin;
artifact metadata and the company016 CHECK require a derivation identity, retaining
existing deferred same-company provenance FKs. Keep direct HTML ingestion denied
and preserve the original three formats. Labelling HTML as plain text would lose
its real media identity; widening only Python literals would fail database writes.

Use the additive independent company lineage. Normal downgrade refuses retained
HTML and preserves rows/history transactionally. Native event capability explicitly
recognizes015/016 with actual columns checked; future revisions do not inherit it.
Fresh restricted PostgreSQL provenance/format/rollback and clean install/schema
checks qualify this boundary. Browser sanitization, native publication and service
migration/activation remain separate. See the generated HTML schema checkpoint.

## ADR-126 — Native dual-output publication and independent acceptance

**Date:** 2026-10-15
**Status:** accepted

Keep existing generic artifact tool keys and fixed protected targets/policies.
Native own-role readers require actual accepted same-goal E/EV and original/current
source authority. A committed effect permit precedes publication; both ordered
outputs and all provenance/event families persist or replay together. Known intents
use metadata before bodies; unresolved outcomes never issue a replacement write.
Independent check receipts and protected recomputation create acceptance.

Count all exact-run intents before recognizing one canonical succeeded/reconciled
model request beside a tool publication. Original intent approval timing and model
artifact identity remain checked without current-time approval or body reads.
Offline source/component checks establish implementation, not native activation or
business acceptance. Actual Company execution remains a separate release gate.

## ADR-127 — Exact manager histories and distinct current execution method

**Date:** 2026-10-15
**Status:** accepted

Preserve exact261.2-1 provider hashes and wire history; add explicit262-1 root and
issued provider identities with immutable closed selectors. Bind actual manager,
UID, phase and hash rather than accepting a version prefix or relabelling old data.
Full-method V7 binds these profiles while retaining the identifiable V6 descriptor.
The candidate remains unconfigured and execution_ready=false. Current execution
and verification require new qualification/pins; historical V6 is not renewed.
Tiny bootstrap normal/timeout evidence, opaque native issuance and full business
execution remain separate qualifications.


## ADR-128 — Shared bounded mount reader with distinct current parent profiles

**Date:** 2026-10-15
**Status:** accepted (source; actual qualification pending)

Use one shared fixed-name mountinfo reader with a 65,536-byte complete bound and
one-byte overflow sentinel. Keep the generic kernel-file bound at4,096 bytes.
Retain same-call immutable length/hash/status metadata, held mount namespace,
root/group descriptor identities and final visible group rebind after final
mount/boot/membership reads. Finite path replacement tests verify this order;
observations do not establish atomic protection from a hostile same-UID writer.

Preserve historical261/262 root/issued tuples, canonical descriptors, default261
wire fixture and V6/V7 method digests. New exact current261/262 root and issued
identities bind the changed reader; fresh observation, service return, spawn and
owned-start binding require current tuples. Historical DTOs remain readable.
Full V8 describes the new composition with execution_ready=false and stays
unconfigured pending actual native qualification. Old evidence cannot activate it.
The private manual public-data importer adopts these through a new v2 profile,
new source and a fresh namespace only after its own source qualification/review.


## ADR-129 — Bind nominated image reference and configuration separately

**Date:** 2026-10-16
**Status:** accepted (source; native qualification remains separate)

The selected CSV template incorrectly equated its immutable manifest-reference
suffix with the installed image/configuration ID. Retained manifest, loaded-image
and exact-reference preflight evidence records distinct c4d552… and8f3dff… values.
The [OCI configuration specification](https://github.com/opencontainers/image-spec/blob/main/config.md#imageid)
defines ImageID from configuration JSON; the [manifest](https://specs.opencontainers.org/image-spec/manifest/)
references that configuration. Neither equality nor arbitrary inequality binds them.

Check one exact trusted tuple of architecture/full reference/manifest/configuration
ID for the nominated amd64 image. Unknown references, aliases, architectures,
coercions and cross-pairs deny pending their separate qualification. Preserve the
existing public template fields and all other policy/source/runtime guards.
Synthetic linked fixtures use the real distinct image pair while keeping their
remaining data explicitly supplied. Raw historical golden wires remain unchanged.
The tuple describes server configuration; actual native image observation, current
capabilities/policy/owned parent, leases and permits remain required. No new public
DTO, dependency, migration, image download or native authority follows from this fix.

## ADR-130 — Stop the original owned container before releasing run ownership

**Date:** 2026-10-16
**Status:** accepted for implementation; combined source and native qualification pending

Actual cancellation qualification detects the native denial promptly, but killing
the Podman client leaves the container tree alive. Introduce a distinct bounded
running-stop operation. Existing cleanup v1 remains stopped-object inspection and
removal; adding a force flag there would broaden a different authority boundary.

The original opaque context, actual process and discovery seal select one full
immutable container ID with its original company/action/name/image binding. A DTO,
name, stored historical record or new execution lease cannot confer stop authority.
Mark the context consumed before the first await; repeated/concurrent entry denies.
Issue inspect, KILL only if running, wait and re-inspect under one five-second cap
shortened by the original operation, parent and owner ends. No deadline renewal,
container removal, replacement permit or financial reset accompanies the stop.

The run owns shielded stop, command/capture/reap and finalizer tasks until settled.
Preserve the original denial under repeated coordinator cancellation; defer context
close when actual owners remain pending. Missing seals, expired budget and incomplete
stop remain unproven. An engine stop result cannot replace whole-tree PID/start
retirement under the original physical oracle.
An already-issued CLI may finish late; its original unknown result stays unknown.
Retain its actual resource-completion task/child until settlement, without another
container command or positive result adoption. Distinguish that semantic uncertainty
from pending resource ownership before metadata release or collector shutdown.

Name and preserve the exact V8 method expression alongside V6/V7; a new current V9
descriptor binds these changed semantics and stays unconfigured. Explicit old
result/sidecar reads and metadata-only recovery remain supported. Fresh policy,
service, dispatch and protected interpretation stay current-only; this does not
introduce a historical execution or old-result republication mode.

Private qualification output uses a dedicated complete canonical control record
and separately retained bounded diagnostics. Adopt a completed original-owned
report before waiting for physical retirement, preserving first cause on failure.
Never strip historical mixed output into accepted wire or relax physical predicates.
Test source boundaries first, then use fresh exact pins and an independent namespace
for all five native fault cases. No schema, dependency or runtime activation follows
from this decision. The old stopped wave and every consumed artifact remain intact.

## ADR-131 — Reject Google continuation at the bounded response hook

**Date:** 2026-10-16
**Status:** implemented; offline SDK checks passed, live qualification remains open

The pinned google-genai2.30.1 client automatically follows continuation responses.
Retry attempts1 does not disable that loop. A real SDK test with mock HTTP shows
two POSTs under one mocked authorizer claim. PydanticAI2.54 does not expose the client's
automatic-continuation option through its supported Google model settings.

Keep the existing SDK/API and public HTTP response hook. First run the bounded
WireObserver so supported first-hop usage is retained. Then reject continuation
finish/token markers before the SDK can parse and follow them. Malformed,
oversized or unsupported usage fails earlier and stays unknown. A supported
first-hop charge can stay known, but continuation never becomes successful text,
a tool proposal or an implicit second billable call.

Do not patch dependency internals, use wire extra_body as a client-side flag,
upgrade the SDK by assumption or change the provider API. Ordinary Google/OpenAI
responses, output caps, retry settings, authority and durable intent/hold handling
stay unchanged. Mock-HTTP conformance and current-source integration are required;
neither establishes live provider quality or activates the empty preview catalog.

The separate concrete endpoint resolver accepts only explicitly configured named
bindings for the currently supported official OpenAI Responses/Google GenerateContent
bases. It resolves an injected Settings credential at runtime without caching,
discovery or fallback. Credentials remain absent from model request/result DTOs.
Resolver configuration is not model eligibility, invocation authority or setup
approval. No migration or dependency change follows from this decision.

## ADR-132 — Separate financial input bounds, qualification and planning authority

**Date:** 2026-10-16
**Status:** implemented; combined source and restricted-PG/SDK-mock integration pass;
live qualification and owner/runtime planning integration remain pending

Reserve the reviewed model's complete input ceiling when exact local framing
cannot be proven. Encode this as explicit whole-input financial mode; preserve
legacy request/quote bytes when the optional mode is absent. It is not a prompt
fit certificate. Original registry/model/recipe/source/version hashes must join
the actual request at intent and immediately before SDK use. Existing data
allowlists and normal healthy/evaluated model eligibility remain required.

Unknown disabled models use a distinct public-only SDK qualification operation.
It has a dedicated owner goal, fixed server catalog and permanent shared Work
allocation, exact approvals, current goal/mandate, native attempts/holds/leases
and separate protected evidence. It cannot reuse a delivery procedure goal,
enable a model, assert profile quality or complete company work. Both providers
share the fixed target set and lifetime allowance; changing a case or day cannot
reset it. Until output-cap conformance is known, the financial hold also covers
the full reviewed output ceiling while the requested cap stays small.

The governed planning consumer binds the server's original goal and plan-head
comparison into its fixed output schema. An actual protected known result may
become a bounded historical candidate. Formal proposal mapping must recheck the
current goal/head and supply authority, identities, resources and allowances from
server configuration. Valid JSON cannot approve work, change caps or replace a
goal's permanent reasoning root with the existing zero-model native pair.

Keep original finite deadlines and actual SDK/file/settlement task ownership.
Late work cannot become positive or authorize a second request. Reuse the pinned
SDKs, native stores and company schema; no new framework, dependency, database
migration, paid request or runtime activation follows from these components.

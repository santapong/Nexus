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

<!-- New ADR entries go above this line, with the next ID number -->
<!-- Next ID: ADR-011 -->

---

*Last updated: 2026-03*
*Next ADR ID: ADR-011*
*Decision count: 10 accepted*

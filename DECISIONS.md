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
| ADR-011 | Semantic memory contradiction resolution strategy | proposed | 2026-03-07 |
| ADR-012 | Log aggregation approach for v1 | proposed | 2026-03-07 |
| ADR-013 | Meeting room termination signal | proposed | 2026-03-07 |
| ADR-014 | Pin pydantic-ai 0.5.x with anthropic <0.83.0 | accepted | 2026-03-08 |
| ADR-015 | Docker port remapping for local dev | accepted | 2026-03-08 |
| ADR-016 | Explicit DB commit before Kafka publish | accepted | 2026-03-08 |
| ADR-017 | Universal ModelFactory — multi-provider prefix registry | accepted | 2026-03-08 |
| ADR-018 | Test model provider for infrastructure testing | accepted | 2026-03-08 |
| ADR-019 | LLM retry logic with exponential backoff | accepted | 2026-03-08 |

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
**Status:** proposed
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
**Status:** proposed
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
**Status:** proposed
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

<!-- New ADR entries go above this line, with the next ID number -->
<!-- Next ID: ADR-020 -->

---

*Last updated: 2026-03-08*
*Next ADR ID: ADR-020*
*Decision count: 16 accepted, 3 proposed*

# NEXUS — Agentic AI Company as a Service
## CLAUDE.md — Master Project Document

> **This file is the single source of truth for this project.**
> Every developer, every AI agent, and every automated tool that touches this codebase
> must read and follow everything in this document before writing a single line of code.
> When in doubt, refer back here.
>
> **Agents:** Load §20 (Agent Operational Policy) and §23 (Prevention Rules) into your
> semantic memory under namespace `project.policy` before executing any task.

---

## Table of Contents

1.  [Project Vision](#1-project-vision)
2.  [Current Status & Phase](#2-current-status--phase)
3.  [Architecture Overview](#3-architecture-overview)
4.  [Tech Stack — Finalized Decisions](#4-tech-stack--finalized-decisions)
5.  [AI Framework Decision](#5-ai-framework-decision)
6.  [LLM Provider Strategy](#6-llm-provider-strategy)
7.  [Agent Roster & Responsibilities](#7-agent-roster--responsibilities)
8.  [MCP Tools Integration](#8-mcp-tools-integration)
9.  [A2A Gateway — External Agent Protocol](#9-a2a-gateway--external-agent-protocol)
10. [Kafka Design — Topics & Flow](#10-kafka-design--topics--flow)
11. [Redis Architecture — Four Roles](#11-redis-architecture--four-roles)
12. [Database & Memory Schema](#12-database--memory-schema)
13. [Task Queue — Taskiq](#13-task-queue--taskiq)
14. [Testing Strategy](#14-testing-strategy)
15. [Project Structure](#15-project-structure)
16. [Coding Policy — Python Backend](#16-coding-policy--python-backend)
17. [Coding Policy — TypeScript Frontend](#17-coding-policy--typescript-frontend)
18. [Coding Policy — Database](#18-coding-policy--database)
19. [Coding Policy — Kafka](#19-coding-policy--kafka)
20. [Agent Operational Policy](#20-agent-operational-policy)
21. [Git & CI/CD Policy](#21-git--cicd-policy)
22. [Docker Compose — Local Dev](#22-docker-compose--local-dev)
23. [Prevention Rules — Active Risks](#23-prevention-rules--active-risks)
24. [Build Roadmap — Phased Plan](#24-build-roadmap--phased-plan)
25. [Open Questions & Decisions Log](#25-open-questions--decisions-log)

---

## 1. Project Vision

**NEXUS** is an Agentic AI Company-as-a-Service platform.

The core concept: a digital company where every department is staffed by an AI agent.
Agents have defined roles, persistent memory, access to MCP tools, and communicate
through Apache Kafka — the "conference room" where agents can meet, debate, and collaborate.

**Phase 1 goal:** Internal tool for solo use. Prove the architecture works end-to-end
before exposing it to other users or building SaaS features.

**Long-term goal:** Multi-tenant platform where any user can spin up their own AI company,
configure agents, and delegate real business tasks. External agents and companies can
hire NEXUS agents via the A2A protocol.

### Three protocol layers — distinct jobs, no overlap

| Protocol | Job | Scope |
|----------|-----|-------|
| **Kafka** | Internal agent communication | CEO ↔ Engineer ↔ QA — never leaves the system |
| **MCP** | Agent → Tools | Web search, code execution, file system, email |
| **A2A** | Agent ↔ External Agents | External systems hire NEXUS; NEXUS hires specialists |

These three protocols never compete. Confusing their roles is the #1 integration mistake.

### Primary task categories (v1)

- Software engineering & coding
- Research & analysis
- Business operations (email drafting, planning, scheduling)
- Content writing

---

## 2. Current Status & Phase

| Item | Status |
|------|--------|
| Architecture design | ✅ Complete |
| Tech stack decisions | ✅ Finalized |
| AI framework decision | ✅ Pydantic AI (see §5) |
| Database schema design | ✅ Deployed — all 9 tables (see §12) |
| Coding policy | ✅ Defined + CI enforced (see §16–21) |
| MCP integration | ✅ Complete — adapter + registry + guards (see §8) |
| A2A gateway | ✅ Complete — inbound with SSE streaming (see §9) |
| Prompt Creator Agent | ✅ Complete — failure analysis, benchmarks, approval flow (see §7) |
| Prevention guide | ✅ Defined (see §23) |
| MCP tools project | ✅ Integrated (Python package, direct import) |
| Codebase scaffolding | ✅ Complete |
| Docker Compose setup | ✅ Complete (5 services) |
| Agent base class | ✅ Complete |
| Phase 0 build | ✅ Complete |
| Phase 1 build | ✅ Complete — 50-task stress test: 100% pass rate |
| Phase 2 build | ✅ Complete — 20-task stress test: 100% pass rate |

**Current phase:** Phase 2 COMPLETE — Ready for Phase 3 hardening.

**Next action:** Phase 3 — Chaos tests, dead letter monitoring, A2A outbound, bearer token issuance.

---

## 3. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│  External World                                                     │
│  Other AI Agents ←── A2A Protocol ──→     User / Dashboard         │
└──────────────────┬──────────────────────────────┬───────────────────┘
                   │ HTTP + SSE                   │ HTTP + WebSocket
┌──────────────────▼──────────────┐  ┌────────────▼────────────────── ┐
│  A2A Gateway Service  [NEW §9]  │  │  Litestar API                  │
│  /.well-known/agent.json        │  │  REST + WebSocket + Auth        │
│  POST /a2a  GET /a2a/{id}/stream│  │  Rate limiting                  │
└──────────────────┬──────────────┘  └────────────┬────────────────────┘
                   │ Kafka: a2a.inbound            │ Kafka: task.queue
┌──────────────────▼──────────────────────────────▼───────────────────┐
│  Apache Kafka — Event Bus  (The Conference Room)  [unchanged]       │
│  task.queue · agent.commands · agent.responses · task.results       │
│  meeting.room · memory.updates · audit.log · agent.heartbeat        │
│  human.input_needed · tools.* · a2a.inbound · prompt.*             │
└──────────┬──────────────────────────────────────────────────────────┘
           │
┌──────────▼──────────────────────────────────────────────────────────┐
│  Agent Runtime — Pydantic AI                                        │
│  CEO · Engineer · Analyst · Writer · QA · Prompt Creator           │
│  (all extend AgentBase — stateless, Kafka-driven)                   │
└──────────┬──────────────────────────────────────────────────────────┘
           │ Pydantic AI tool calls
┌──────────▼──────────────────────────────────────────────────────────┐
│  Tools Layer — MCP Adapter  [NEW §8]                                │
│  nexus/tools/adapter.py  ← wraps your MCP Python package           │
│  nexus/tools/registry.py ← per-role access map                     │
│  nexus/tools/guards.py   ← require_approval() irreversibility gate  │
│  web_search · file_read · code_execute · file_write⚠ · email⚠      │
└──────────┬──────────────────────────────────────────────────────────┘
           │
┌──────────▼──────────────────────────────────────────────────────────┐
│  Persistence                                                        │
│  PostgreSQL 16 + pgvector  ← source of truth                       │
│  Redis 7 (4 roles)         ← speed layer / working memory          │
└─────────────────────────────────────────────────────────────────────┘
```

### Key architectural principles

1. **Kafka is the internal nervous system.** All NEXUS agent-to-agent communication goes
   through Kafka only. Nothing agent-to-agent is direct. Observable and replayable.

2. **MCP gives agents hands.** Tools are Pydantic AI functions wrapping your MCP package.
   Agents never import MCP directly — always through adapter + registry.

3. **A2A sits at the boundary only.** The A2A Gateway translates external requests into
   Kafka messages. Agents cannot tell whether a task came from a human or an external
   agent — it arrives on `a2a.inbound` and looks identical to any other task.

4. **PostgreSQL is the source of truth.** All durable state lives here. Redis and Kafka
   are speed/communication layers. If both die, the system recovers from PostgreSQL alone.

5. **Agents are stateless processes.** No in-memory state between tasks. All state is in
   Redis (working memory) or PostgreSQL (long-term memory). Agents restart safely.

6. **Every action is traceable.** Every Kafka message, DB write, LLM call, and tool use
   carries `task_id` and `trace_id`. You can reconstruct exactly what happened.

7. **Humans stay in the loop.** Irreversible actions require an explicit `HumanApproval`
   record before execution. Enforced in `tools/guards.py` — agents cannot bypass it.

---

## 4. Tech Stack — Finalized Decisions

### Backend

| Component | Choice | Reason |
|-----------|--------|--------|
| Language | Python 3.12+ | Async-native, best AI/ML ecosystem |
| API Framework | **Litestar** | Async-first, type-safe, excellent OpenAPI |
| ORM | **Advanced Alchemy** | Type-safe async ORM, pairs with Litestar |
| DB Migrations | **Alembic** | Standard, works with Advanced Alchemy |
| AI Agent Runtime | **Pydantic AI** | See §5 |
| Task Queue | **Taskiq** | Async-native, Kafka broker backend |
| Kafka Client | **aiokafka** | Async Kafka consumer/producer |
| Redis Client | **redis-py (async)** | Full async support |
| Validation | **Pydantic v2** | Used throughout by Pydantic AI + Litestar |
| Linting | **Ruff** | Fast, replaces flake8 + isort |
| Type Checking | **mypy (strict)** | Enforced in CI |
| Testing | **pytest + pytest-asyncio** | Async test support |
| Logging | Structured JSON logger | task_id on every log line |

### Frontend

| Component | Choice | Reason |
|-----------|--------|--------|
| Language | TypeScript (strict) | Type safety, matches backend Pydantic models |
| Framework | **Vite + React 18** | Fast dev, no Next.js overhead for v1 |
| State (server) | **TanStack Query v5** | All API calls, caching, invalidation |
| State (UI) | **Zustand** | Lightweight global UI state only |
| Styling | **Tailwind CSS** | Utility-first, consistent |
| Components | **Shadcn/ui** | ✅ Decided — Composable, Tailwind-based |
| Real-time | **Native WebSocket** | Streaming Kafka events to dashboard |
| API client | **Generated from OpenAPI** | Always matches backend types |

### Infrastructure

| Component | Choice | Reason |
|-----------|--------|--------|
| Containerization | **Docker + Docker Compose** | v1 local dev target |
| Database | **PostgreSQL 16 + pgvector** | Vector memory support |
| Cache / Speed | **Redis 7** | 4 roles (see §11) |
| Message Bus | **Apache Kafka KRaft** | No ZooKeeper dependency |
| Embedding Model | **Google embedding-001** | ✅ Decided — already using Gemini, no third provider |
| Observability | Structured logs + audit table | Custom, no external tools in v1 |

### Intentionally excluded from v1

- Kubernetes — overkill for solo local use
- Temporal — add in Phase 4 when tasks run >1 hour regularly
- LangSmith / LangFuse — add with Temporal in Phase 4
- External observability (Datadog, etc.) — internal logging sufficient

---

## 5. AI Framework Decision

### ✅ Decision: Pydantic AI

**Rejected:** LangChain + LangGraph

Pydantic AI handles: structured LLM calls with typed outputs, tool/function calling with
Pydantic validation, multi-provider model abstraction (Claude, Gemini), async-native
execution, and dependency injection compatible with Litestar.

Pydantic AI does **not** handle (and should not):
- Agent orchestration → Kafka
- Agent memory → PostgreSQL
- Task scheduling → Taskiq
- Agent communication → Kafka topics
- Tool access control → `tools/registry.py` + `tools/guards.py`

LangGraph was rejected because it would create a second orchestration layer competing
with Kafka. Two orchestration systems in the same codebase fight each other.

The Pydantic AI dependency is isolated inside `AgentBase`. If it ever needs replacing,
nothing else changes — Kafka, PostgreSQL, Taskiq, the API, the frontend, MCP, and A2A
are all unaffected.

---

## 6. LLM Provider Strategy

### Providers: Claude (Anthropic) + Gemini (Google)

**Rule:** No agent code references a specific provider directly.
All LLM calls go through `llm/factory.py → ModelFactory`.

### Default model assignment per role

| Agent | Primary | Fallback | Reason |
|-------|---------|----------|--------|
| CEO | Claude Sonnet | Gemini Pro | Best reasoning for orchestration |
| Engineer | Claude Sonnet | Gemini Pro | Best code generation |
| Analyst | Gemini Pro | Claude Haiku | Long-document analysis, cost-effective |
| Writer | Claude Haiku | Gemini Flash | Fast, structured writing |
| QA | Claude Haiku | Gemini Flash | Simple evaluation tasks |
| Prompt Creator | Claude Sonnet | Gemini Pro | Analytical reasoning required |

### ModelFactory

```python
# nexus/llm/factory.py
class ModelFactory:
    @staticmethod
    def get_model(role: AgentRole, override: str | None = None) -> BaseModel:
        model_name = override or settings.AGENT_MODEL_MAP[role]
        if model_name.startswith("claude"):
            return AnthropicModel(model_name, api_key=settings.ANTHROPIC_API_KEY)
        if model_name.startswith("gemini"):
            return GeminiModel(model_name, api_key=settings.GOOGLE_API_KEY)
        raise ValueError(f"Unknown model: {model_name}")
```

### Cost controls — mandatory from Phase 0

- Hard daily spending cap: **$5/day** enforced via Redis token tracker
- Per-task token budget: **50,000 tokens** (configurable per role in `agents` table)
- At 90% budget consumed → pause task → publish to `human.input_needed`
- Every LLM call writes a row to `llm_usage`: `model_name`, `input_tokens`,
  `output_tokens`, `task_id`, `agent_id`, `cost_usd`
- **Token budget enforcement must be live before any real LLM call runs**

---

## 7. Agent Roster & Responsibilities

### Complete roster — v1

| Agent | Phase | Role | Model |
|-------|-------|------|-------|
| CEO | 1 | Orchestrator, task decomposer, delegator | Claude Sonnet |
| Engineer | 1 | Code generation, debugging, architecture | Claude Sonnet |
| Analyst | 2 | Research, data analysis, reports | Gemini Pro |
| Writer | 2 | Content, emails, documentation | Claude Haiku |
| QA | 2 | Reviews all outputs before delivery | Claude Haiku |
| Prompt Creator | 2 | Meta-agent: improves all other agents' prompts | Claude Sonnet |

### Agent details

#### CEO Agent
- **Kafka:** subscribes `task.queue`, `agent.responses`, `a2a.inbound`
  — publishes `agent.commands`, `task.results`
- **Tools:** None — CEO delegates tool use to specialists
- **Memory:** `episodic.ceo`, `semantic.strategy`

#### Engineer Agent *(Phase 1 — first built)*
- **Kafka:** subscribes `agent.commands` (role=engineer) — publishes `agent.responses`
- **Tools:** `web_search`, `file_read`, `code_execute`, `file_write`⚠, `git_push`⚠
- **Memory:** `episodic.engineer`, `semantic.codebase`

#### Analyst Agent
- **Kafka:** subscribes `agent.commands` (role=analyst) — publishes `agent.responses`
- **Tools:** `web_search`, `web_fetch`, `file_read`, `file_write`⚠
- **Memory:** `episodic.analyst`, `semantic.research`

#### Writer Agent
- **Kafka:** subscribes `agent.commands` (role=writer) — publishes `agent.responses`
- **Tools:** `web_search`, `file_read`, `file_write`⚠, `send_email`⚠
- **Memory:** `episodic.writer`, `semantic.brand_voice`

#### QA Agent
- **Kafka:** subscribes `task.review_queue` — publishes `task.results`
- **Tools:** `file_read`, `web_search`
- **Memory:** `episodic.qa`, `semantic.quality_criteria`

#### Prompt Creator Agent *(meta-agent — Phase 2, Week 6–7)*
- **Role:** Reads failure patterns from episodic memory of other agents → drafts
  improved system prompts → runs benchmark tests → proposes for human approval.
  **Never deploys a prompt automatically.** A bad auto-deployed prompt could corrupt
  every agent simultaneously.
- **Kafka:** subscribes `prompt.improvement_requests`, `prompt.benchmark_requests`
  — publishes `prompt.proposals`, `human.input_needed`
- **Tools:** `web_search`, `file_read`, `memory_read` (reads other agents' memories)
- **Memory:** `episodic.prompt_creator`, `semantic.prompt_techniques`
- **Trigger:** Agent failure rate >10% in last 20 tasks, or manual request

### ⚠ Irreversible tools

Tools marked ⚠ cannot execute without an approved `HumanApproval` record in the
database. The `require_approval()` guard in `tools/guards.py` enforces this at the
adapter layer — agents cannot bypass it in their own logic.

### Agent base class contract

```python
class AgentBase(ABC):
    role: AgentRole                     # set in each subclass

    # Injected dependencies
    db: AsyncSession
    kafka: KafkaClient
    redis_working: Redis                # db:0
    redis_cache: Redis                  # db:1
    redis_pubsub: Redis                 # db:2
    redis_locks: Redis                  # db:3
    memory: AgentMemory
    llm: Agent                          # Pydantic AI Agent

    @abstractmethod
    async def handle_task(self, message: AgentCommand) -> AgentResponse: ...

    # Provided by base — DO NOT override in subclasses
    async def run(self): ...                     # Kafka consumer loop
    async def _execute_with_guards(self): ...    # idempotency → budget → load memory
                                                 # → handle_task → write memory → publish
    async def _check_budget(self, task_id): ...  # halts at 90%, raises TokenBudgetExceeded
    async def _write_memory(self, episode): ...  # MUST complete before result published
    async def _broadcast(self, event): ...       # Redis pub/sub → dashboard WebSocket
    async def _heartbeat_loop(self): ...         # publishes to agent.heartbeat every 30s
    async def _request_human_input(self): ...    # publishes to human.input_needed, pauses
```

---

## 8. MCP Tools Integration

### Integration method: Python package → Pydantic AI native tools

Your MCP project is a Python package imported directly.
Result: no HTTP overhead, no extra server, no extra Docker service.
The integration is **three files** in `nexus/tools/`.

### The three files

```
nexus/tools/
├── adapter.py      ← wraps MCP package functions as Pydantic AI tools
├── registry.py     ← per-role tool access map, enforced at agent construction
└── guards.py       ← require_approval() + IrreversibleAction model
```

### adapter.py — the wrapping pattern

```python
# nexus/tools/adapter.py
from your_mcp_package import web_search, code_exec, file_ops, email_ops, git_ops
from pydantic_ai import RunContext
from nexus.tools.guards import require_approval, IrreversibleAction

# READ-ONLY — no approval needed
async def tool_web_search(ctx: RunContext, query: str) -> str:
    """Search the web and return relevant results.
    Args: query: The search query string.
    Returns: Formatted search results as text.
    """
    return await web_search.search(query)

async def tool_file_read(ctx: RunContext, path: str) -> str:
    """Read the contents of a file.
    Args: path: Absolute or relative path to the file.
    Returns: File contents as string.
    """
    return await file_ops.read(path)

async def tool_code_execute(ctx: RunContext, code: str, language: str = "python") -> str:
    """Execute code in a sandboxed environment with no network access.
    Args: code: Code to execute. language: python | bash | node.
    Returns: stdout + stderr output.
    """
    return await code_exec.run_sandboxed(code, language)

# IRREVERSIBLE — require human approval before execution
async def tool_file_write(ctx: RunContext, path: str, content: str) -> str:
    """Write content to a file. Requires human approval — cannot be undone.
    Args: path: File path to write to. content: Content to write.
    Returns: Confirmation message.
    """
    await require_approval(ctx, IrreversibleAction(
        action="file_write",
        description=f"Write {len(content)} chars to {path}",
        task_id=ctx.deps.task_id
    ))
    return await file_ops.write(path, content)

async def tool_send_email(ctx: RunContext, to: str, subject: str, body: str) -> str:
    """Send an email. Requires human approval — irreversible.
    Args: to: Recipient address. subject: Subject line. body: Email body.
    Returns: Confirmation with message ID.
    """
    await require_approval(ctx, IrreversibleAction(
        action="send_email",
        description=f"Send email to {to}: {subject}",
        task_id=ctx.deps.task_id
    ))
    return await email_ops.send(to, subject, body)
```

### registry.py — access map

```python
# nexus/tools/registry.py
TOOL_REGISTRY: dict[AgentRole, list] = {
    AgentRole.CEO:            [],
    AgentRole.ENGINEER:       [tool_web_search, tool_file_read, tool_file_write,
                                tool_code_execute, tool_git_push],
    AgentRole.ANALYST:        [tool_web_search, tool_web_fetch,
                                tool_file_read, tool_file_write],
    AgentRole.WRITER:         [tool_web_search, tool_file_read,
                                tool_file_write, tool_send_email],
    AgentRole.QA:             [tool_file_read, tool_web_search],
    AgentRole.PROMPT_CREATOR: [tool_web_search, tool_file_read, tool_memory_read],
}
# In AgentBase.__init__: tools=get_tools_for_role(self.role) injected into Pydantic AI Agent
```

### Complete tool registry

| Tool | Type | Agents with access |
|------|------|--------------------|
| `web_search` | Read-only | engineer, analyst, writer, qa, prompt_creator |
| `web_fetch` | Read-only | analyst, writer |
| `file_read` | Read-only | engineer, analyst, writer, qa, prompt_creator |
| `code_execute` | Sandboxed | engineer only |
| `file_write` ⚠ | Irreversible | engineer, analyst, writer |
| `git_push` ⚠ | Irreversible | engineer only |
| `send_email` ⚠ | Irreversible | writer only |
| `memory_read` | Read-only | prompt_creator only |
| `hire_external_agent` ⚠ | Irreversible + A2A | all (Phase 3) |

### MCP prerequisite — before Phase 1

Audit every function in your MCP package that will be wrapped:
- All parameters must have type hints
- All functions must have a docstring with one-line summary + Args + Returns

Pydantic AI uses the docstring to describe the tool to the LLM.
Vague docstrings produce bad tool usage. Add them to the MCP package if missing.
**This is a prerequisite for Phase 1. Do it before writing adapter.py.**

---

## 9. A2A Gateway — External Agent Protocol

### What A2A is

Google's Agent-to-Agent protocol (open source, April 2025). Standard for how AI agents
discover each other, negotiate capabilities, and exchange tasks. Uses JSON over HTTP
with Server-Sent Events (SSE) for streaming. Agents advertise via an "Agent Card" JSON
document served at `/.well-known/agent.json`.

### Three use cases — all planned

| Use Case | Direction | Phase |
|----------|-----------|-------|
| External agents hire NEXUS | Inbound | Phase 2, Week 7–8 |
| NEXUS agents hire external specialists | Outbound | Phase 3 |
| Multi-tenant: NEXUS companies hire each other | Bidirectional | Phase 4 |

### Critical design rule

**The A2A Gateway is the only code that speaks A2A.**
It converts external requests into internal Kafka messages and vice versa.
Agents receive A2A tasks on `a2a.inbound` — identical format to any Kafka task.
They cannot tell the difference between human and A2A tasks.
A2A adds zero complexity to agent code.

### New gateway files

```
nexus/gateway/
├── routes.py       ← /.well-known/agent.json · POST /a2a · GET /a2a/{id}/stream
├── outbound.py     ← A2A HTTP client for calling external agents
├── schemas.py      ← A2ATask, AgentCard, A2AEvent Pydantic models
└── auth.py         ← Bearer token validation for inbound calls
```

### Agent Card — NEXUS identity document

```json
{
  "name": "NEXUS Agentic Company",
  "url": "https://nexus.yourdomain.com",
  "capabilities": { "streaming": true, "stateTransitionHistory": true },
  "authentication": { "schemes": ["bearer"] },
  "skills": [
    { "id": "software-engineering", "name": "Software Engineering",
      "tags": ["python", "typescript", "code", "debug"] },
    { "id": "research-analysis", "name": "Research & Analysis",
      "tags": ["research", "analysis", "report"] },
    { "id": "content-writing", "name": "Content & Business Writing",
      "tags": ["writing", "email", "content"] }
  ]
}
```

### Inbound flow

```
1. External agent fetches /.well-known/agent.json
2. External agent → POST /a2a with task + bearer token
3. Gateway validates token, resolves skill → creates task in DB
4. Gateway → Kafka: Topics.A2A_INBOUND
5. CEO consumes a2a.inbound, routes to correct specialist agent
6. Agent executes, publishes to agent.responses as normal
7. Gateway subscribes to Redis pub/sub agent_activity:{task_id}
8. Gateway streams progress to external agent via SSE
```

### Outbound — NEXUS hires external agents

`tool_hire_external_agent` is added to the MCP adapter in Phase 3.
It is an irreversible tool — requires human approval before NEXUS calls any
external service. Prevents agents from autonomously spending on third-party APIs.

### A2A security plan

| Requirement | Implementation | Phase |
|-------------|----------------|-------|
| Authentication | Bearer token per external caller, stored in DB | Phase 3 |
| Rate limiting | Per-token limit via Redis db:1 | Phase 3 |
| Skill authorization | Token has allowed_skills list | Phase 3 |
| Outbound approval | `require_approval()` on `hire_external_agent` | Phase 2 |
| Audit trail | All A2A interactions written to `audit_log` table | Phase 2 |
| Input validation | Pydantic validation at gateway before Kafka publish | Phase 2 |

---

## 10. Kafka Design — Topics & Flow

### Topic registry

**All topic names in `nexus/kafka/topics.py` as constants.**
**No hardcoded topic strings anywhere else in the codebase. Ever.**

```python
# nexus/kafka/topics.py
class Topics:
    TASK_QUEUE                = "task.queue"
    TASK_RESULTS              = "task.results"
    TASK_REVIEW_QUEUE         = "task.review_queue"
    AGENT_COMMANDS            = "agent.commands"
    AGENT_RESPONSES           = "agent.responses"
    MEETING_ROOM              = "meeting.room"
    MEMORY_UPDATES            = "memory.updates"
    TOOLS_REQUESTS            = "tools.requests"
    TOOLS_RESPONSES           = "tools.responses"
    AUDIT_LOG                 = "audit.log"
    AGENT_HEARTBEAT           = "agent.heartbeat"
    HUMAN_INPUT_NEEDED        = "human.input_needed"
    A2A_INBOUND               = "a2a.inbound"               # NEW
    PROMPT_IMPROVEMENT        = "prompt.improvement_requests" # NEW
    PROMPT_BENCHMARK          = "prompt.benchmark_requests"   # NEW
    PROMPT_PROPOSALS          = "prompt.proposals"            # NEW
```

### Standard message envelope — mandatory on every message

```python
class KafkaMessage(BaseModel):
    message_id: UUID = Field(default_factory=uuid4)
    task_id: UUID       # REQUIRED — links to tasks table
    trace_id: UUID      # REQUIRED — groups all messages from one user request
    agent_id: str       # REQUIRED — who sent this
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    payload: dict
```

**Consumers reject messages missing `task_id`, `trace_id`, or `agent_id`.**

### Task execution flow — human

```
1. POST /tasks → task created in DB (status: queued)
2. API → Kafka: task.queue
3. CEO consumes task.queue, decomposes goal
4. CEO → Kafka: agent.commands (with role routing key per subtask)
5. Specialist agents consume agent.commands, filter by role
6. Agents load episodic + semantic memory context
7. Agents execute: LLM calls → tool calls via MCP adapter
8. Agents → Kafka: agent.responses
9. CEO aggregates → Kafka: task.review_queue
10. QA → Kafka: task.results
11. API updates task in DB (status: completed)
12. Redis pub/sub → WebSocket → dashboard shows result
```

### Task execution flow — A2A inbound

Same as above except:
- Step 1: External agent → POST /a2a → Gateway creates task in DB
- Step 2: Gateway → Kafka: `a2a.inbound` (CEO subscribes here)
- Step 12: Gateway streams SSE to external agent via Redis pub/sub

### Dead letter handling

Failed consumer after 3 retries → publish to `{topic}.dead_letter`.
Dashboard monitors dead letter topics and alerts if any message lands there.
**Never silently drop a failed message.**

---

## 11. Redis Architecture — Four Roles

**Redis is NOT the source of truth. PostgreSQL is.**
If Redis is wiped, the system recovers from PostgreSQL + Kafka without data loss.

| DB | Role | Key Pattern | TTL |
|----|------|-------------|-----|
| db:0 | Agent working memory (scratch pad) | `working:{agent_id}:{task_id}` | 4h |
| db:1 | Task state cache · rate limiting · token budget | `task_status:{id}` · `ratelimit:{id}:{window}` · `token_budget:{id}` | varies |
| db:2 | Real-time dashboard pub/sub · A2A SSE stream | `agent_activity:{agent_id}` | n/a |
| db:3 | Distributed locks · idempotency keys | `task_lock:{id}` · `idempotency:{key}` | 1h / 24h |

**db:2 note:** Both the Litestar WebSocket handler and the A2A Gateway subscribe to the
same `agent_activity:{agent_id}` Redis channel. One publisher, two subscriber types.

---

## 12. Database & Memory Schema

### PostgreSQL setup

- Version: PostgreSQL 16
- Extensions: `pgvector`, `uuid-ossp`
- Connection: async via Advanced Alchemy
- Migrations: Alembic only — no manual DDL ever

### Complete table list

| Table | Purpose |
|-------|---------|
| `agents` | Agent config, role, model, tool access, token budget |
| `tasks` | Every task submission — central audit anchor |
| `episodic_memory` | Past task history per agent + pgvector embeddings |
| `semantic_memory` | Accumulated facts per agent + pgvector embeddings |
| `llm_usage` | Every LLM call — tokens, cost, model |
| `audit_log` | Immutable event log — never updated, never deleted |
| `human_approvals` | Approval records for irreversible tool actions |
| `prompts` | Versioned system prompts per agent role |
| `prompt_benchmarks` | Fixed test cases for prompt quality measurement |

### Core table schemas

#### `agents`
```
id                    uuid PK
role                  varchar(50) NOT NULL     -- ceo|engineer|analyst|writer|qa|prompt_creator
name                  varchar(100) NOT NULL
system_prompt         text NOT NULL            -- loaded from prompts table at runtime
tool_access           text[] NOT NULL          -- allowed MCP tool names
kafka_topics          text[] NOT NULL
llm_model             varchar(100) NOT NULL
token_budget_per_task integer DEFAULT 50000
is_active             boolean DEFAULT true
created_at / updated_at timestamptz
```

#### `tasks`
```
id                    uuid PK
trace_id              uuid NOT NULL            -- groups sub-tasks from one user request
parent_task_id        uuid nullable FK tasks   -- CEO-delegated subtasks
assigned_agent_id     uuid FK agents
instruction           text NOT NULL
status                varchar(20) NOT NULL     -- queued|running|paused|completed|failed|escalated
source                varchar(20) DEFAULT 'human'  -- 'human' | 'a2a'
source_agent          varchar(200) nullable    -- A2A: external agent identifier
output                jsonb nullable
error                 text nullable
tokens_used           integer DEFAULT 0
created_at / started_at / completed_at timestamptz
```

#### `episodic_memory`
```
id                    uuid PK
agent_id              uuid FK agents
task_id               uuid FK tasks
summary               text NOT NULL
full_context          jsonb NOT NULL           -- full conversation turns + tool calls
outcome               varchar(20) NOT NULL     -- success|failed|partial|escalated
tools_used            text[]
tokens_used           integer
duration_seconds      integer
embedding             vector(1536)             -- Google embedding-001
importance_score      float DEFAULT 0.5

INDEX episodic_embedding_idx USING ivfflat (embedding vector_cosine_ops) WITH (lists=100)
INDEX episodic_agent_created ON (agent_id, created_at DESC)
```

#### `semantic_memory`
```
id                    uuid PK
agent_id              uuid FK agents
namespace             varchar(100) NOT NULL    -- e.g. 'project.policy', 'codebase.arch'
key                   varchar(200) NOT NULL
value                 text NOT NULL
confidence            float DEFAULT 1.0        -- degrades if contradicted
source_task_id        uuid nullable FK tasks
embedding             vector(1536)
updated_at            timestamptz

UNIQUE (agent_id, namespace, key)             -- upsert pattern
```

#### `human_approvals` *(new)*
```
id                    uuid PK
task_id               uuid FK tasks
agent_id              uuid FK agents
tool_name             varchar(100) NOT NULL    -- which tool was blocked
action_description    text NOT NULL            -- "Send email to x@y.com: subject"
status                varchar(20) DEFAULT 'pending'  -- pending|approved|rejected
requested_at          timestamptz DEFAULT now()
resolved_at           timestamptz nullable
resolved_by           varchar(100) nullable
```

#### `prompts` *(new — Prompt Creator Agent)*
```
id                    uuid PK
agent_role            varchar(50) NOT NULL
version               integer NOT NULL
content               text NOT NULL
benchmark_score       float nullable           -- set after benchmark run, 0-1
is_active             boolean DEFAULT false    -- only one active per role at a time
authored_by           varchar(50) NOT NULL     -- 'human' | 'prompt_creator_agent'
notes                 text nullable
created_at            timestamptz
approved_at           timestamptz nullable     -- null until human approves

UNIQUE (agent_role, version)
```

#### `prompt_benchmarks` *(new — Prompt Creator Agent)*
```
id                    uuid PK
agent_role            varchar(50) NOT NULL
input                 text NOT NULL            -- fixed test instruction
expected_criteria     jsonb NOT NULL           -- what a good response must contain
created_at            timestamptz
```

### Semantic recall query

```sql
SELECT summary, outcome, importance_score,
       1 - (embedding <=> $query_embedding) AS similarity
FROM episodic_memory
WHERE agent_id = $agent_id
ORDER BY embedding <=> $query_embedding
LIMIT 5;
```

### Embedding strategy

- Model: Google `embedding-001` via Gemini API (dimension: 1536)
- Generate async via Taskiq fire-and-forget task on every episodic/semantic write
- Never block task completion waiting for embedding
- Test the recall query with real embeddings in Phase 0 before agent code relies on it

---

## 13. Task Queue — Taskiq

```python
# nexus/taskiq_app.py
broker = AioKafkaBroker(
    bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
).with_result_backend(
    RedisAsyncResultBackend(settings.REDIS_URL)
)
```

### Task design rules

1. All tasks MUST be idempotent — running twice produces the same result
2. All parameters MUST be JSON-serializable Pydantic models
3. Tasks MUST accept `task_id: str` and `trace_id: str`
4. Tasks MUST have `retry_on_error=True`, `max_retries=3`, `timeout=3600`

Taskiq task signatures are designed to be Temporal-compatible from day one.
When migrating in Phase 4, the function body stays — only the decorator changes.

---

## 14. Testing Strategy

### Five-layer pyramid

| Layer | What | Speed | When |
|-------|------|-------|------|
| 1 — Unit | Infrastructure in isolation, mocked deps | <30s | Every commit |
| 2 — Behavior | Agent logic with mocked LLM, real infra structure | <2min | Every PR |
| 3 — E2E | Real infrastructure via Docker, real tasks | <10min | Before merge to main |
| 4 — Chaos | Kill services mid-task, assert graceful failure | slow | Weekly |
| 5 — Eval | LLM output quality scoring via LLM-as-judge | slow | Nightly |

### Layer 1 unit test targets

Memory read/write/recall · Kafka producer/consumer · API endpoints · Tool adapter
inputs/outputs · `require_approval()` guard behavior · A2A gateway routing ·
idempotency key logic · cost tracking · rate limiting · token budget enforcement

### Layer 2 behavior test rule

Give agent a fixed scenario with deterministic mocked LLM response.
Assert: correct tool called, memory written, Kafka topic published, budget checked,
approval triggered for irreversible tools.
**You are NOT testing LLM output quality — you are testing agent decision logic.**

### Layer 4 — chaos scenarios to cover

- Kafka unavailable → task fails cleanly (not silently hung)
- Redis wiped mid-task → agent recovers from PostgreSQL, no corrupt state
- LLM timeout → task fails with error message, not infinite wait
- Token budget exceeded → task paused, `human.input_needed` published
- Duplicate Kafka message → idempotency key prevents double-execution
- A2A inbound with invalid bearer token → 401, nothing published to Kafka

### Phase 2 gate — 50-task stress test

Before Phase 2 starts, run 50 consecutive tasks of increasing complexity on the
Phase 1 Engineer Agent. Pass rate must be ≥ 90%. Log all failures. Fix all failures.

---

## 15. Project Structure

```
nexus/
├── CLAUDE.md
├── docs/
│   ├── ARCHITECTURE.md                  ← system architecture & design fundamentals
│   ├── DECISIONS.md                     ← architecture decision records
│   ├── RISK_REVIEW.md                   ← risk assessment & phase gates
│   ├── BACKLOG.md                       ← scope creep capture
│   ├── CHANGELOG.md                     ← version history
│   ├── ERRORLOG.md                      ← bug tracking & prevention
│   └── archive/                         ← old planning documents
├── docker-compose.yml
├── docker-compose.test.yml
├── Makefile
├── .env.example
├── .gitignore
│
├── backend/
│   ├── pyproject.toml                   ← deps + ruff + mypy + pytest config
│   ├── Dockerfile
│   ├── alembic/
│   │   ├── versions/
│   │   └── env.py
│   │
│   └── nexus/
│       ├── __init__.py
│       ├── settings.py                  ← ALL config from env vars only
│       ├── app.py                       ← Litestar app factory
│       ├── taskiq_app.py                ← Taskiq broker
│       │
│       ├── api/
│       │   ├── health.py                ← GET /health — first endpoint built
│       │   ├── tasks.py
│       │   ├── agents.py
│       │   ├── approvals.py             ← GET /approvals · POST /approvals/{id}/approve
│       │   ├── websocket.py
│       │   └── router.py
│       │
│       ├── agents/
│       │   ├── base.py                  ← AgentBase — most critical class
│       │   ├── ceo.py
│       │   ├── engineer.py              ← first full implementation (Phase 1)
│       │   ├── analyst.py
│       │   ├── writer.py
│       │   ├── qa.py
│       │   └── prompt_creator.py        ← Phase 2
│       │
│       ├── tools/                       ← NEW — MCP integration (Phase 1)
│       │   ├── __init__.py
│       │   ├── adapter.py               ← wraps MCP package as Pydantic AI tools
│       │   ├── registry.py              ← per-role tool access map
│       │   └── guards.py               ← require_approval() + IrreversibleAction
│       │
│       ├── gateway/                     ← NEW — A2A protocol gateway (Phase 2)
│       │   ├── __init__.py
│       │   ├── routes.py                ← /.well-known/agent.json · POST /a2a · SSE
│       │   ├── outbound.py              ← A2A client for hiring external agents
│       │   ├── schemas.py               ← A2ATask, AgentCard, A2AEvent models
│       │   └── auth.py                  ← Bearer token validation
│       │
│       ├── kafka/
│       │   ├── topics.py                ← ALL topic constants — single source of truth
│       │   ├── schemas.py               ← KafkaMessage base + per-topic models
│       │   ├── producer.py
│       │   └── consumer.py
│       │
│       ├── memory/
│       │   ├── episodic.py
│       │   ├── semantic.py
│       │   ├── working.py               ← Redis db:0 scratch pad
│       │   └── embeddings.py            ← Google embedding-001
│       │
│       ├── llm/
│       │   ├── factory.py               ← ModelFactory
│       │   └── usage.py                 ← token tracking + cost logging
│       │
│       ├── db/
│       │   ├── models.py                ← SQLAlchemy models for all 9 tables
│       │   └── session.py
│       │
│       ├── redis/
│       │   └── clients.py               ← 4 clients, one per db role
│       │
│       └── tests/
│           ├── conftest.py
│           ├── unit/
│           ├── behavior/
│           └── e2e/
│
└── frontend/
    ├── package.json
    ├── vite.config.ts
    ├── tsconfig.json
    └── src/
        ├── api/                         ← generated from OpenAPI
        ├── components/
        │   ├── dashboard/
        │   ├── agents/
        │   ├── tasks/
        │   ├── approvals/               ← human approval queue UI
        │   └── meeting/
        ├── hooks/                       ← TanStack Query hooks
        ├── store/                       ← Zustand (UI state only)
        ├── ws/                          ← WebSocket context provider
        └── types/                       ← generated from OpenAPI
```

---

## 16. Coding Policy — Python Backend

Applies to all `backend/**/*.py`. Agents generating Python MUST follow these rules.

### MUST rules (CI enforced)

1. **Type hints everywhere.** All parameters, return types, class attributes. Use
   `from __future__ import annotations`. Never `Any` without an explanatory comment.

2. **Async/await consistently.** All I/O (DB, Kafka, Redis, HTTP, LLM, tools) must be
   async. No blocking calls in async context. Unavoidable sync → `asyncio.to_thread()`.

3. **task_id and trace_id propagation.** Every I/O function accepts and passes through
   both. Every log line includes both. This is how the system is debugged.

4. **Pydantic models at all boundaries.** API request/response, Kafka payloads, LLM
   tool inputs/outputs. No raw `dict` crossing module boundaries.

5. **Structured logging only.** `logger.info("event", extra={"task_id": task_id})`.
   `print()` is banned and fails CI.

6. **Settings via `settings` module only.** Never `os.environ` directly.
   No hardcoded URLs, ports, or secrets anywhere.

### NEVER rules

- `print()` for logging
- Hardcoded secrets, API keys, connection strings
- Synchronous I/O in async context
- Raw SQL strings with dynamic content
- Hardcoded topic strings — always use `Topics.CONSTANT`
- Calling MCP tools directly from agent code — always through the adapter + registry

---

## 17. Coding Policy — TypeScript Frontend

Applies to all `frontend/src/**/*.ts` and `*.tsx`.

### MUST rules

1. **Strict TypeScript.** `strict: true` in tsconfig. No `any`. All API types generated
   from OpenAPI — must match backend Pydantic models exactly.

2. **TanStack Query for all server state.** No `fetch()` in components. All API calls
   via hooks in `src/hooks/`. Cache invalidation explicit, never timed.

3. **Separate concerns.** Components render only. Business logic in hooks. API calls in
   `src/api/`. WebSocket in `src/ws/` context provider.

4. **Zustand for UI state only.** Not for server data. Only: active agent selection,
   sidebar state, theme, user preferences.

### NEVER rules

- `useEffect` for data fetching — use TanStack Query
- `any` type without justification
- Direct `fetch()` in components
- Hardcoded API URLs — use `import.meta.env.VITE_API_URL`

---

## 18. Coding Policy — Database

### MUST rules

1. **All schema changes via Alembic migrations.** No manual `ALTER TABLE`. Migration
   files are immutable once merged to main.

2. **Indexes for all FKs and WHERE clause fields.** Run `EXPLAIN ANALYZE` on any new
   query before merging. Paginate queries touching >10,000 rows.

3. **`task_id` on every table related to agent activity.** Non-negotiable.

### NEVER rules

- Delete columns — add `deprecated_at timestamptz`, stop writing, drop in a later migration
- Raw SQL with dynamic user or agent input
- Direct DDL in application code (migrations only)

---

## 19. Coding Policy — Kafka

### MUST rules

1. **Every message includes `task_id`, `trace_id`, `agent_id`, `timestamp`.**
   Enforced at schema level via `KafkaMessage`. Consumer rejects messages missing these.

2. **All consumers must be idempotent.** Kafka delivers at-least-once.
   Use Redis idempotency keys (`idempotency:{message_id}`) in every consumer.

3. **Failed messages go to dead letter topics.** After 3 retries → `{topic}.dead_letter`.
   Never silently drop.

4. **All topic names from `Topics` constants.** No hardcoded strings elsewhere.

### NEVER rules

- Create topics without adding to `Topics` class
- Silently drop failed messages
- Use Kafka as a database or rebuild state from topic replay alone

---

## 20. Agent Operational Policy

Seeded into each agent's `semantic_memory` at initialization under `project.policy`.

### MUST rules

1. **Check token budget before every LLM call.** At 90% → pause → publish to
   `human.input_needed`. Never silently exceed budget.

2. **Write episodic memory before publishing result.** If memory write fails → task
   is failed, not published. No exceptions to this ordering.

3. **Load relevant memory before starting work.** Query episodic memory for similar
   past tasks. Query semantic memory for project facts. Include both in LLM context.

4. **Limit tool call loops.** Maximum 20 tool calls per task. If limit reached →
   publish to `human.input_needed`. Prevents infinite reasoning loops.

5. **Publish heartbeat every 30 seconds.** To `agent.heartbeat`. If no heartbeat
   within 5 minutes of task assignment → task is auto-failed by the system.

### NEVER rules

1. **Never take irreversible actions without human approval.** Irreversible includes:
   sending emails, deleting files, pushing code, calling external APIs with side effects,
   hiring external agents. The `require_approval()` guard enforces this — agents cannot
   bypass it in their own logic.

2. **Never access tools outside your `tool_access` list.** Runtime check in AgentBase.
   Violation raises `ToolAccessDenied` and writes a security event to `audit_log`.

3. **Never fabricate sources or citations.** If search returns no results → say so.

4. **Never store secrets in memory tables.** API keys, passwords, tokens must never
   appear in `episodic_memory` or `semantic_memory`.

5. **Never auto-deploy a prompt version.** Prompt Creator Agent routes ALL proposals
   through `human.input_needed`. Human approval required every time.

---

## 21. Git & CI/CD Policy

### Branch naming

```
feature/{description}
fix/{description}
chore/{description}
agent/{task-id}/{description}    ← branches created by Engineer Agent
```

### Commit format (Conventional Commits — enforced by CI)

```
type(scope): description

Types:  feat | fix | chore | test | docs | refactor | perf
Scopes: backend | frontend | kafka | db | agents | tools | gateway | infra
```

Agents MUST follow this format when writing commits.

### PR rules

1. All changes via PR — no direct pushes to `main`
2. CI must pass: `ruff`, `mypy`, `pytest unit`, `pytest behavior`
3. PRs over 400 lines flagged for splitting
4. **Engineer Agent may open PRs but never merge them — human review required**

### CI pipeline

```
Every commit:   ruff check · mypy --strict · pytest tests/unit/
Every PR:       pytest tests/behavior/ · E2E smoke test · OpenAPI types up to date
Nightly:        pytest tests/e2e/ · LLM eval scoring run
```

---

## 22. Docker Compose — Local Dev

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: nexus
      POSTGRES_USER: nexus
      POSTGRES_PASSWORD: nexus_dev
    ports: ["5432:5432"]
    volumes: ["postgres_data:/var/lib/postgresql/data"]

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
    command: redis-server --save 60 1 --loglevel warning

  kafka:
    image: apache/kafka:3.7.0
    environment:
      KAFKA_NODE_ID: 1
      KAFKA_PROCESS_ROLES: broker,controller
      KAFKA_LISTENERS: PLAINTEXT://:9092,CONTROLLER://:9093
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://localhost:9092
      KAFKA_CONTROLLER_QUORUM_VOTERS: 1@localhost:9093
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
    ports: ["9092:9092"]

  backend:
    build: ./backend
    environment:
      DATABASE_URL: postgresql+asyncpg://nexus:nexus_dev@postgres:5432/nexus
      REDIS_URL: redis://redis:6379
      KAFKA_BOOTSTRAP_SERVERS: kafka:9092
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
      GOOGLE_API_KEY: ${GOOGLE_API_KEY}
      DAILY_SPEND_LIMIT_USD: "5.00"
    ports: ["8000:8000"]
    depends_on: [postgres, redis, kafka]
    volumes: ["./backend:/app"]

  frontend:
    build: ./frontend
    ports: ["5173:5173"]
    depends_on: [backend]
    volumes: ["./frontend:/app"]

volumes:
  postgres_data:
```

### Makefile

```makefile
up:             docker compose up -d
down:           docker compose down
logs:           docker compose logs -f
migrate:        docker compose exec backend alembic upgrade head
seed:           docker compose exec backend python -m nexus.db.seed
test-unit:      docker compose exec backend pytest tests/unit/ -v
test-behavior:  docker compose exec backend pytest tests/behavior/ -v
test-e2e:       docker compose -f docker-compose.test.yml run --rm test
test-all:       make test-unit && make test-behavior && make test-e2e
kafka-test:     docker compose exec backend python -m nexus.kafka.health_check
kafka-topics:   docker compose exec kafka kafka-topics.sh --bootstrap-server localhost:9092 --list
shell-db:       docker compose exec postgres psql -U nexus nexus
shell-redis:    docker compose exec redis redis-cli
```

---

## 23. Prevention Rules — Active Risks

Every phase has a gate. The next phase cannot start until all gates for the current
phase are cleared. Write your Definition of Done before starting any task.

### Risk 1 — CRITICAL: Building orchestration before the loop works

**What happens:** You build CEO delegation, meeting rooms, QA pipeline — then discover
the core agent loop has a bug every agent inherits. Weeks of work thrown away.

**Prevention:**
- Phase 1 produces ONE working agent only. No multi-agent until stress test passes.
- 50-task stress test at end of Phase 1. Pass rate ≥ 90% required before Phase 2.

**Gate:** Phase 2 BLOCKED until 50-task loop test passes.

---

### Risk 2 — CRITICAL: Cost explosion from unbounded agent loops

**What happens:** One multi-agent task burns $50 in tokens before you notice.

**Prevention:**
- Hard $5/day spending cap enforced via Redis before EVERY LLM call.
- Per-task token budget — halt and ask for approval at 90%.
- Token budget enforcement must be live before any real LLM call runs.

**Gate:** Token budget live before first real task.

---

### Risk 3 — CRITICAL: Vague system prompts producing garbage outputs

**What happens:** CEO decomposes tasks incorrectly. Every downstream agent gets wrong
subtasks. You blame the architecture when the prompt is the problem.

**Prevention:**
- Manual prompt testing (2+ hours per agent in Claude.ai) BEFORE writing the Python class.
- Prompts versioned in `prompts` table — not hardcoded in Python.
- Prompt Creator Agent iterates prompts systematically in Phase 2.

**Gate:** Manual prompt test session documented before each agent is coded.

---

### Risk 4 — CRITICAL: Agent takes irreversible action before approval flow exists

**What happens:** Engineer Agent pushes a commit or deletes a file during testing.
You planned human-in-the-loop for Phase 2. Too late.

**Prevention:**
- `require_approval()` guard and `human_approvals` table built in **Phase 0**, not Phase 2.
- All irreversible tools disabled by default in Phase 1 testing.
- Approval flow is infrastructure, not a feature.

**Gate:** Approval flow and `human_approvals` table exist before any agent runs.

---

### Risk 5 — HIGH: Agents fail silently with no observability

**What happens:** Agent hangs in a tool call. No error. No log. Task sits "running"
forever. Debugging becomes archaeology.

**Prevention:**
- Structured JSON logging with `task_id` on every line from day one. `print()` banned.
- Agent heartbeat every 30s. Task auto-fail if no heartbeat within 5 minutes.
- `make kafka-test` health check before every agent test session.

**Gate:** Logging structure defined and enforced by CI before first agent runs.

---

### Risk 6 — HIGH: Memory schema migration hell mid-build

**What happens:** You start writing agents, realize the schema needs a new column,
run a migration, but the running agent has the old model loaded. Or embedding dimension
is wrong. Schema changes mid-phase are expensive.

**Prevention:**
- Full schema (all 9 tables, all indexes) deployed in Phase 0.
- Populate with synthetic test data. Test embedding recall query with real embeddings.

**Gate:** Full schema deployed and tested before Phase 1 starts.

---

### Risk 7 — HIGH: Kafka instability derailing Phase 0

**What happens:** KRaft mode has configuration subtleties. Kafka is flaky in dev.
Every agent test is unreliable. Days wasted debugging infrastructure.

**Prevention:**
- Use exact Docker image and config from §22. Don't customize until it works.
- `make kafka-test` passes before any agent uses Kafka.
- If Kafka is unstable after 1 day of setup: switch to Redis Streams for Phase 1.
  Your `Topics` constants and `KafkaMessage` schema stay identical — only the broker changes.

**Gate:** `make kafka-test` passes before any agent consumer runs.

---

### Risk 8 — MEDIUM: Scope creep

**What happens:** "While I'm here let me add the meeting room." Six weeks in, you have
40% of 10 things and 100% of nothing.

**Prevention:**
- `BACKLOG.md` created on Day 1 as the capture mechanism. Ideas go there, not into code.
- Each phase has a one-sentence Definition of Done. Nothing ships until DoD is met.
- Phase 0 DoD: `make up` works, `/health` returns 200. That's it.
- Phase 1 DoD: one agent completes one real task visible in dashboard. That's it.

**Gate:** `BACKLOG.md` exists before any code is written.

---

## 24. Build Roadmap — Phased Plan

### Phase 0 — Foundation (Week 1, Days 1–3)

Goal: working skeleton. Nothing smart. Everything starts and connects.

**Day 1:**
- [ ] Create full directory structure from §15
- [ ] Create `BACKLOG.md` ← do this first
- [ ] Write `pyproject.toml` with all pinned dependencies
- [ ] Write `settings.py` reading all config from env vars
- [ ] Write `topics.py` with all Kafka constants (including A2A and Prompt topics)
- [ ] Configure ruff + mypy in `pyproject.toml`

**Day 2–3:**
- [ ] Write `docker-compose.yml` (5 services)
- [ ] Write `Makefile` with all commands
- [ ] Implement `GET /health` (checks DB, Redis, Kafka connectivity)
- [ ] Write `make kafka-test` health check script
- [ ] Run full schema migration — all 9 tables from §12
- [ ] Build `require_approval()` guard + `human_approvals` table ← prevention rule 4
- [ ] Set up CI (ruff + mypy + pytest skeleton)

**Definition of done:**
`make up` starts all 5 services with no errors. `curl localhost:8000/health` returns all
green. `make kafka-test` passes. `make migrate` creates all 9 tables. Frontend loads
at localhost:5173. `BACKLOG.md` exists.

---

### Phase 1 — Single Agent Loop (Weeks 2–3)

Goal: one agent completes one real task end-to-end.

**Week 2 — Infrastructure:**
- [ ] `AgentBase` with full guard chain: idempotency → budget → load memory →
  `handle_task` → write memory → publish → broadcast
- [ ] `AgentMemory` — `load_context()` + `write_episode()` with async embedding generation
- [ ] `AgentWorkingMemory` — Redis db:0 scratch pad
- [ ] `ModelFactory` — Claude + Gemini abstraction
- [ ] Token budget enforcement via Redis db:1
- [ ] Heartbeat loop (30s) + task auto-fail on 5min silence
- [ ] Human approval flow: suspends execution, publishes to `human.input_needed`
- [ ] Approval UI: pending list + approve/reject buttons
- [ ] Unit tests for AgentBase guard chain

**Week 3 — First Agent:**
- [ ] Audit MCP package: verify type hints + docstrings on all functions to be wrapped
- [ ] Write `nexus/tools/adapter.py`, `registry.py`, `guards.py`
- [ ] Manual prompt testing session (2+ hours in Claude.ai) — BEFORE writing `engineer.py`
- [ ] `EngineerAgent` extending `AgentBase`
- [ ] Test `web_search` tool individually before wiring to agent
- [ ] Thin `CEOAgent` — routes tasks to Engineer (no decomposition yet)
- [ ] Basic dashboard: submit task → live WebSocket status → see result

**Phase 2 gate — 50-task stress test:**
- [ ] 50 consecutive tasks of increasing complexity
- [ ] Pass rate ≥ 90%
- [ ] All failures logged and fixed
- [ ] Cost baseline documented in §25

**Definition of done:**
Submit "Research Python async patterns and write a working code example with tests."
Engineer Agent completes it. Result in DB. Episodic memory written. Cost logged in
`llm_usage`. Dashboard shows output. 50-task stress test passes at ≥ 90%.

---

### Phase 2 — Multi-Agent + Prompt Creator + A2A Inbound (Weeks 4–8)

Goal: full company collaborating. External agents can hire NEXUS.

**Weeks 4–5 — Multi-agent:**
- [x] Manual prompt testing for each new agent before coding
- [x] `AnalystAgent`, `WriterAgent`, `QAAgent` extending `AgentBase`
- [x] CEO full task decomposition logic
- [x] CEO → delegate → specialists → CEO aggregation → QA review flow
- [x] Meeting room pattern (temporary `meeting.room.{task_id}` topic)
- [x] Agent memory context loading (recall past similar tasks)
- [x] Full task trace view in dashboard

**Week 6 — All task types:**
- [x] All 4 task categories working end-to-end
- [x] `make test-e2e` passing

**Weeks 6–7 — Prompt Creator Agent:**
- [x] `prompts` + `prompt_benchmarks` tables migration
- [x] Migrate existing system prompts into `prompts` table (version=1, authored_by='human')
- [x] Write 10 benchmark test cases per agent role
- [x] `PromptCreatorAgent` — reads failures → drafts → benchmarks → proposes via approval
- [x] Prompt approval UI: diff view + benchmark scores + approve/reject
- [x] First improvement run against Engineer Agent failures from Phase 1

**Weeks 7–8 — A2A Inbound:**
- [x] `nexus/gateway/` directory with all 4 files
- [x] `GET /.well-known/agent.json` serving Agent Card
- [x] `POST /a2a` inbound task handler with DB persistence
- [x] `GET /a2a/{id}/events` SSE endpoint
- [x] CEO routing logic for `a2a.inbound`
- [x] Integration test: simulate external A2A call end-to-end

**Definition of done:**
"Write a competitive analysis of [X] and draft an email summary." CEO delegates →
Analyst researches → Writer drafts → QA reviews → output delivered. External A2A
test call completes with SSE stream. Prompt Creator produces a measurably improved
prompt for at least one agent.

---

### Phase 3 — Hardening + A2A Outbound (Weeks 9–12)

- [ ] Chaos tests passing for all scenarios in §14
- [ ] Dead letter queue monitoring in dashboard with alerts
- [ ] `tool_hire_external_agent` in MCP adapter (outbound A2A, requires approval)
- [ ] Bearer token issuance for external A2A callers
- [ ] Per-token rate limiting via Redis db:1
- [ ] LLM eval scoring baseline established
- [ ] Full audit log dashboard view
- [ ] All CI layers passing
- [ ] `make migrate` runs cleanly from scratch on fresh DB
- [ ] README for the project

**Definition of done:**
System survives infrastructure failures gracefully. NEXUS can hire an external test
A2A agent and receive results. All CI passes. Daily spend never exceeds $5.

---

### Phase 4 — Scale to Service (Month 3+)

Not starting until Phase 3 Definition of Done is fully met.

- [ ] Multi-user / multi-tenant support
- [ ] Per-tenant Agent Cards (each user's company discoverable via A2A)
- [ ] Temporal for long-running workflows (>1 hour tasks)
- [ ] NEXUS Agent Marketplace (browse external A2A specialist agents)
- [ ] Cross-company task billing
- [ ] Custom agent role creator (no-code configuration)
- [ ] LangFuse or Braintrust for eval tracking
- [ ] Kubernetes deployment manifests

---

## 25. Open Questions & Decisions Log

### Decided ✅

| Decision | Choice | Date | Reason |
|----------|--------|------|--------|
| AI Framework | Pydantic AI | 2026-03 | Lightweight, async-native, no conflict with Kafka |
| Task Queue v1 | Taskiq | 2026-03 | Async-native, Kafka broker backend, Litestar compatible |
| Task Queue v2 | Temporal (Phase 4) | 2026-03 | Durable workflows >1 hour |
| LLM Providers | Claude + Gemini | 2026-03 | Abstracted via ModelFactory |
| v1 Deployment | Docker Compose | 2026-03 | Solo user, local dev |
| Orchestration | Kafka (not LangGraph) | 2026-03 | Already designed better; LangGraph would conflict |
| MCP integration | Python pkg → Pydantic AI adapter | 2026-03 | Direct import, cleanest path |
| Embedding model | Google embedding-001 | 2026-03 | Already using Gemini; no third provider needed |
| Frontend components | Shadcn/ui | 2026-03 | Composable, Tailwind-based |
| A2A protocol | Google A2A (April 2025) | 2026-03 | Open standard, aligns with scale vision |
| A2A architecture | Gateway service at boundary only | 2026-03 | Agents unchanged; gateway translates |

### Open ❓

| Question | Options | Priority |
|----------|---------|----------|
| Log aggregation | File-based JSON vs Loki vs OpenSearch | Medium — decide before Phase 3 |
| Secrets management | `.env` vs Docker secrets vs Vault | Low for v1 solo; required before multi-user |
| Agent naming | Generic roles vs named personas | Low — cosmetic |
| Kafka fallback | Stay with Kafka vs Redis Streams for Phase 1 | Decide on Day 2 of setup |

### Needs further design before Phase 1 code starts

- [ ] **MCP package audit** — verify all functions to be wrapped have type hints +
  docstrings. Add to MCP package if missing. Prerequisite for `tools/adapter.py`.
- [ ] **Engineer Agent system prompt** — write and manually test for 2+ hours in
  Claude.ai before writing `engineer.py`. Document the prompt in `prompts` table seed.
- [ ] **Semantic memory contradiction handling** — when two tasks produce conflicting
  facts, which wins? Options: newest wins, highest confidence wins, human resolves.
- [ ] **Meeting room termination** — what signals a meeting is over? CEO timeout,
  explicit vote, or unanimous agreement signal?
- [ ] **Embedding async timing** — confirm Taskiq fire-and-forget for embedding is
  acceptable (agent context loads without embeddings for first seconds of a new task).

---

*Last updated: 2026-03*
*Owner: Nexus Project*
*Document version: 0.5*

*Changes in v0.5:*
*— Added §8: MCP Tools Integration (adapter pattern, registry, guards, full tool table)*
*— Added §9: A2A Gateway (inbound/outbound/multi-tenant, Agent Card, security plan)*
*— Added §23: Prevention Rules (8 active risks with phase gates)*
*— §7: Added Prompt Creator Agent to full roster with complete spec*
*— §10: Added A2A and Prompt Creator Kafka topics to registry*
*— §12: Added human_approvals, prompts, prompt_benchmarks tables; source/source_agent to tasks*
*— §15: Added nexus/tools/ and nexus/gateway/ to project structure*
*— §24: Rebuilt all phase roadmaps to incorporate MCP (Phase 1), A2A inbound +*
*  Prompt Creator (Phase 2), A2A outbound (Phase 3), multi-tenant A2A (Phase 4)*
*— §25: Resolved MCP integration method, embedding model, frontend components,*
*  A2A protocol and architecture decisions; cleaned up open questions*

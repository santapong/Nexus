# ARCHITECTURE.md — NEXUS System Architecture & Design Fundamentals

> This document explains how NEXUS works at a systems level.
> For coding rules, see [AGENTS.md](AGENTS.md). For the full spec, see [CLAUDE.md](CLAUDE.md).
> For decision rationale, see [DECISIONS.md](DECISIONS.md).

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Three Protocol Layers](#2-three-protocol-layers)
3. [Agent Architecture](#3-agent-architecture)
4. [Task Lifecycle](#4-task-lifecycle)
5. [Kafka Event Bus Design](#5-kafka-event-bus-design)
6. [Data Architecture](#6-data-architecture)
7. [Memory System](#7-memory-system)
8. [Tool System (MCP)](#8-tool-system-mcp)
9. [A2A Gateway](#9-a2a-gateway)
10. [Prompt Evolution System](#10-prompt-evolution-system)
11. [Resilience & Health](#11-resilience--health)
12. [Security Model](#12-security-model)
13. [Deployment Architecture](#13-deployment-architecture)
14. [KeepSave Integration](#14-keepsave-integration)

---

## 1. System Overview

NEXUS is an **Agentic AI Company-as-a-Service** — a platform where every department of a
digital company is staffed by an AI agent. Agents communicate through Apache Kafka, access
tools via MCP, and are callable by external systems via the A2A protocol.

```mermaid
flowchart TD
    subgraph EXT["**External Boundary**"]
        USER[Users / Dashboard - React]
        EXTAGENT[External Agents]
    end

    subgraph APILAYER["**API Layer — Litestar**"]
        REST[/api/tasks · /api/agents<br/>/api/approvals · /api/prompts/]
        A2AROUTES[/.well-known/agent.json<br/>/a2a/tasks · SSE/]
    end

    subgraph BUS["**Event Bus — Apache Kafka (KRaft)**"]
        TQ[task.queue]
        AC[agent.commands]
        AR[agent.responses]
        TR[task.results]
        TRQ[task.review_queue]
        DR[director.review]
        MR[meeting.room]
        HB[agent.heartbeat]
        HIN[human.input_needed]
        A2A[a2a.inbound]
        PIR[prompt.improvement_requests]
        AUDIT[audit.log · memory.updates]
    end

    subgraph RUNTIME["**Agent Runtime — Pydantic AI**"]
        BASE[AgentBase<br/>guard chain + lifecycle]
        CEO[CEO — plan + decompose + aggregate]
        DIRECTOR[Director — synthesizer + loop guard + security review]
        ENGINEER[Engineer — code, debug]
        ANALYST[Analyst — research, data]
        WRITER[Writer — content, emails]
        QA[QA — output review]
        PROMPT[Prompt Creator — meta-agent]
    end

    subgraph TOOLS["**Tools Layer — MCP Adapter**"]
        ROTOOLS[web_search · web_fetch · file_read<br/>code_execute · memory_read]
        IRREV[file_write⚠ · git_push⚠ · send_email⚠<br/>hire_external_agent⚠]
    end

    subgraph STORE["**Persistence**"]
        PG[(PostgreSQL 16 + pgvector<br/>source of truth · 24+ tables + RLS)]
        RDS[(Redis 7 · 4 dbs<br/>working memory · pubsub · budget · locks)]
        TMP[(Temporal Server<br/>durable workflows)]
    end

    USER -->|REST + WebSocket| REST
    EXTAGENT -->|HTTP + Bearer Auth| A2AROUTES

    APILAYER ==>|publish| BUS
    BUS ==>|consume| RUNTIME

    BASE --- CEO
    BASE --- DIRECTOR
    BASE --- ENGINEER
    BASE --- ANALYST
    BASE --- WRITER
    BASE --- QA
    BASE --- PROMPT

    RUNTIME --> TOOLS
    RUNTIME --> STORE

    classDef core fill:#1e40af,stroke:#1e3a8a,color:#fff
    classDef integ fill:#0891b2,stroke:#0e7490,color:#fff
    classDef ext fill:#64748b,stroke:#475569,color:#fff
    classDef danger fill:#dc2626,stroke:#991b1b,color:#fff
    classDef store fill:#7c3aed,stroke:#5b21b6,color:#fff

    class USER,EXTAGENT ext
    class REST,A2AROUTES,BASE,CEO,DIRECTOR,ENGINEER,ANALYST,WRITER,QA,PROMPT core
    class TQ,AC,AR,TR,TRQ,DR,MR,HB,HIN,A2A,PIR,AUDIT,ROTOOLS integ
    class IRREV danger
    class PG,RDS,TMP store
```

### Architectural Principles

```mermaid
mindmap
  root((NEXUS<br/>Principles))
    Observable
      Every message via Kafka
      Replayable + debuggable
      Structured JSON logs
      OpenTelemetry traces
    Stateless agents
      No in-memory state
      State in Redis or Postgres
      Safe restart anytime
    Humans in the loop
      Irreversible → require_approval
      human_approvals table
      human.input_needed Kafka topic
    Protocol separation
      Kafka — internal A2A
      MCP — agent → tools
      A2A — external agents
    Fail safely
      Budget caps $5/day
      Round + tool limits
      Heartbeat auto-fail
    Plan before execute
      CEO risk assessment
      Director security review
    Enterprise security
      HMAC-signed Kafka
      PII sanitization
      SOPS + KeepSave secrets
    Crash-consistent
      Orphaned task recovery
      Graceful shutdown drain
    Circuit-broken
      Sliding window per provider
      Health-score routing
```

### Design Philosophy

1. **Observable by default** — Every message flows through Kafka, making the entire system replayable and debuggable
2. **Stateless agents** — No in-memory state between tasks; all state in Redis (volatile) or PostgreSQL (durable)
3. **Humans in the loop** — Irreversible actions always require explicit human approval
4. **Protocol separation** — Kafka (internal), MCP (tools), A2A (external) never overlap
5. **Fail safely** — Budget caps, round limits, timeouts, and auto-fail on silence
6. **Plan before execute** — CEO creates risk-assessed execution plan before decomposing tasks
7. **Enterprise security** — HMAC-signed Kafka messages, PII sanitization, Director security review
8. **Crash-consistent** — Orphaned task recovery on startup, graceful shutdown with task draining
9. **Circuit-broken** — Sliding window health scoring per LLM provider, automatic failover

---

## 2. Three Protocol Layers

NEXUS uses three distinct protocols. Understanding their boundaries is critical:

| Protocol | Purpose | Direction | Transport | Scope |
|----------|---------|-----------|-----------|-------|
| **Kafka** | Agent-to-agent communication | Internal only | aiokafka | Task decomposition, delegation, results, debates |
| **MCP** | Agent-to-tool access | Agent → external service | Python package import | Web search, file I/O, code execution, email |
| **A2A** | External agent interop | Bidirectional (inbound Phase 2) | HTTP + Bearer auth | External agents submit tasks to NEXUS |

### Why Three Protocols?

**Kafka** provides ordered, persistent, replayable messaging between agents. It's the "conference room."

**MCP** gives agents hands — the ability to interact with the real world (files, web, email). MCP tools are wrapped in Pydantic AI functions via `adapter.py`, with per-role access control via `registry.py` and approval gates via `guards.py`.

**A2A** sits at the boundary. External requests arrive via HTTP, get translated into Kafka messages, and flow through the same pipeline as human-submitted tasks.

> **Rule:** These protocols never compete. A message is Kafka OR MCP OR A2A — never two at once.

---

## 3. Agent Architecture

### AgentBase — The Foundation

Every agent extends `AgentBase`, which provides the guard chain — a sequence of checks
that runs before and after every task:

```mermaid
flowchart TD
    MSG([Message arrives from Kafka]):::ext
    IDEM[Idempotency check<br/>Redis db:3]:::core
    SKIP{{Duplicate?}}:::core
    SKIPEND([Skip — already processed]):::ext
    COUNTER[Reset tool call counter<br/>0/20 for this task]:::core
    HOTPROMPT[Hot-reload prompt from DB<br/>check system_prompt changed]:::core
    BUDGET[Budget check<br/>Redis db:1 · 90% threshold]:::core
    PAUSE([Pause → human.input_needed]):::danger
    AUDIT1[Audit: task_received<br/>audit_log table]:::core
    EPI[Load episodic memory<br/>pgvector similar tasks]:::store
    SEM[Load semantic memory<br/>pgvector project facts]:::store
    HANDLE[handle_task<br/>subclass implements]:::core
    VALIDATE[Validate output<br/>secret detection · size · empty]:::core
    PII[PII sanitization<br/>API keys · emails · SSNs · JWTs]:::danger
    EPIWRITE[Write episodic memory]:::store
    AUDIT2[Audit: task_completed<br/>duration · tokens · status]:::core
    PUBLISH[Publish response<br/>Kafka agent.responses]:::core
    WS[Broadcast via WebSocket<br/>dashboard real-time view]:::integ
    CLEAR[Clear working memory<br/>Redis db:0 cleanup]:::core
    DONE([Done]):::ext

    MSG --> IDEM --> SKIP
    SKIP -->|yes| SKIPEND
    SKIP -->|no| COUNTER --> HOTPROMPT --> BUDGET
    BUDGET -->|over budget| PAUSE
    BUDGET -->|ok| AUDIT1 --> EPI --> SEM --> HANDLE
    HANDLE --> VALIDATE --> PII --> EPIWRITE --> AUDIT2 --> PUBLISH --> WS --> CLEAR --> DONE

    classDef core fill:#1e40af,stroke:#1e3a8a,color:#fff
    classDef integ fill:#0891b2,stroke:#0e7490,color:#fff
    classDef ext fill:#64748b,stroke:#475569,color:#fff
    classDef danger fill:#dc2626,stroke:#991b1b,color:#fff
    classDef store fill:#7c3aed,stroke:#5b21b6,color:#fff
```

### Agent Roster

| Agent | Role | Kafka Topics | Tools |
|-------|------|-------------|-------|
| **CEO** | Orchestrator — plans, decomposes, aggregates | `task.queue`, `a2a.inbound` | planning tools |
| **Director** | Synthesizer — loop prevention, security review | `director.review` | web_search, file_read |
| **Engineer** | Code & debugging | `agent.commands` | web_search, file_read, file_write⚠, code_execute, git_push⚠ |
| **Analyst** | Research & analysis | `agent.commands` | web_search, web_fetch, file_write |
| **Writer** | Content & docs | `agent.commands` | web_search, file_read, send_email⚠ |
| **QA** | Output review | `task.review_queue` | — |
| **Prompt Creator** | Improve prompts | `prompt.improvement_requests` | memory_read |

### LLM Provider Architecture

Agents use the **Universal ModelFactory** — a prefix-based registry that resolves model names to providers:

```
MODEL_ENGINEER=groq:llama-3.3-70b-versatile  →  Groq provider
MODEL_CEO=claude-3-5-sonnet-20241022          →  Anthropic (auto-detected)
MODEL_QA=gemini-2.0-flash                     →  Gemini (auto-detected)
MODEL_ANALYST=openai:gpt-4o                   →  OpenAI
MODEL_WRITER=ollama:llama3.2                  →  Ollama (local)
```

Supported providers: Anthropic, Google Gemini, OpenAI, Groq, Mistral, Ollama, any OpenAI-compatible endpoint, and `test:` (zero-cost testing).

**Fallback chains:** Each agent role has configurable fallback models via `MODEL_{ROLE}_FALLBACKS` env vars. `ModelFactory.get_model_with_fallbacks(role)` wraps the primary model with Pydantic AI's `FallbackModel`. If the primary fails (rate limit, timeout, API down), the next model in the chain is tried automatically. See ADR-019.

---

## 4. Task Lifecycle

### Canonical task flow — sequenceDiagram

```mermaid
sequenceDiagram
    autonumber
    actor Human as Human / Dashboard
    participant API as Litestar API
    participant K as Kafka
    participant CEO
    participant Spec as Specialists
    participant DIR as Director
    participant QA
    participant PG as PostgreSQL
    participant R as Redis pub/sub

    Human->>API: POST /api/tasks
    API->>PG: INSERT task (queued)
    API->>K: publish task.queue
    K->>CEO: consume
    CEO->>CEO: create execution plan<br/>(risk + security)
    CEO->>CEO: decompose with dependencies
    CEO->>K: publish agent.commands × N
    K->>Spec: consume (per role)
    Spec->>Spec: load memory · LLM + MCP tools
    Spec->>K: agent.responses (HMAC + PII-clean)
    K->>CEO: aggregate
    CEO->>K: publish director.review
    K->>DIR: consume
    DIR->>DIR: security review vs plan
    DIR->>DIR: synthesize best result
    DIR->>K: publish task.review_queue
    K->>QA: consume
    alt QA approves
        QA->>K: publish task.results
    else QA rejects
        QA->>K: publish agent.commands (rework w/ feedback)
    end
    K->>API: consume task.results
    API->>PG: UPDATE task (completed)
    API->>R: pub agent_activity:{task_id}
    R-->>Human: WebSocket → dashboard
```

### Simple Task (single agent)

```mermaid
flowchart LR
    U[User]:::ext --> A[POST /api/tasks]:::core
    A --> DB[(DB insert)]:::store
    A --> TQ[Kafka task.queue]:::core
    TQ --> CEO:::core
    CEO --> AC[agent.commands<br/>target: engineer]:::core
    AC --> ENG[Engineer]:::core
    ENG --> AR[agent.responses]:::core
    AR --> RC[Result consumer]:::core
    RC --> TRQ[task.review_queue]:::core
    TRQ --> QA:::core
    QA --> TR[task.results]:::core
    TR --> DASH[Dashboard]:::ext

    classDef core fill:#1e40af,stroke:#1e3a8a,color:#fff
    classDef ext fill:#64748b,stroke:#475569,color:#fff
    classDef store fill:#7c3aed,stroke:#5b21b6,color:#fff
```

### Complex Task (multi-agent with decomposition)

```mermaid
flowchart TD
    U[User]:::ext --> POST[POST /api/tasks]:::core
    POST --> TQ[Kafka task.queue]:::core --> CEO[CEO]:::core
    CEO --> PLAN[Create EXECUTION PLAN<br/>risk · security · approvals]:::core
    PLAN --> DECOMP[Decompose into subtasks<br/>with dependencies]:::core
    DECOMP --> RWM[(Redis · working memory<br/>tracking + plan)]:::store
    DECOMP --> AC[Kafka agent.commands × N<br/>parallel where unblocked]:::core
    AC --> S1[Specialist 1]:::core
    AC --> S2[Specialist 2]:::core
    AC --> SN[Specialist N]:::core
    S1 --> RESP[agent.responses<br/>HMAC + PII-sanitized]:::core
    S2 --> RESP
    SN --> RESP
    RESP --> AGG[CEO aggregates + dispatch dependents]:::core
    AGG --> DR[Kafka director.review<br/>aggregated + plan]:::core
    DR --> DIR[Director<br/>security review vs plan<br/>synthesize best result]:::core
    DIR --> TRQ[task.review_queue]:::core
    TRQ --> QA:::core
    QA -->|approve| TR[task.results]:::core
    QA -.->|reject| AC

    classDef core fill:#1e40af,stroke:#1e3a8a,color:#fff
    classDef ext fill:#64748b,stroke:#475569,color:#fff
    classDef store fill:#7c3aed,stroke:#5b21b6,color:#fff
```

### A2A Task (external agent)

```mermaid
flowchart LR
    EXT[External Agent]:::ext -->|POST /a2a/tasks<br/>Bearer auth| GW[A2A Gateway]:::integ
    GW --> CHK{validate<br/>token + skill}:::integ
    CHK -->|ok| A2AT[Kafka a2a.inbound]:::core
    CHK -->|deny| ERR[401 Unauthorized]:::danger
    A2AT --> CEO[CEO — normal pipeline]:::core
    CEO --> RESULT[task.results]:::core
    RESULT -.->|GET /a2a/tasks/&#123;id&#125;/status| EXT
    RESULT -.->|SSE /a2a/tasks/&#123;id&#125;/events| EXT

    classDef core fill:#1e40af,stroke:#1e3a8a,color:#fff
    classDef integ fill:#0891b2,stroke:#0e7490,color:#fff
    classDef ext fill:#64748b,stroke:#475569,color:#fff
    classDef danger fill:#dc2626,stroke:#991b1b,color:#fff
```

---

## 5. Kafka Event Bus Design

### Topic Registry

All topics are defined in `kafka/topics.py` — never use string literals:

| Topic | Producer | Consumer | Key | Purpose |
|-------|----------|----------|-----|---------|
| `task.queue` | API | CEO | task_id | New tasks from users |
| `agent.commands` | CEO | Specialists | agent_id | Task assignments |
| `agent.responses` | Agents | Result consumer | task_id | Task outputs |
| `task.results` | QA | API/dashboard | task_id | Final results |
| `task.review_queue` | Director | QA | task_id | QA review queue |
| `director.review` | CEO | Director | task_id | Aggregated output for synthesis |
| `meeting.room` | Meeting room | CEO + agents | meeting_id | Multi-agent debates |
| `agent.heartbeat` | All agents | Health monitor | agent_id | Liveness signals |
| `human.input_needed` | Guards | Dashboard | task_id | Approval requests |
| `a2a.inbound` | A2A gateway | CEO | task_id | External tasks |
| `prompt.improvement_requests` | API/trigger | Prompt Creator | task_id | Prompt improvement |
| `audit.log` | All | Logger | task_id | Audit trail |
| `memory.updates` | Agents | Memory service | agent_id | Memory writes |

### Guarantees

- **At-least-once delivery** — idempotency keys in Redis db:3 prevent duplicate processing
- **Ordered within partition** — messages keyed by task_id or agent_id stay in order
- **KRaft mode** — no ZooKeeper dependency (ADR-007)

---

## 6. Data Architecture

### PostgreSQL (Source of Truth)

24 tables with pgvector extension, RLS policies, and embedding search:

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `tasks` | All tasks (parent + subtasks) | id, instruction, status, assigned_agent_id, parent_task_id |
| `agents` | Registered agents | id, role, system_prompt, model, status |
| `llm_usage` | Token/cost tracking per call | task_id, model, tokens_in, tokens_out, cost_usd |
| `human_approvals` | Approval queue | task_id, agent_id, tool_name, approved, resolved_by |
| `episodic_memory` | Agent experience records | agent_id, task_id, summary, outcome, embedding |
| `semantic_memory` | Project knowledge facts | namespace, key, value, confidence, embedding |
| `audit_log` | All system events | task_id, actor, action, details |
| `prompts` | Versioned agent prompts | agent_role, version, content, is_active, benchmark_score |
| `prompt_benchmarks` | Test cases for prompts | agent_role, input, expected_criteria |
| `dead_letters` | Failed Kafka messages after 3 retries | topic, message_id, payload, error, retry_count |
| `a2a_tokens` | Bearer tokens for external A2A callers | token_hash, name, allowed_skills, rate_limit_rpm |
| `eval_results` | LLM-as-judge quality scores | task_id, overall_score, dimension scores, judge_model |
| `oauth_accounts` | OAuth2 provider accounts | user_id, provider, provider_user_id, tokens |
| `webhook_subscriptions` | Webhook notification URLs | workspace_id, url, events, secret_hash |
| `task_schedules` | Cron-based recurring tasks | workspace_id, cron_expression, instruction, next_run_at |
| `model_benchmarks` | Model quality/cost/speed comparison | agent_role, model_name, score, latency_ms, cost |
| `provider_health` | LLM provider health metrics | provider, latency_p50/p99, error_rate, window |
| `agent_cost_alerts` | Per-agent daily budget limits | agent_id, daily_limit_usd, alert_threshold_pct |

### Redis (Speed Layer — 4 Databases)

| DB | Purpose | Key Pattern | TTL |
|----|---------|-------------|-----|
| db:0 | Agent working memory | `wm:{task_id}:{agent_id}` | Task lifetime |
| db:1 | Token budgets | `token_budget:{task_id}`, `daily_spend:{date}` | 24h |
| db:2 | Pub/Sub channels | `agent_activity:{agent_id}`, `agent_activity:{task_id}` | N/A |
| db:3 | Idempotency keys | `idempotency:{message_id}` | 24h |

### Key Principle

> PostgreSQL is the sole source of truth. If Redis and Kafka both die, the system recovers from PostgreSQL alone. Redis is a speed layer. Kafka is a communication layer. Neither holds irreplaceable state.

### Core Schema — Entity Relationships

```mermaid
erDiagram
    AGENTS ||--o{ TASKS : "assigned_to"
    AGENTS ||--o{ EPISODIC_MEMORY : "owns"
    AGENTS ||--o{ SEMANTIC_MEMORY : "owns"
    AGENTS ||--o{ HUMAN_APPROVALS : "requests"
    AGENTS ||--o{ AUDIT_LOG : "logs"
    AGENTS ||--o{ LLM_USAGE : "spends"
    TASKS ||--o{ TASKS : "parent_of"
    TASKS ||--o{ EPISODIC_MEMORY : "produces"
    TASKS ||--o{ LLM_USAGE : "costs"
    TASKS ||--o{ HUMAN_APPROVALS : "blocks_on"
    TASKS ||--o{ AUDIT_LOG : "trace"
    PROMPTS ||--o{ AGENTS : "active_for_role"
    PROMPT_BENCHMARKS ||--o{ PROMPTS : "evaluates"

    AGENTS {
        uuid id PK
        varchar role
        varchar name
        text system_prompt
        text_array tool_access
        varchar llm_model
        int token_budget_per_task
        bool is_active
    }
    TASKS {
        uuid id PK
        uuid trace_id
        uuid parent_task_id FK
        uuid assigned_agent_id FK
        text instruction
        varchar status
        varchar source
        jsonb output
        int tokens_used
    }
    EPISODIC_MEMORY {
        uuid id PK
        uuid agent_id FK
        uuid task_id FK
        text summary
        jsonb full_context
        varchar outcome
        vector embedding
        float importance_score
    }
    SEMANTIC_MEMORY {
        uuid id PK
        uuid agent_id FK
        varchar namespace
        varchar key
        text value
        float confidence
        vector embedding
    }
    LLM_USAGE {
        uuid id PK
        uuid task_id FK
        uuid agent_id FK
        varchar model
        int tokens_in
        int tokens_out
        float cost_usd
    }
    HUMAN_APPROVALS {
        uuid id PK
        uuid task_id FK
        uuid agent_id FK
        varchar tool_name
        text action_description
        varchar status
        varchar resolved_by
    }
    AUDIT_LOG {
        uuid id PK
        uuid task_id FK
        uuid agent_id FK
        varchar action
        jsonb details
    }
    PROMPTS {
        uuid id PK
        varchar agent_role
        int version
        text content
        bool is_active
        float benchmark_score
        varchar authored_by
    }
    PROMPT_BENCHMARKS {
        uuid id PK
        varchar agent_role
        text input
        jsonb expected_criteria
    }
```

---

## 7. Memory System

Agents have three types of memory:

### Episodic Memory (What happened)
- Stored in `episodic_memory` table with pgvector embeddings
- Records: agent_id, task_id, summary, outcome, context, embedding
- Used by AgentBase to load similar past tasks before processing
- Enables agents to learn from past successes and failures

### Semantic Memory (What we know)
- Stored in `semantic_memory` table with pgvector embeddings
- Records: namespace, key, value, confidence, source
- Project-level facts (e.g., "the API uses Litestar", "database is PostgreSQL 16")
- Shared across agents, namespace-scoped

### Working Memory (What we're doing now)
- Stored in Redis db:0 (volatile, fast)
- Per-task state: CEO tracking data, subtask progress, intermediate results
- Cleared when task completes. Not persisted to PostgreSQL.
- Key pattern: `wm:{task_id}:{agent_id}`

---

## 8. Tool System (MCP)

### Architecture

```mermaid
flowchart LR
    AGENT[Agent<br/>Pydantic AI]:::core --> ADAPTER[tools/adapter.py<br/>wraps MCP]:::integ
    REGISTRY[tools/registry.py<br/>per-role access map]:::integ
    GUARDS[tools/guards.py<br/>require_approval gate]:::danger
    AGENT -.-> REGISTRY
    ADAPTER --> GUARDS
    ADAPTER --> MCPPKG[MCP Python package]:::integ
    MCPPKG --> EXT[External service<br/>web · files · email]:::ext

    classDef core fill:#1e40af,stroke:#1e3a8a,color:#fff
    classDef integ fill:#0891b2,stroke:#0e7490,color:#fff
    classDef ext fill:#64748b,stroke:#475569,color:#fff
    classDef danger fill:#dc2626,stroke:#991b1b,color:#fff
```

### Per-Role Tool Access

| Tool | CEO | Engineer | Analyst | Writer | QA | Prompt Creator |
|------|-----|----------|---------|--------|----|----|
| web_search | – | ✓ | ✓ | ✓ | – | – |
| web_fetch | – | – | ✓ | – | – | – |
| file_read | – | ✓ | – | ✓ | – | – |
| file_write | – | ✓⚠ | ✓ | – | – | – |
| code_execute | – | ✓ | – | – | – | – |
| git_push | – | ✓⚠ | – | – | – | – |
| send_email | – | – | – | ✓⚠ | – | – |
| memory_read | ✓ | – | – | – | – | ✓ |

⚠ = Requires `HumanApproval` record before execution

### Approval Flow

```mermaid
sequenceDiagram
    autonumber
    participant Agent
    participant Guards as guards.py
    participant DB as PostgreSQL
    participant K as Kafka
    actor Dashboard
    participant API as Litestar API
    actor Human

    Agent->>Guards: tool_file_write("deploy.sh", content)
    Guards->>DB: INSERT human_approvals (pending)
    Guards->>K: publish human.input_needed
    K->>Dashboard: shows approval request
    Human->>Dashboard: click Approve / Reject
    Dashboard->>API: POST /api/approvals/{id}/resolve
    API->>DB: UPDATE human_approvals (resolved)
    API-->>Guards: notify decision
    alt approved
        Guards-->>Agent: proceed (execute tool)
    else rejected
        Guards-->>Agent: raise ApprovalRejected
    end
```

---

## 9. A2A Gateway

### Inbound Flow (Phase 2)

External agents discover NEXUS via the Agent Card, then submit tasks:

```mermaid
sequenceDiagram
    autonumber
    participant Ext as External Agent
    participant GW as A2A Gateway
    participant PG as PostgreSQL
    participant K as Kafka
    participant CEO
    participant R as Redis pub/sub

    Ext->>GW: GET /.well-known/agent.json
    GW-->>Ext: AgentCard (skills + auth)
    Ext->>GW: POST /a2a/tasks (Bearer token)
    GW->>GW: validate token + skill access
    GW->>PG: INSERT task (source=a2a)
    GW->>K: publish a2a.inbound
    K->>CEO: consume (normal pipeline)
    par poll
        Ext->>GW: GET /a2a/tasks/{id}/status
        GW-->>Ext: status JSON
    and stream
        Ext->>GW: GET /a2a/tasks/{id}/events (SSE)
        R-->>GW: agent_activity:{task_id}
        GW-->>Ext: SSE events until task_result/failed
    end
```

**SSE Streaming (ADR-033):** The events endpoint subscribes to Redis pub/sub channel
`agent_activity:{task_id}` and streams events in SSE format. Terminates on `task_result`
or `task_failed`. Same channel the dashboard WebSocket uses — one publisher, two consumers.

### Agent Card

```json
{
  "name": "NEXUS",
  "description": "Agentic AI Company-as-a-Service",
  "version": "0.2.0",
  "skills": [
    { "id": "research", "name": "Research & Analysis" },
    { "id": "write", "name": "Content Writing" },
    { "id": "code", "name": "Engineering" },
    { "id": "general", "name": "General Task" }
  ],
  "auth": { "type": "bearer" }
}
```

### Authentication

- Tokens are SHA-256 hashed and stored in the `a2a_tokens` DB table
- Each token has: allowed_skills list, rate_limit_rpm, expiration, revocation status
- Skill-level access control: a token for "research" can't submit "code" tasks
- Per-token rate limiting via Redis db:1 sliding window counter
- CRUD API: create, list, revoke, rotate tokens
- Dev token seeded on startup for testing

### Outbound (Complete)

NEXUS agents can hire external agents via `tool_hire_external_agent` (irreversible tool,
requires human approval). The `gateway/outbound.py` implements:
- Agent discovery via `/.well-known/agent.json`
- Task submission with bearer token auth
- Status polling and SSE streaming for results
- Full error handling and structured logging

---

## 10. Prompt Evolution System

The Prompt Creator Agent is a meta-agent that improves other agents' system prompts:

```mermaid
flowchart TD
    TRIGGER([Trigger<br/>manual or auto when failure rate > 10%]):::ext
    ANALYZE[Analyze episodic memory for target role<br/>identify failure patterns from recent 50 episodes<br/>calculate failure rate]:::core
    DRAFT[Draft improved prompt via LLM<br/>include current prompt + failure analysis<br/>request specific improvements]:::core
    BENCH[Benchmark proposed prompt<br/>score against test cases<br/>LLM self-evaluation v1]:::core
    STORE[Store proposed prompt<br/>is_active=FALSE]:::store
    APPROVE[Publish approval request<br/>Kafka human.input_needed]:::danger
    REVIEW[Human reviews diff in PromptDiffView<br/>current vs proposed + benchmark scores]:::ext
    ACTIVATE[POST /api/prompts/{id}/activate<br/>deactivate current · activate proposed]:::core
    AGENT([Agent picks up new prompt<br/>on next task]):::core

    TRIGGER --> ANALYZE --> DRAFT --> BENCH --> STORE --> APPROVE --> REVIEW --> ACTIVATE --> AGENT

    classDef core fill:#1e40af,stroke:#1e3a8a,color:#fff
    classDef ext fill:#64748b,stroke:#475569,color:#fff
    classDef store fill:#7c3aed,stroke:#5b21b6,color:#fff
    classDef danger fill:#dc2626,stroke:#991b1b,color:#fff
```

> **Critical invariant:** Prompts are NEVER auto-activated. See ADR-024.

---

## 11. Resilience & Health

### Budget Enforcement

- **Per-task limit:** 50,000 tokens (configurable)
- **Daily cap:** $5/day via Redis counter
- **Guard:** `_check_budget()` called before every LLM call
- **At 90%:** Task pauses, publishes to `human.input_needed`

### Tool Call Limits

- **Per-task limit:** 20 tool calls (configurable via `AgentBase.MAX_TOOL_CALLS`)
- Tool counting wrapper in `agents/factory.py` decorates every tool function
- Counter resets to 0 at the start of each task
- Exceeding limit raises `ToolCallLimitExceeded` → escalates to `human.input_needed`

### Output Validation & PII Sanitization

Applied after `handle_task()`, before memory write or publishing:

- **Empty output detection:** Success with no output downgraded to "partial"
- **Secret pattern redaction:** Scans for 9 patterns (`sk-`, `AKIA`, `Bearer`, `ghp_`, `gho_`,
  `github_pat_`, `xoxb-`, `xoxp-`, `-----BEGIN PRIVATE KEY`) and replaces with `[REDACTED]`
- **Size limit:** Outputs > 100KB get `_truncated: true` flag
- **PII sanitization** (`core/sanitization.py`): Scans for 18 pattern categories including
  API keys (AWS, GitHub, Slack, Anthropic, OpenAI), emails, phone numbers, SSNs, credit cards,
  JWT tokens, database connection strings, private IPs, and private keys. Detected patterns
  are replaced with typed redaction markers (e.g., `[REDACTED:EMAIL]`, `[REDACTED:AWS_KEY]`).
  Applied recursively to string, dict, and list outputs.

### Audit Logging

Centralized audit trail via `audit/service.py`:

- **13 event types:** task_received, task_completed, task_failed, llm_call, tool_call,
  tool_call_limit_reached, approval_requested, approval_resolved, budget_exceeded,
  prompt_activated, prompt_rollback, prompt_created, heartbeat_silence
- All events written to `audit_log` table with task_id, trace_id, agent_id
- API endpoints: `GET /audit` (filterable list), `GET /audit/{task_id}/timeline`

### Prompt Hot-Reload

- Agents check `agents.system_prompt` in DB before each task
- If changed (via prompt versioning API), the PydanticAgent is reconstructed
- No restart required — prompt changes take effect on next task

### Health Monitor

- Background asyncio task consuming `agent.heartbeat`
- Tracks last-seen timestamp per agent in Redis
- Scans every 60 seconds for agents silent > 5 minutes
- Auto-fails active tasks for stale agents (DB update + audit log)

### Meeting Room Guards & Convergence Detection

- **Timeout:** 300 seconds default (configurable per meeting)
- **Max rounds:** 10 default (configurable per meeting)
- **Transcript:** Generated on termination for auditability
- **Convergence detection:** Director's `check_convergence()` measures inter-round similarity
  via SequenceMatcher. Rounds with >75% similarity are flagged as looping.
- **Stagnation detection:** Tracks unique ideas per round. If last 2 rounds have ≤1 unique
  idea each, discussion is stagnating.
- **Loop prevention:** Recommends `terminate` (looping), `synthesize` (stagnating/converging),
  or `continue` (productive). Director uses this to decide meeting fate.
- **Best contribution extraction:** `get_best_contributions()` deduplicates and ranks responses
  by depth, giving the Director the strongest material for synthesis.

### Dead Letter Handling

- Failed Kafka consumer after 3 retries → message routed to `{topic}.dead_letter`
- Dead letters persisted to `dead_letters` DB table with retry count, error, payload
- Dashboard shows dead letter count per topic with resolve actions
- Dead letter topics: `task.queue.dead_letter`, `agent.commands.dead_letter`,
  `agent.responses.dead_letter`, `a2a.inbound.dead_letter`
- Never silently drop a failed message

### LLM Eval Scoring

- LLM-as-judge framework in `eval/scorer.py` using configurable judge model
- 4 dimensions scored (0–1): relevance, completeness, accuracy, formatting
- Batch runner in `eval/runner.py` evaluates recent completed tasks
- Results stored in `eval_results` table with judge reasoning
- API: `GET /api/eval/scores` (aggregates by role/period), `POST /api/eval/run` (trigger)
- Dashboard: EvalScoreDashboard with period selector, role breakdown, recent scores

### Idempotency

- Every Kafka message has a unique message_id
- Before processing, agents check Redis db:3 for `idempotency:{message_id}`
- If found → skip (already processed). If not → process and write key with 24h TTL.

### Retry Logic

- Rate limit errors (429): exponential backoff, 5 retries, 5s→45s
- Tool use failures: retry without tools (fallback to text-only)
- Kafka publish failures: logged and re-raised (fail fast)
- **Configurable retry policies** (`core/retry.py`): Pre-configured policies for LLM (5 retries,
  2-45s), Kafka (3, 1-30s), DB (3, 0.5-10s), Redis (3, 0.2-5s). All use exponential backoff
  with jitter to prevent thundering herds. Non-retryable exceptions (e.g., auth failures) fail
  immediately.

### Kafka Message Integrity

- **HMAC-SHA256 signing** (`core/kafka/signing.py`): Every message is signed before publishing
  using the JWT secret as the HMAC key. Canonical JSON serialization ensures deterministic
  signatures regardless of dict ordering.
- **Signature validation on consume:** Consumer rejects unsigned messages in production.
  Development mode accepts unsigned messages for backwards compatibility.
- **Constant-time comparison:** Uses `hmac.compare_digest()` to prevent timing attacks.

### Crash Recovery

- **Orphaned task detection** (`core/recovery.py`): On startup, scans for tasks with
  `status=running` older than 30 minutes. Re-queues tasks with <2 recovery attempts,
  fails tasks that have been retried too many times.
- **Stale lock cleanup:** Scans Redis db:3 for `task_lock:*` keys with no TTL (indicating
  a dead process held the lock). Removes them to unblock task processing.
- **Human notification:** Failed recovery tasks are published to `human.input_needed`.

### Graceful Shutdown

- **Signal handling:** `SIGINT` and `SIGTERM` trigger `request_shutdown()` in the runner.
- **Task draining:** In-flight tasks get 30 seconds to complete. Progress logged every 5s.
- **Checkpointing:** Tasks that can't finish are marked in DB for recovery on next startup.
- **Shutdown awareness:** Agents check `is_shutting_down()` before accepting new tasks.
  Active tasks are tracked via `register_active_task()`/`unregister_active_task()`.

### Circuit Breaker (Enterprise Edition)

- **Sliding window:** Tracks last 20 calls per provider (not just consecutive failures).
  Opens circuit when failure rate exceeds 50% in the window OR after 5 consecutive failures.
- **Health scores:** 0.0 (dead) to 1.0 (healthy), combining failure rate (60% weight),
  slow call rate (30% weight), and circuit state (10% weight).
- **Latency tracking:** Records per-call latency. Calls >10s are classified as "slow."
- **System health:** `get_system_health_score()` averages all provider health scores.
- **Stats dashboard:** `get_all_breaker_stats()` returns comprehensive metrics per provider.

---

## 12. Security Model

### Authentication

| Endpoint | Auth Method |
|----------|------------|
| `/api/*` | No auth (Phase 2 — single-user mode) |
| `/a2a/tasks` | Bearer token (SHA-256 hashed, skill-scoped) |
| `/ws/agent-activity` | No auth (Phase 2 — localhost only) |

### Authorization

- **Tool access:** Per-role registry in `tools/registry.py`
- **Irreversible tools:** Require `HumanApproval` record (`tools/guards.py`)
- **A2A tokens:** Skill-level access control (token can only access allowed skills)
- **Agent isolation:** Agents can only access their own working memory namespace

### Planning & Security Review (Phase 7)

- **CEO execution plan:** Before decomposing tasks, CEO creates a plan with:
  risk level (low/medium/high), security concerns, required approvals, estimated complexity
- **Director security review:** After specialists finish, the Director validates outputs
  against the execution plan. Checks for dangerous patterns (`rm -rf`, `eval()`, `exec()`,
  `os.system()`, SQL injection), unauthorized external references, and risk level alignment.
- **End-to-end flow:** Plan → Decompose → Execute → Security Review → Synthesize → QA

### Message Integrity

- **Kafka signing:** All messages HMAC-SHA256 signed at the producer (`core/kafka/signing.py`).
  Consumers validate signatures before processing. Unsigned or tampered messages rejected in production.
- **PII sanitization:** All agent outputs scanned for 18 PII pattern categories before publishing.
  Detected patterns replaced with typed redaction markers.

### Secrets Management

- All API keys via environment variables (never hardcoded)
- `.env` file in `.gitignore`
- Docker Compose passes env vars to containers
- SOPS-based encrypted secrets + KeepSave integration for API-based secrets

---

## 13. Deployment Architecture

### Docker Compose (Local Development)

```mermaid
flowchart TD
    COMPOSE[docker-compose.yml<br/>target: dev]:::core
    BACKEND[backend<br/>Python 3.12 · Litestar · :8000<br/>hot-reload]:::core
    FRONTEND[frontend<br/>Node 20 · Vite · :5173<br/>hot-reload]:::core
    POSTGRES[(postgres<br/>PostgreSQL 16 + pgvector<br/>5433:5432)]:::store
    REDIS[(redis<br/>Redis 7<br/>6380:6379)]:::store
    KAFKA[(kafka<br/>Apache Kafka KRaft<br/>:9092)]:::store

    COMPOSE --> BACKEND
    COMPOSE --> FRONTEND
    COMPOSE --> POSTGRES
    COMPOSE --> REDIS
    COMPOSE --> KAFKA
    BACKEND -.-> POSTGRES
    BACKEND -.-> REDIS
    BACKEND -.-> KAFKA
    FRONTEND -.-> BACKEND

    classDef core fill:#1e40af,stroke:#1e3a8a,color:#fff
    classDef store fill:#7c3aed,stroke:#5b21b6,color:#fff
```

### Multi-Stage Docker Builds

Both backend and frontend use multi-stage Dockerfiles:

| Stage | Backend | Frontend |
|-------|---------|----------|
| **dev** | Full deps + dev deps, `--reload`, volume mounts | `npm install`, Vite dev server |
| **prod** | No dev deps, non-root user, 2 uvicorn workers | nginx serving static files (62MB) |

```bash
make up          # Dev mode (default)
make build-prod  # Build prod images
make up-prod     # Run prod stack
```

### Port Mapping

Host ports are remapped to avoid conflicts with local services:

| Service | Container Port | Host Port (dev) | Host Port (prod) |
|---------|---------------|-----------------|-------------------|
| Backend | 8000 | 8000 | 8000 |
| Frontend | 5173 / 80 | 5173 | 80 |
| PostgreSQL | 5432 | 5433 | 5433 |
| Redis | 6379 | 6380 | 6380 |
| Kafka | 9092 | 9092 | 9092 |

### CI/CD Pipeline

GitHub Actions workflows in `.github/workflows/`:

| Workflow | Trigger | Jobs |
|----------|---------|------|
| `ci.yml` | Push/PR to main | Ruff lint, mypy, unit tests, behavior tests, chaos tests, integration tests, frontend TS check + build |
| `docker-publish.yml` | Push to main + tags | Build prod images → push to DockerHub (SHA/branch/semver tags) |
| `security.yml` | Push/PR + weekly | pip-audit, npm audit, TruffleHog secrets, Trivy container scan, CodeQL |

### Startup Sequence

```mermaid
sequenceDiagram
    autonumber
    actor Dev
    participant Make as make setup
    participant Docker
    participant PG as PostgreSQL
    participant R as Redis
    participant K as Kafka
    participant BE as Backend
    participant FE as Frontend

    Dev->>Make: invoke scripts/setup.sh
    Make->>Docker: build all 5 containers (dev target)
    Docker->>PG: start + healthcheck
    Docker->>R: start + healthcheck
    Docker->>K: start + healthcheck
    Docker->>BE: start
    BE->>PG: alembic upgrade head
    BE->>PG: seed DB
    BE->>BE: start agents
    Docker->>FE: start
    FE->>BE: connect API + WebSocket
    Dev->>BE: GET /health
    BE-->>Dev: all green
```

---

## 14. KeepSave Integration

NEXUS integrates with [KeepSave](https://github.com/santapong/KeepSave) for centralized secret management, OAuth 2.0 identity, and MCP gateway access. This replaces hardcoded credentials and resolves critical security audit findings.

### Integration Architecture

```mermaid
flowchart TD
    subgraph STARTUP["**NEXUS Startup**"]
        SETTINGS[settings.py]
        ENV[Read KEEPSAVE_URL,<br/>KEEPSAVE_API_KEY from env]
        SDK[KeepSave Python SDK<br/>GET /api/v1/projects/{id}/secrets]
        INJECT[Inject decrypted secrets<br/>into os.environ]
        PSETTINGS[Pydantic Settings<br/>reads from env as normal]
    end

    subgraph KS["**KeepSave (Go + Gin)**"]
        AUTH[API Key Auth]
        DECRYPT[Decrypt AES-256-GCM]
        RETURN[Return secrets]
        VAULT[(Encrypted Vault<br/>ANTHROPIC_API_KEY · GOOGLE_API_KEY · OPENAI_API_KEY<br/>DATABASE_URL · REDIS_URL · KAFKA_BOOTSTRAP_SERVERS<br/>JWT_SECRET_KEY · A2A_INBOUND_TOKEN<br/>DAILY_SPEND_LIMIT_USD · DEFAULT_TOKEN_BUDGET_PER_TASK)]
    end

    SETTINGS --> ENV --> SDK
    SDK -->|HTTPS| AUTH
    AUTH --> DECRYPT
    DECRYPT --> VAULT
    VAULT --> RETURN
    RETURN -->|secrets JSON| INJECT
    INJECT --> PSETTINGS

    classDef core fill:#1e40af,stroke:#1e3a8a,color:#fff
    classDef integ fill:#0891b2,stroke:#0e7490,color:#fff
    classDef store fill:#7c3aed,stroke:#5b21b6,color:#fff

    class SETTINGS,ENV,INJECT,PSETTINGS core
    class SDK,AUTH,DECRYPT,RETURN integ
    class VAULT store
```

### What KeepSave Provides

| Capability | How NEXUS Uses It |
|-----------|-------------------|
| **Encrypted Vault** | All LLM API keys, DB URLs, JWT secrets stored with AES-256-GCM encryption |
| **Environment Promotion** | Dev ($5/day limit) → Staging ($10/day) → Prod ($50/day) with diff preview |
| **OAuth 2.0 Provider** | SSO for dashboard users + client credentials for A2A external agents |
| **MCP Gateway** | NEXUS tools registered in marketplace; other MCP servers callable with auto-secret injection |
| **Scoped API Keys** | Read-only, environment-locked keys for runtime secret fetching |
| **Audit Trail** | Complete log of secret access — required for multi-tenant compliance |

### Security Improvements

| Before (Insecure) | After (KeepSave) |
|-------------------|-------------------|
| All secrets in `.env` plaintext | Only `KEEPSAVE_URL` + `KEEPSAVE_API_KEY` in `.env` |
| Hardcoded JWT secret in `settings.py` | JWT secret in encrypted vault, no default |
| Hardcoded A2A token in `gateway/auth.py` | A2A tokens as encrypted secrets with rotation |
| Manual secret rotation | Promotion pipeline with approval workflow |
| No secret access auditing | Full audit trail per secret per access |

### Graceful Fallback

If KeepSave is unavailable, NEXUS falls back to standard environment variables:

```python
# settings.py — KeepSave bootstrap is conditional
if _keepsave_url and _keepsave_key and _keepsave_project:
    # Fetch from KeepSave
    ...
# Else: Pydantic Settings reads from env/defaults as normal
```

For the full integration guide, see [KEEPSAVE_INTEGRATION.md](KEEPSAVE_INTEGRATION.md).

---

## 15. Performance Optimization

### Database Indexes (Migration 005)

Seven composite and partial indexes added for hot query paths:

| Index | Table | Columns | Use Case |
|-------|-------|---------|----------|
| `ix_tasks_agent_created` | tasks | (assigned_agent_id, created_at DESC) | Agent task history, analytics |
| `ix_approvals_status_requested` | human_approvals | (status, requested_at DESC) | Pending approvals listing |
| `ix_billing_workspace_created` | billing_records | (workspace_id, created_at DESC) | Tenant billing queries |
| `ix_tasks_active` | tasks | (status, created_at DESC) WHERE status IN ('queued','running','paused') | Active task lookups |
| `ix_llm_usage_agent_created` | llm_usage | (agent_id, created_at DESC) | Per-agent cost analytics |
| `ix_audit_agent_created` | audit_log | (agent_id, created_at DESC) | Per-agent audit queries |
| `ix_episodic_agent_created` | episodic_memory | (agent_id, created_at DESC) | Agent memory recall |

### N+1 Query Fixes

- **Analytics** (`api/analytics.py`) — Replaced per-agent loop (3 queries × N agents) with 2 batch
  GROUP BY queries. Single query for task stats, single query for costs.
- **Task replay** (`api/tasks.py`) — Replaced per-subtask loop (2 queries × N subtasks) with
  batch `IN` clause queries for memories and usage.
- **ORM relationships** — All `lazy="selectin"` changed to `lazy="raise"` on Agent.tasks,
  Task.assigned_agent, Task.parent_task, User.workspaces, Workspace.owner. Accidental eager
  loading now raises an error instead of silently executing N+1 queries.

---

## 16. Circuit Breaker & Fault Tolerance

### LLM Provider Circuit Breaker (`core/llm/circuit_breaker.py`)

Per-provider circuit breaker prevents cascading failures when an LLM provider is down.

**States:**
- **CLOSED** — Normal operation. Calls go through.
- **OPEN** — Provider failing (5 consecutive failures). Calls rejected immediately → fallback chain.
- **HALF_OPEN** — Recovery test after 60s timeout. One call allowed to probe.

**Integration:** ModelFactory checks circuit breaker before each LLM call. If circuit is open,
immediately tries the next provider in the fallback chain. States exposed via `/health` endpoint
under `circuit_breakers` key.

### Enhanced Health Check

The `/health` endpoint now returns three-tier status:

| Status | Meaning | HTTP Code |
|--------|---------|-----------|
| `healthy` | All core + optional services up | 200 |
| `degraded` | Core services up, optional services (Temporal, KeepSave, LangFuse) down | 200 |
| `unhealthy` | One or more core services (PostgreSQL, Redis, Kafka) down | 200 |

Response includes `checks` (core), `optional` (integrations), and `circuit_breakers` (LLM providers).

---

## 17. API Security Middleware (`api/middleware.py`)

### Rate Limiting

Sliding window counters in Redis db:1:

| Tier | Limit | Scope |
|------|-------|-------|
| Authenticated | 100 req/min | Per user_id |
| Unauthenticated | 20 req/min | Per IP |
| Task creation | 10 req/min | Per user_id |

Falls back to allowing requests if Redis is unavailable.

### Prompt Injection Defense

Two-layer defense:

1. **`validate_instruction()`** — Rejects instructions matching 5 regex patterns:
   - "ignore previous instructions"
   - "you are now"
   - "reveal/show system prompt"
   - Special tokens (`<|...|>`)
   - Llama tokens (`[INST]`, `<<SYS>>`)
   - Max 10,000 character length

2. **`sandbox_instruction()`** — Wraps user input with `<user_instruction>` delimiters.
   System prompts instruct the LLM to treat delimited content as untrusted user input.

### Startup Security Checks

Production deployments blocked if:
- JWT secret is the default value (`nexus-dev-secret-change-in-production`)
- No LLM API keys configured (warning only)

### Request Size Limits

- Litestar `request_max_body_size=1_048_576` (1MB)
- Tool output sanitization: `_sanitize_tool_output()` truncates at 50KB

---

## 18. Scheduled & Recurring Tasks (`core/scheduler.py`)

Cron-based task scheduler for recurring automated tasks:

- **Cron evaluation** via `croniter` library — standard 5-field cron expressions
- **`task_schedules` table** — stores schedule definition, cron expression, next_run_at, total_runs
- **Scheduler tick** — finds due schedules (next_run_at <= now), creates tasks, publishes to Kafka
- **Max runs guard** — auto-deactivates schedule after reaching configured max_runs
- **Missed run handling** — next_run_at recalculated after each execution
- **CRUD API** — `POST /api/schedules`, `GET /api/schedules`, `PATCH`, `DELETE`

---

## 19. Per-Agent Cost Alerts (`core/llm/cost_alerts.py`)

Configurable daily budget limits per agent:

- **`agent_cost_alerts` table** — per-agent daily_limit_usd + alert_threshold_pct
- **Redis-cached spend counter** — `agent_daily_spend:{agent_id}:{date}` key
- **PostgreSQL fallback** — queries `llm_usage` when Redis unavailable
- **Guard chain integration** — `AgentBase._check_budget()` checks agent cost alerts alongside
  global daily spend and per-task token budgets (three-layer enforcement)
- **API** — `GET /api/analytics/agent-cost-alerts` returns spend status for all configured agents

---

## 20. Provider Health Monitoring (`core/llm/provider_health.py`)

Tracks LLM provider health for informed routing and debugging:

- **In-memory ring buffer** — records latency + success/failure for last 100 calls per provider
- **Status derivation** — `healthy` / `degraded` (>10% errors) / `down` (>50% errors or circuit open)
- **Circuit breaker integration** — reads from `circuit_breaker.py` for immediate failure detection
- **Periodic flush** — writes rolling window summary to `provider_health` DB table
- **API** — `GET /api/analytics/provider-health` returns per-provider status, latency percentiles,
  error rates, and circuit breaker state

---

## 21. Model Performance Benchmarking (`core/llm/benchmarking.py`)

Compare quality/cost/speed across models for each agent role:

- **Reuses `prompt_benchmarks` table** — existing test cases drive comparisons
- **Per-benchmark execution** — runs test input against specified model, measures output quality,
  latency, tokens, and cost
- **Scoring** — keyword matching, format validation, length checks against expected_criteria
- **`model_benchmarks` table** — stores results for historical comparison
- **API** — `GET /api/analytics/model-benchmarks/{role}` returns benchmark history

---

## 22. QA Multi-Round Rework

Configurable rework loop with escalation guard:

- **`qa_max_rework_rounds`** setting (default 2) — prevents unbounded rework loops
- **Round tracking** — `rework_round` counter in task payload and `tasks.rework_round` column
- **Feedback accumulation** — each rework includes all previous QA feedback for context
- **Escalation** — after max rounds, QA publishes to `human.input_needed` instead of reworking
- **Task status** — escalated tasks marked with `rework_rounds_exhausted: true`

---

*Last updated: 2026-05-21*
*Phase: 7 Complete + post-Phase 7 audit war room (2026-05-19)*
*Diagram format: Mermaid (flowchart, sequenceDiagram, erDiagram, mindmap)*

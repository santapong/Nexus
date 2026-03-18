# NEXUS

**Agentic AI Company as a Service**

A platform where every department of a digital company is staffed by an AI agent. Agents have defined roles, persistent memory, access to tools via MCP, and communicate through Apache Kafka — the "conference room" where they meet, debate, and collaborate.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  External World                                                     │
│  Other AI Agents ←── A2A Protocol ──→     User / Dashboard         │
└──────────────────┬──────────────────────────────┬───────────────────┘
                   │                              │
┌──────────────────▼──────────────┐  ┌────────────▼───────────────────┐
│  A2A Gateway Service            │  │  Litestar API                  │
│  /.well-known/agent.json        │  │  REST + WebSocket + Auth       │
└──────────────────┬──────────────┘  └────────────┬───────────────────┘
                   │                              │
┌──────────────────▼──────────────────────────────▼───────────────────┐
│  Apache Kafka — Event Bus  (The Conference Room)                    │
│  task.queue · agent.commands · agent.responses · task.results       │
│  meeting.room · memory.updates · audit.log · agent.heartbeat        │
└──────────┬──────────────────────────────────────────────────────────┘
           │
┌──────────▼──────────────────────────────────────────────────────────┐
│  Agent Runtime — Pydantic AI                                        │
│  CEO · Engineer · Analyst · Writer · QA · Prompt Creator           │
└──────────┬──────────────────────────────────────────────────────────┘
           │
┌──────────▼──────────────────────────────────────────────────────────┐
│  Tools Layer — MCP Adapter                                          │
│  web_search · file_read · code_execute · file_write · email         │
└──────────┬──────────────────────────────────────────────────────────┘
           │
┌──────────▼──────────────────────────────────────────────────────────┐
│  Persistence                                                        │
│  PostgreSQL 16 + pgvector    Redis 7 (4 roles)                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Three Protocol Layers

| Protocol | Purpose | Scope |
|----------|---------|-------|
| **Kafka** | Internal agent communication | Agent-to-agent — never leaves the system |
| **MCP** | Agent-to-tool access | Web search, code execution, file I/O, email |
| **A2A** | External agent interop | External systems hire NEXUS agents and vice versa |

## Tech Stack

**Backend:** Python 3.12+ · Litestar · Pydantic AI · Advanced Alchemy · Alembic · aiokafka · Taskiq · redis-py (async)

**Frontend:** TypeScript · React 18 · Vite · TanStack Query v5 · Zustand · Tailwind CSS · Shadcn/ui

**Infrastructure:** PostgreSQL 16 + pgvector · Redis 7 · Apache Kafka (KRaft) · Docker Compose · Kubernetes (Kustomize)

**LLM Providers:** Anthropic Claude · Google Gemini · OpenAI · Groq · Mistral · Ollama · any OpenAI-compatible endpoint (abstracted via universal ModelFactory)

## Agent Roster

| Agent | Role | Default Model |
|-------|------|---------------|
| CEO | Orchestrator — decomposes tasks, delegates, aggregates results | Configurable (any provider) |
| Engineer | Code generation, debugging, architecture | Configurable (any provider) |
| Analyst | Research, data analysis, reports | Configurable (any provider) |
| Writer | Content, emails, documentation | Configurable (any provider) |
| QA | Reviews all outputs before delivery | Configurable (any provider) |
| Prompt Creator | Meta-agent — improves other agents' system prompts | Configurable (any provider) |

Models are configured per-role via environment variables (e.g., `MODEL_ENGINEER=groq:llama-3.3-70b-versatile`). See `.env.example` for all options.

## Project Structure

```
nexus/
├── CLAUDE.md                      # Master project document
├── AGENTS.md                      # AI agent coding policy
├── docs/
│   ├── ARCHITECTURE.md            # System architecture & fundamentals
│   ├── DECISIONS.md               # Architecture decision records
│   ├── RISK_REVIEW.md             # Risk assessment & phase gates
│   ├── BACKLOG.md                 # Deferred scope capture
│   ├── CHANGELOG.md               # Version history
│   ├── ERRORLOG.md                # Bug tracking & prevention
│   └── archive/                   # Old planning documents
├── backend/
│   ├── pyproject.toml
│   ├── Dockerfile
│   ├── alembic/                   # DB migrations
│   └── nexus/
│       ├── api/                   # Litestar REST + WebSocket endpoints
│       ├── agents/                # Agent implementations (base, ceo, engineer, ...)
│       ├── tools/                 # MCP adapter, per-role registry, approval guards
│       ├── gateway/               # A2A protocol gateway
│       ├── kafka/                 # Topics, schemas, producer, consumer, meeting
│       ├── memory/                # Episodic, semantic, working memory + embeddings
│       ├── llm/                   # ModelFactory + token/cost tracking
│       ├── db/                    # SQLAlchemy models, session, seed data
│       ├── eval/                  # LLM-as-judge eval scoring
│       ├── redis/                 # 4-role client abstraction
│       └── tests/                 # Unit, behavior, integration, e2e, chaos
├── frontend/
│   ├── package.json
│   └── src/
│       ├── api/                   # Typed API client
│       ├── components/            # Dashboard, agents, tasks, approvals, prompts
│       ├── hooks/                 # TanStack Query hooks
│       ├── types/                 # TypeScript interfaces
│       └── ws/                    # WebSocket context provider
├── scripts/
│   └── setup.sh                   # One-command project setup
├── k8s/
│   ├── base/                     # K8s manifests (postgres, redis, kafka, backend, frontend)
│   └── overlays/                 # Kustomize overlays (dev, prod)
├── docker-compose.yml
├── Makefile
└── .env.example
```

## Current Status

| Phase | Status |
|-------|--------|
| Phase 0 — Foundation | **Complete** |
| Phase 1 — Single Agent Loop | **Complete** — 50-task stress test passed at 100% |
| Phase 2 — Multi-Agent + A2A | **Complete** — All 7 priority groups done |
| Phase 3 — Hardening + A2A Outbound | **Complete** — Chaos tests, eval scoring, A2A outbound, K8s |
| Phase 4 — Scale to Service | **Complete** — Multi-tenant, Temporal, marketplace, billing, agent builder, LangFuse |
| Security Audit | **Complete** — 15 findings documented, 7 open (2 critical, 4 high, 1 medium) |

### What works today

- All 5 Docker services start and report healthy (PostgreSQL, Redis, Kafka, backend, frontend)
- `GET /health` returns all green checks (postgres, 4x redis, kafka)
- **Multi-agent task flow:** `POST /api/tasks` -> CEO decomposes -> specialist agents execute -> CEO aggregates -> QA reviews -> result delivered
- **6 agent roles operational:** CEO (orchestrator), Engineer, Analyst, Writer, QA, Prompt Creator
- **CEO LLM-based task decomposition** with dependency tracking and subtask dispatch
- **QA review pipeline** with approve/reject routing and rework commands
- **Meeting room pattern** — Kafka-based multi-agent debates with Redis-backed state
- **Prompt Creator Agent** — meta-agent that analyzes failures and proposes improved prompts
- **Health monitor** — auto-fails tasks for agents silent >5 minutes
- **A2A Gateway (inbound + outbound)** — external agents can hire NEXUS and vice versa
- **9 MCP tools** with per-role access control: web_search, web_fetch, file_read, file_write, code_execute, git_push, send_email, memory_read, hire_external_agent
- **A2A token management:** DB-backed with CRUD API, per-token rate limiting, rotation
- **Dead letter queue:** failed messages tracked in DB with retry counters and dashboard monitoring
- **Chaos tested:** 8 failure scenarios verified (Kafka down, Redis wiped, LLM timeout, budget exceeded, duplicates, invalid auth, DB exhaustion, agent silence)
- **LLM eval scoring:** LLM-as-judge framework with dimension scores and batch runner
- **Audit log dashboard:** filterable, paginated, color-coded event viewer
- **Fault tolerance:** DB connection pooling, Kafka producer reconnection, Redis retry with backoff, budget tracking fallback
- **Kubernetes ready:** Kustomize manifests with dev/prod overlays
- Universal ModelFactory supporting 7+ LLM providers (Anthropic, Google, OpenAI, Groq, Mistral, Ollama, OpenAI-compatible)
- **Eval scoring dashboard** — LLM-as-judge scores by role with period selector and manual eval trigger
- **A2A token management** — create, revoke, rotate bearer tokens for external callers
- Frontend dashboard with all panels (health, tasks, approvals, agents, prompts, analytics, audit, eval, A2A tokens)
- LLM retry logic: rate limit backoff (5 retries) + tool call fallback + model fallback chains
- `test:` model provider for infrastructure testing at zero API cost
- Database schema deployed: 18 tables with pgvector extension
- **Multi-tenant support** — Users, workspaces, JWT auth, per-tenant isolation
- **Per-tenant Agent Cards** — Workspace-scoped A2A discovery at `/.well-known/agent.json?workspace=`
- **Temporal workflows** — Durable long-running task execution with auto-retry
- **Agent Marketplace** — Browse, rate, and hire agents by skill/rating/price
- **Cross-company billing** — Cost tracking, invoice generation, per-task attribution
- **Custom agent builder** — No-code agent creation with model/tool/prompt configuration
- **LangFuse integration** — External eval tracking with LLM call traces and dimension scores

## Getting Started

### Prerequisites

- Docker and Docker Compose
- API key for at least one LLM provider (Groq free tier works for testing)

### Quick Setup

```bash
# One command setup (checks prerequisites, builds, starts, migrates, seeds)
make setup
```

### Manual Setup

```bash
# Clone the repository
git clone <repo-url> && cd Nexus

# Configure environment variables
cp .env.example .env
# Edit .env with your API keys (at minimum, set one provider key)
# Supported: ANTHROPIC_API_KEY, GOOGLE_API_KEY, OPENAI_API_KEY, GROQ_API_KEY, MISTRAL_API_KEY

# Start all services (PostgreSQL, Redis, Kafka, backend, frontend)
make up

# Run database migrations
make migrate

# Seed initial data
make seed

# Verify everything is running
curl localhost:8000/health
```

The dashboard will be available at `http://localhost:5173` and the API at `http://localhost:8000`.

> **Note:** If you have local PostgreSQL (5432) or Redis (6379) running, Docker ports are
> remapped to 5433 and 6380 respectively. Internal container networking is unaffected.

## Development

### Makefile Commands

| Command | Description |
|---------|-------------|
| `make up` | Start all services |
| `make down` | Stop all services |
| `make logs` | Tail service logs |
| `make migrate` | Run Alembic migrations |
| `make seed` | Seed database with initial data |
| `make test-unit` | Run unit tests |
| `make test-behavior` | Run behavior tests |
| `make test-e2e` | Run end-to-end tests |
| `make test-chaos` | Run chaos/fault tolerance tests |
| `make test-all` | Run all test suites (unit + behavior + e2e + chaos) |
| `make eval` | Run LLM eval scoring on recent tasks |
| `make kafka-test` | Kafka connectivity health check |
| `make kafka-topics` | List Kafka topics |
| `make lint` | Run Ruff linter |
| `make typecheck` | Run mypy strict type checking |
| `make shell-db` | Open PostgreSQL shell |
| `make shell-redis` | Open Redis CLI |

### Key Design Principles

- **Kafka is the nervous system** — all agent-to-agent communication is observable and replayable
- **Agents are stateless** — all state lives in Redis (working memory) or PostgreSQL (long-term memory)
- **PostgreSQL is the source of truth** — if Redis and Kafka both die, the system recovers from PostgreSQL alone
- **Humans stay in the loop** — irreversible actions (file writes, emails, git pushes) require explicit human approval
- **Every action is traceable** — all messages carry `task_id` and `trace_id` for full auditability

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | System health check (DB, Redis, Kafka) |
| `POST` | `/api/tasks` | Create a new task |
| `GET` | `/api/tasks` | List tasks (optional `?status=` filter) |
| `GET` | `/api/tasks/{id}` | Get task by ID |
| `GET` | `/api/agents` | List registered agents |
| `GET` | `/api/tasks/{id}/trace` | Get task trace (parent + subtask tree) |
| `GET` | `/api/approvals` | List pending approvals |
| `POST` | `/api/approvals/{id}/resolve` | Approve or reject an action |
| `GET` | `/api/prompts` | List prompts (filter by role, active) |
| `GET` | `/api/prompts/{id}/diff` | Diff proposed vs active prompt |
| `POST` | `/api/prompts/{id}/activate` | Approve and activate a proposed prompt |
| `POST` | `/api/prompts/improve` | Trigger prompt improvement for a role |
| `GET` | `/api/analytics/performance` | Agent performance metrics |
| `GET` | `/api/analytics/costs` | Cost breakdown by model/role |
| `GET` | `/api/analytics/dead-letters` | Dead letter queue stats |
| `GET` | `/api/audit` | Audit event log (filterable) |
| `POST` | `/api/a2a-tokens` | Create A2A bearer token |
| `GET` | `/api/a2a-tokens` | List A2A tokens |
| `DELETE` | `/api/a2a-tokens/{id}` | Revoke A2A token |
| `GET` | `/api/eval/scores` | Eval scoring aggregates |
| `POST` | `/api/eval/run` | Trigger manual eval run |
| `GET` | `/.well-known/agent.json` | A2A Agent Card (public capabilities) |
| `POST` | `/a2a/tasks` | A2A inbound — submit task (bearer auth) |
| `GET` | `/a2a/tasks/{id}/events` | A2A SSE event stream |
| `WS` | `/ws/agent-activity` | Real-time agent event stream |
| `POST` | `/api/auth/register` | Register new user + default workspace |
| `POST` | `/api/auth/login` | Login and get JWT token |
| `GET` | `/api/workspaces` | List workspaces |
| `POST` | `/api/workspaces` | Create workspace |
| `GET` | `/api/marketplace` | Browse agent marketplace |
| `POST` | `/api/marketplace` | Create marketplace listing |
| `GET` | `/api/billing/summary` | Billing cost summary |
| `GET` | `/api/billing/invoice` | Generate invoice |
| `GET` | `/api/agent-builder` | List custom agents |
| `POST` | `/api/agent-builder` | Create custom agent (no-code) |

## Roadmap

| Phase | Focus | Status |
|-------|-------|--------|
| Phase 0 | Foundation — Docker, schema, health checks, approval guards | **Complete** |
| Phase 1 | Single agent loop — AgentBase, Engineer Agent, basic dashboard | **Complete** — stress test 100% |
| Phase 2 | Multi-agent collaboration, Prompt Creator, A2A inbound | **Complete** — All groups done |
| Phase 3 | Hardening, chaos testing, A2A outbound, K8s | **Complete** |
| Phase 4 | Multi-tenant SaaS, Temporal workflows, marketplace | **Complete** |
| Phase 5 | Advanced features, federation, fine-tuning | Planned |

## Kubernetes Deployment

Kustomize manifests are provided in `k8s/` for cluster deployment.

```bash
# Dev (single replicas, small PVCs)
kubectl apply -k k8s/overlays/dev

# Production (HA, larger resources)
kubectl apply -k k8s/overlays/prod
```

Services: PostgreSQL (StatefulSet + PVC), Redis, Kafka (StatefulSet + PVC), Backend (with init container for migrations), Frontend (nginx), Ingress (WebSocket + SSE support).

## Documentation

- **[ARCHITECTURE.md](docs/ARCHITECTURE.md)** — System architecture, data flows, and design fundamentals
- **[CLAUDE.md](CLAUDE.md)** — Master project document with full architecture, schemas, and policies
- **[DECISIONS.md](docs/DECISIONS.md)** — Architecture Decision Records (26 ADRs)
- **[RISK_REVIEW.md](docs/RISK_REVIEW.md)** — Risk assessment and phase gate checklist
- **[BACKLOG.md](docs/BACKLOG.md)** — Captured ideas and deferred scope
- **[CHANGELOG.md](docs/CHANGELOG.md)** — Version history
- **[ERRORLOG.md](docs/ERRORLOG.md)** — Bug tracking and prevention rules (25 entries)
- **[AGENTS.md](AGENTS.md)** — AI agent coding policy and workflow rules

## Security

A full security audit was performed on 2026-03-18. See [ERRORLOG.md](docs/ERRORLOG.md) entries ERROR-019 through ERROR-025 for details.

### Audit Summary

| Severity | Count | Status |
|----------|-------|--------|
| Critical | 2 | Open — must fix before production |
| High | 4 | Open — must fix before production |
| Medium | 3 | Open — recommended fix |
| Low/Info | 6 | Tracked — enhancement |

### Critical Issues (fix before deploying)

1. **Hardcoded JWT secret** (`settings.py`) — Default dev secret must be removed; make env-var required
2. **Hardcoded A2A dev token** (`gateway/auth.py`) — Auto-seeded token discoverable in source code

### High Issues (fix before multi-tenant use)

3. **Missing workspace isolation** (`api/workspaces.py`) — All workspaces visible to any user
4. **Missing task tenant isolation** (`api/tasks.py`) — Tasks not scoped to workspace
5. **Unsafe slug generation** (`api/workspaces.py`) — No validation or uniqueness constraint
6. **Missing auth on approvals** (`api/approvals.py`) — `resolved_by` is user-controlled, no JWT check

### What's Already Secure

- Password hashing: PBKDF2-HMAC-SHA256, 600k iterations (OWASP 2023)
- Timing-safe JWT comparison via `hmac.compare_digest()`
- A2A tokens stored as SHA-256 hashes (not plaintext)
- Pydantic validation at all API boundaries (no raw dict crossing modules)
- No raw SQL — SQLAlchemy ORM throughout
- Secret pattern detection in agent output (redacts `sk-`, `AKIA`, `Bearer`, `ghp_`, etc.)
- Safe subprocess execution (list args, no `shell=True`)
- 24-hour JWT token expiration
- Sliding window rate limiting on A2A endpoints

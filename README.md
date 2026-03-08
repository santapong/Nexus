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

**Infrastructure:** PostgreSQL 16 + pgvector · Redis 7 · Apache Kafka (KRaft) · Docker Compose

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
├── backend/
│   ├── pyproject.toml
│   ├── Dockerfile
│   ├── alembic/                    # DB migrations
│   └── nexus/
│       ├── api/                    # Litestar REST + WebSocket endpoints
│       ├── agents/                 # Agent implementations (base, ceo, engineer, ...)
│       ├── tools/                  # MCP adapter, per-role registry, approval guards
│       ├── gateway/                # A2A protocol gateway
│       ├── kafka/                  # Topics, schemas, producer, consumer
│       ├── memory/                 # Episodic, semantic, working memory + embeddings
│       ├── llm/                    # ModelFactory + token/cost tracking
│       ├── db/                     # SQLAlchemy models, session, seed data
│       ├── redis/                  # 4-role client abstraction
│       └── tests/                  # Unit, behavior, e2e
├── frontend/
│   ├── package.json
│   └── src/
│       ├── api/                    # Generated from OpenAPI
│       ├── components/             # Dashboard, agents, tasks, approvals
│       ├── hooks/                  # TanStack Query hooks
│       ├── store/                  # Zustand (UI state only)
│       └── ws/                     # WebSocket context provider
├── docker-compose.yml
├── Makefile
└── .env.example
```

## Current Status

| Phase | Status |
|-------|--------|
| Phase 0 — Foundation | **Complete** |
| Phase 1 — Single Agent Loop | **Complete** — 50-task stress test passed at 100% |
| Phase 2 — Multi-Agent + A2A | Ready to start |

### What works today

- All 5 Docker services start and report healthy (PostgreSQL, Redis, Kafka, backend, frontend)
- `GET /health` returns all green checks (postgres, 4x redis, kafka)
- Full task flow verified end-to-end: `POST /api/tasks` → CEO → Engineer → LLM → result in DB
- Universal ModelFactory supporting 7+ LLM providers (Anthropic, Google, OpenAI, Groq, Mistral, Ollama, OpenAI-compatible)
- Frontend dashboard with all panels (health, tasks, approvals, agents)
- WebSocket real-time updates from agent activity
- LLM retry logic: rate limit backoff (5 retries) + tool call fallback
- `test:` model provider for infrastructure testing at zero API cost
- 50-task stress test: 100% pass rate (Phase 2 gate cleared)
- Database schema deployed: all 9 tables with pgvector extension
- CEO and Engineer agents start, subscribe to correct Kafka topics, and process messages

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
| `make test-all` | Run all test suites |
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
| `GET` | `/api/approvals` | List pending approvals |
| `POST` | `/api/approvals/{id}/resolve` | Approve or reject an action |
| `WS` | `/ws/agent-activity` | Real-time agent event stream |

## Roadmap

| Phase | Focus | Status |
|-------|-------|--------|
| Phase 0 | Foundation — Docker, schema, health checks, approval guards | **Complete** |
| Phase 1 | Single agent loop — AgentBase, Engineer Agent, basic dashboard | **Complete** — stress test 100% |
| Phase 2 | Multi-agent collaboration, Prompt Creator, A2A inbound | Planned |
| Phase 3 | Hardening, chaos testing, A2A outbound | Planned |
| Phase 4 | Multi-tenant SaaS, Temporal workflows, marketplace | Planned |

## Documentation

- **[CLAUDE.md](CLAUDE.md)** — Master project document with full architecture, schemas, and policies
- **[DECISIONS.md](DECISIONS.md)** — Architecture Decision Records
- **[BACKLOG.md](BACKLOG.md)** — Captured ideas and deferred scope
- **[CHANGELOG.md](CHANGELOG.md)** — Version history
- **[ERRORLOG.md](ERRORLOG.md)** — Bug tracking and prevention rules
- **[AGENTS.md](AGENTS.md)** — AI agent coding policy and workflow rules

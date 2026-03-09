# Phase 2 Implementation Plan — Multi-Agent + Prompt Creator + A2A Inbound

## Current State Summary

Phase 0 and Phase 1 are **complete**. The following is working:
- Full infrastructure: Docker Compose (5 services), Kafka KRaft, PostgreSQL 16 + pgvector, Redis 7
- AgentBase with guard chain (idempotency → budget → memory → execute → write → publish)
- EngineerAgent + thin CEOAgent (router only, no decomposition)
- Tools: `web_search`, `file_read`, `code_execute`, `file_write` via adapter
- Memory system: episodic (pgvector), semantic (key-value), working (Redis)
- ModelFactory supporting 8 LLM providers
- Token budget + daily spend cap enforcement
- Human approval flow for irreversible tools
- Frontend dashboard with task submission, WebSocket streaming, approvals UI
- 50-task stress test passed at 100%
- All 9 DB tables migrated, all 16 Kafka topics defined

**What does NOT exist yet:**
- AnalystAgent, WriterAgent, QAAgent implementations (only `__init__.py` placeholders)
- CEO full task decomposition (currently routes everything to Engineer)
- Meeting room pattern
- Prompt Creator Agent
- A2A Gateway (only empty `__init__.py` in `gateway/`)
- Task trace view, multi-provider cost dashboard
- Auto-fail on heartbeat silence (BACKLOG-016)
- `web_fetch`, `send_email`, `git_push`, `memory_read` tools in adapter

---

## Phase 2 Breakdown — 5 Weeks (Weeks 4–8)

### Week 4 — New Agent Implementations + Missing Tools

**Step 1: Add missing tools to adapter.py and registry.py**
- Add `tool_web_fetch(url: str) -> str` — HTTP GET + content extraction (read-only)
- Add `tool_send_email(to: str, subject: str, body: str) -> str` — irreversible, requires approval
- Add `tool_git_push(repo: str, branch: str, message: str) -> str` — irreversible, requires approval
- Add `tool_memory_read(agent_role: str, namespace: str, key: str) -> str` — read-only, for Prompt Creator
- Update `TOOL_REGISTRY` in `registry.py` to match the full table from CLAUDE.md §8:
  - Analyst: `[web_search, web_fetch, file_read, file_write]`
  - Writer: `[web_search, file_read, file_write, send_email]`
  - QA: `[file_read, web_search]` (already correct)
  - Prompt Creator: `[web_search, file_read, memory_read]`
- Update `IRREVERSIBLE_TOOLS` set to include `tool_send_email`, `tool_git_push`

**Step 2: Manual prompt testing for Analyst, Writer, QA**
- Write system prompts for each role (following §23 Risk 3 prevention)
- Each prompt must be tested before coding the agent class
- Seed prompts into `prompts` table (version=1, authored_by='human')
- Update `db/seed.py` to include Analyst, Writer, QA agent records

**Step 3: Implement AnalystAgent**
- File: `backend/nexus/agents/analyst.py`
- Extends AgentBase, same pattern as EngineerAgent
- Tools: web_search, web_fetch, file_read, file_write
- Subscribes to: `agent.commands` (role=analyst)
- Specialization: research tasks, data analysis, report generation
- Include memory context loading (similar episodes + working memory)

**Step 4: Implement WriterAgent**
- File: `backend/nexus/agents/writer.py`
- Extends AgentBase, same pattern as EngineerAgent
- Tools: web_search, file_read, file_write, send_email
- Subscribes to: `agent.commands` (role=writer)
- Specialization: content writing, email drafting, documentation

**Step 5: Implement QAAgent**
- File: `backend/nexus/agents/qa.py`
- Extends AgentBase, same pattern but subscribes to `task.review_queue`
- Tools: file_read, web_search
- Publishes to: `task.results` (not `agent.responses`)
- Specialization: reviews outputs, checks quality, approves/rejects

**Step 6: Update agent factory**
- Update `agents/factory.py` to handle `AgentRole.ANALYST`, `AgentRole.WRITER`, `AgentRole.QA`
- Import and instantiate each new agent class
- Update `agents/runner.py` to support running all agent roles

**Step 7: Unit tests for new agents**
- Test each agent's `handle_task()` with mocked LLM
- Test tool registry enforcement per role
- Test QA agent publishes to `task.results` (not `agent.responses`)

---

### Week 5 — CEO Full Decomposition + Multi-Agent Flow

**Step 8: Upgrade CEO to full task decomposition**
- Rewrite `agents/ceo.py` to use LLM for task analysis
- CEO receives task on `task.queue`, uses LLM to:
  1. Analyze the task instruction
  2. Determine which agents are needed (single or multi-agent)
  3. Decompose into subtasks with `parent_task_id` linking
  4. Route each subtask to the correct agent via `agent.commands`
- CEO also subscribes to `agent.responses` to aggregate results
- When all subtasks complete → CEO publishes to `task.review_queue` for QA
- Create subtask records in `tasks` table with `parent_task_id` FK

**Step 9: CEO response aggregation logic**
- CEO tracks subtask completion state in Redis working memory
- Pattern: `working:{ceo_agent_id}:{parent_task_id}` stores subtask IDs + statuses
- When all subtasks return on `agent.responses`:
  - Aggregate outputs into a single coherent result
  - Publish aggregated output to `task.review_queue`
- Handle partial failures: if one subtask fails, CEO can retry or escalate

**Step 10: QA review pipeline**
- QA Agent receives aggregated result on `task.review_queue`
- Evaluates quality against criteria
- If approved → publishes final result to `task.results`
- If rejected → publishes back to `agent.commands` with feedback for rework
- Result consumer (already exists) picks up `task.results` and updates DB

**Step 11: Meeting room pattern**
- Create temporary Kafka topic pattern: `meeting.room.{task_id}`
- CEO creates meeting when agents need to debate/collaborate on a subtask
- Participating agents subscribe to the meeting topic temporarily
- CEO moderates: poses questions, collects responses, drives to conclusion
- Termination: CEO decides when meeting is over (simplest approach for now, addresses BACKLOG-004)
- Clean up: unsubscribe from meeting topic when done

**Step 12: Full task trace view in dashboard**
- New API endpoint: `GET /api/tasks/{id}/trace` — returns parent + all subtasks tree
- Frontend component: tree view showing task decomposition
- Show which agent handled each subtask, status, tokens used, duration
- Link to episodic memory for each subtask

**Step 13: Behavior tests for multi-agent flow**
- Test: CEO decomposes a multi-step task into correct subtasks
- Test: Each subtask routes to the correct agent by role
- Test: CEO aggregation waits for all subtasks
- Test: QA review → approval → task.results flow
- Test: QA review → rejection → rework flow
- Test: Meeting room creation, message exchange, termination

---

### Week 6 — All Task Types + Auto-Fail + E2E Tests

**Step 14: Verify all 4 task categories end-to-end**
- Software engineering (Engineer) — already working from Phase 1
- Research & analysis (Analyst) — test with a real research task
- Content writing (Writer) — test with a blog post + email draft
- Business operations (CEO + multiple agents) — test multi-agent coordination

**Step 15: Implement auto-fail on heartbeat silence (BACKLOG-016)**
- New file: `backend/nexus/agents/health_monitor.py`
- Background service that consumes `agent.heartbeat` topic
- Tracks last heartbeat per agent in Redis: `heartbeat:{agent_id}` with timestamp
- Every 60 seconds, scans for tasks assigned to agents with no heartbeat in 5 minutes
- Auto-fails those tasks: updates DB status → publishes error to `agent.responses`
- Logs to `audit_log` table

**Step 16: E2E test suite**
- Write comprehensive `make test-e2e` tests:
  - Multi-agent task: "Research X and write a summary email"
  - Single-agent task: "Debug this code snippet"
  - QA rejection + rework cycle
  - Token budget enforcement mid-task
  - Heartbeat auto-fail (stop agent, verify task fails)
- All E2E tests use the `test:` model provider for zero-cost runs

---

### Weeks 6–7 — Prompt Creator Agent

**Step 17: Seed benchmark test cases**
- Write 10 benchmark test cases per agent role (Engineer, Analyst, Writer, QA, CEO)
- Each benchmark: fixed input instruction + expected output criteria (JSON)
- Seed into `prompt_benchmarks` table via migration or seed script
- Criteria examples: "must include code example", "must cite sources", "must be < 500 words"

**Step 18: Migrate existing prompts into versioned table**
- Move all hardcoded system prompts from `db/seed.py` into `prompts` table
- Each prompt: version=1, authored_by='human', is_active=true
- Agents load system prompt from `prompts` table at startup (not from seed data)
- Update `agents/factory.py` to query active prompt from DB

**Step 19: Implement PromptCreatorAgent**
- File: `backend/nexus/agents/prompt_creator.py`
- Subscribes to: `prompt.improvement_requests`, `prompt.benchmark_requests`
- Tools: web_search, file_read, memory_read
- Workflow:
  1. Read episodic memory of target agent (via `memory_read` tool)
  2. Identify failure patterns from recent episodes
  3. Draft improved system prompt
  4. Run against benchmark test cases
  5. Score results (LLM-as-judge or criteria matching)
  6. Publish proposal to `prompt.proposals`
  7. Create `human_approvals` record — NEVER auto-deploy
- Store proposed prompt in `prompts` table (is_active=false, authored_by='prompt_creator_agent')

**Step 20: Prompt approval UI**
- New frontend page: `/prompts`
- Shows diff between current active prompt and proposed prompt (side-by-side)
- Displays benchmark scores (current vs proposed)
- Approve button → sets `is_active=true` on new version, `is_active=false` on old
- Reject button → marks proposal as rejected
- API endpoints:
  - `GET /api/prompts` — list all prompts, grouped by role
  - `GET /api/prompts/{id}/diff` — diff between versions
  - `POST /api/prompts/{id}/activate` — requires approval record

**Step 21: Trigger logic for Prompt Creator**
- Auto-trigger: when agent failure rate > 10% in last 20 tasks (checked by health monitor)
- Manual trigger: API endpoint `POST /api/prompts/improve` with `agent_role` param
- Both publish to `prompt.improvement_requests` topic

**Step 22: Update agent factory for Prompt Creator**
- Add `AgentRole.PROMPT_CREATOR` case to `agents/factory.py`
- Prompt Creator uses Claude Sonnet (analytical reasoning)
- Run first improvement against Engineer Agent failures from Phase 1 stress test data

---

### Weeks 7–8 — A2A Gateway (Inbound)

**Step 23: A2A Pydantic schemas**
- File: `backend/nexus/gateway/schemas.py`
- Models: `AgentCard`, `A2ATask`, `A2AEvent`, `A2ATaskStatus`
- AgentCard matches the JSON structure from CLAUDE.md §9
- A2ATask: external task submission with skill_id, input, metadata
- A2AEvent: SSE event model (status_update, artifact, completion)

**Step 24: A2A authentication**
- File: `backend/nexus/gateway/auth.py`
- Bearer token validation for inbound calls
- Token storage: new `a2a_tokens` table (or column in existing table)
  - token_hash, allowed_skills, rate_limit, created_at, expires_at
- Middleware that validates token before any A2A route
- Return 401 for invalid/expired tokens

**Step 25: A2A gateway routes**
- File: `backend/nexus/gateway/routes.py`
- `GET /.well-known/agent.json` — serves the Agent Card (static JSON from config)
- `POST /a2a` — receives external task:
  1. Validate bearer token
  2. Validate task against A2ATask schema
  3. Map skill_id to agent role
  4. Create task in DB with `source='a2a'`, `source_agent=caller_identity`
  5. Publish to Kafka: `Topics.A2A_INBOUND`
  6. Return task ID + status URL
- `GET /a2a/{id}/stream` — SSE endpoint:
  1. Validate bearer token
  2. Subscribe to Redis pub/sub `agent_activity:{task_id}`
  3. Stream events as SSE (Server-Sent Events)
  4. Close stream on task completion

**Step 26: CEO routing for A2A tasks**
- CEO already subscribes to `Topics.A2A_INBOUND`
- A2A tasks arrive as standard `AgentCommand` — identical to human tasks
- CEO routes them through the same decomposition logic
- No special handling needed in agent code (gateway handles the translation)

**Step 27: A2A outbound placeholder**
- File: `backend/nexus/gateway/outbound.py`
- Stub class with `async def hire_external_agent()` — raises NotImplementedError
- Placeholder for Phase 3 — documented in BACKLOG

**Step 28: A2A integration tests**
- Simulate external A2A call end-to-end:
  1. POST /a2a with valid bearer token + task
  2. Verify task created in DB with source='a2a'
  3. Verify Kafka message published to `a2a.inbound`
  4. Verify CEO picks it up and routes to specialist
  5. Verify SSE stream delivers progress updates
  6. Verify final result returned via SSE
- Test invalid token → 401
- Test invalid task schema → 400
- Test rate limiting

**Step 29: Register A2A routes with Litestar app**
- Add gateway routes to `api/router.py`
- Add A2A token seeding to `db/seed.py` (dev token for testing)
- Update `GET /health` to report A2A gateway status

---

## Cross-Cutting Concerns (Throughout Phase 2)

**Audit logging:**
- Every A2A interaction → `audit_log` table
- Every prompt change proposal → `audit_log` table
- Every QA review decision → `audit_log` table

**Dashboard enhancements:**
- Multi-agent task trace view (tree of subtasks)
- Prompt management page (diff + benchmark scores)
- A2A inbound task list (filtered by source='a2a')

**Documentation updates:**
- Update CHANGELOG.md with every significant change
- Update DECISIONS.md with new ADRs
- Update BACKLOG.md — resolve items addressed, add new discoveries

---

## Definition of Done — Phase 2

Submit: "Write a competitive analysis of [X] and draft an email summary."
- CEO decomposes into: research subtask (Analyst) + email draft subtask (Writer)
- Analyst researches using web_search + web_fetch
- Writer drafts email using research output
- QA reviews the combined output
- Final result delivered to dashboard
- Full task trace visible (parent → subtasks → outputs)

External A2A test:
- POST /a2a with valid token completes end-to-end
- SSE stream delivers real-time progress
- Result returned to external caller

Prompt Creator:
- Produces a measurably improved prompt for at least one agent
- Human approval required and working via UI

All E2E tests passing via `make test-e2e`.

---

## Files to Create/Modify

### New files:
1. `backend/nexus/agents/analyst.py`
2. `backend/nexus/agents/writer.py`
3. `backend/nexus/agents/qa.py`
4. `backend/nexus/agents/prompt_creator.py`
5. `backend/nexus/agents/health_monitor.py`
6. `backend/nexus/gateway/routes.py`
7. `backend/nexus/gateway/schemas.py`
8. `backend/nexus/gateway/auth.py`
9. `backend/nexus/gateway/outbound.py`
10. `backend/nexus/api/prompts.py` (prompt management endpoints)
11. `backend/nexus/tests/unit/test_analyst.py`
12. `backend/nexus/tests/unit/test_writer.py`
13. `backend/nexus/tests/unit/test_qa.py`
14. `backend/nexus/tests/unit/test_prompt_creator.py`
15. `backend/nexus/tests/unit/test_a2a_gateway.py`
16. `backend/nexus/tests/behavior/test_multi_agent_flow.py`
17. `backend/nexus/tests/behavior/test_qa_review.py`
18. `backend/nexus/tests/e2e/test_a2a_integration.py`
19. `frontend/src/components/prompts/PromptDiffView.tsx`
20. `frontend/src/components/tasks/TaskTraceView.tsx`

### Modified files:
1. `backend/nexus/tools/adapter.py` — add web_fetch, send_email, git_push, memory_read
2. `backend/nexus/tools/registry.py` — update tool access map
3. `backend/nexus/agents/ceo.py` — full decomposition logic
4. `backend/nexus/agents/factory.py` — register all new agents
5. `backend/nexus/agents/runner.py` — support all roles
6. `backend/nexus/api/router.py` — register new routes
7. `backend/nexus/app.py` — register A2A gateway routes
8. `backend/nexus/db/seed.py` — seed new agents + prompts + dev A2A token
9. `frontend/src/App.tsx` — add prompt management page
10. `frontend/src/api/client.ts` — add new API calls
11. `frontend/src/hooks/` — add usePrompts, useTaskTrace hooks

### Possible new migration:
- `002_a2a_tokens.py` — if we add a dedicated `a2a_tokens` table for bearer token storage

---

## Execution Order (Recommended)

1. **Week 4:** Steps 1–7 (tools + 3 new agents + factory + tests)
2. **Week 5:** Steps 8–13 (CEO decomposition + multi-agent flow + meeting room)
3. **Week 6:** Steps 14–16 (all task types verified + auto-fail + E2E)
4. **Weeks 6–7:** Steps 17–22 (Prompt Creator Agent)
5. **Weeks 7–8:** Steps 23–29 (A2A Gateway inbound)

This order ensures each layer builds on verified foundations — new agents before multi-agent coordination, multi-agent before Prompt Creator (needs failure data), and A2A last (most independent).

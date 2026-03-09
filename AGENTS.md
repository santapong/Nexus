# AGENTS.md — AI Agent Coding Policy
## NEXUS Project — Machine-Readable Instructions

> **This file is written for AI agents (Claude Code, Engineer Agent, and any automated
> coding tool) working on the NEXUS codebase.**
>
> Read this file completely before touching any code.
> Read `CLAUDE.md` completely before reading this file.
> The order matters: CLAUDE.md = what to build. AGENTS.md = how to build it.

---

## Table of Contents

1.  [Before You Write a Single Line](#1-before-you-write-a-single-line)
2.  [Understand Your Task Scope](#2-understand-your-task-scope)
3.  [Coding Workflow — Step by Step](#3-coding-workflow--step-by-step)
4.  [File & Module Rules](#4-file--module-rules)
5.  [Python Rules — Enforced](#5-python-rules--enforced)
6.  [TypeScript Rules — Enforced](#6-typescript-rules--enforced)
7.  [Database Rules — Enforced](#7-database-rules--enforced)
8.  [Testing Rules — Before You Ship](#8-testing-rules--before-you-ship)
9.  [How to Update CHANGELOG.md](#9-how-to-update-changelogmd)
10. [How to Update ERRORLOG.md](#10-how-to-update-errorlogmd)
11. [When to Create a Decision Record](#11-when-to-create-a-decision-record)
12. [Commit & Branch Rules](#12-commit--branch-rules)
13. [Pull Request Checklist](#13-pull-request-checklist)
14. [What You Must NEVER Do](#14-what-you-must-never-do)
15. [When to Stop and Ask for Human Input](#15-when-to-stop-and-ask-for-human-input)

---

## 1. Before You Write a Single Line

Execute these steps in order. Do not skip any.

### Step 1 — Read CLAUDE.md

```
Location: /nexus/CLAUDE.md
Read: All sections relevant to the module you are about to touch.
Minimum: §3 Architecture, §16–19 Coding Policies, §20 Agent Operational Policy.
```

### Step 2 — Read DECISIONS.md

```
Location: /nexus/docs/DECISIONS.md
Read: All entries. Understand every architectural decision already made.
Purpose: Do not re-open closed decisions. Do not implement something
         that contradicts a recorded decision.
```

### Step 3 — Read ERRORLOG.md

```
Location: /nexus/docs/ERRORLOG.md
Read: Last 10 entries minimum.
Purpose: Do not repeat a mistake that has already been made and logged.
         Check if the area you're about to touch has known issues.
```

### Step 4 — Understand the existing code in the module you're changing

```python
# Before editing any file, read:
# 1. The file itself — understand what it already does
# 2. All files it imports from
# 3. All files that import it (dependents)
# Never assume. Read the actual code.
```

### Step 5 — State your plan before coding

Before writing any code, write a comment block at the top of your working notes:

```
# TASK: {what I am building}
# FILES I WILL CHANGE: {list}
# FILES I WILL CREATE: {list}
# TESTS I WILL WRITE: {list}
# DEFINITION OF DONE: {one sentence}
# ESTIMATED RISK: low | medium | high
# IF HIGH RISK: {why, and mitigation}
```

If you cannot complete Step 5, the task scope is unclear. Stop and ask for clarification.

---

## 2. Understand Your Task Scope

### Scope boundaries — respect them strictly

| Boundary | Rule |
|----------|------|
| Your task description | Only implement what is described. Nothing more. |
| BACKLOG.md | If you think of something useful not in scope → add to BACKLOG.md, do not implement now. |
| Refactoring | Only refactor code you are already changing. Do not refactor unrelated code. |
| Dependencies | Do not add a new dependency without writing a Decision Record in DECISIONS.md. |
| Schema changes | Do not change the database schema without an Alembic migration. |
| New Kafka topics | Do not create new topics without adding to `Topics` class in `kafka/topics.py`. |

### The BACKLOG.md rule

If you find something worth improving that is outside your current task:

```markdown
<!-- Add to /nexus/docs/BACKLOG.md, do not act on it -->
## [DATE] Discovered during [task description]
- **Observation:** {what you noticed}
- **Suggested action:** {what could be done}
- **Priority estimate:** low | medium | high
```

Do not implement it. Add it and move on.

---

## 3. Coding Workflow — Step by Step

Follow this exact sequence for every task. Do not reorder.

```
┌─────────────────────────────────────────────────────────────────┐
│  1. READ      Read CLAUDE.md, DECISIONS.md, ERRORLOG.md        │
│  2. PLAN      State task, files, tests, DoD before coding      │
│  3. TEST FIRST Write failing tests before implementation        │
│  4. IMPLEMENT  Write the code to make tests pass               │
│  5. LINT       ruff check . — fix all issues before proceeding │
│  6. TYPECHECK  mypy nexus/ --strict — fix all issues           │
│  7. TEST       pytest tests/unit/ — all must pass              │
│  8. REVIEW     Re-read your own code once before committing    │
│  9. CHANGELOG  Update CHANGELOG.md — required before commit    │
│  10. ERRORLOG  Update ERRORLOG.md if any errors were found     │
│  11. DECISIONS Write ADR if an architectural decision was made │
│  12. COMMIT    Follow commit format exactly                    │
│  13. PR        Fill PR checklist completely                    │
└─────────────────────────────────────────────────────────────────┘
```

### Step 3 detail — Test First

Write the test file before the implementation file.
The test must fail before you write the implementation.
The test must pass after you write the implementation.
This is not optional.

```python
# CORRECT order:
# 1. Write tests/unit/test_my_feature.py  ← tests fail
# 2. Write nexus/my_feature.py           ← tests pass
# 3. Run pytest tests/unit/test_my_feature.py — confirm pass

# WRONG order:
# 1. Write nexus/my_feature.py
# 2. Write tests after ← you are testing what you wrote, not what you intended
```

### Step 8 detail — Self-Review Checklist

Before committing, re-read every file you changed and ask:

- [ ] Does every function have a type hint on every parameter and return value?
- [ ] Does every function that does I/O use `async/await`?
- [ ] Does every log line include `task_id` and `trace_id`?
- [ ] Is there any hardcoded string that should be a constant?
- [ ] Is there any `print()` statement? (must remove — fails CI)
- [ ] Is there any hardcoded secret, URL, or port? (must remove)
- [ ] Is there any raw `dict` crossing a module boundary? (use Pydantic model)
- [ ] Is there a Kafka topic string that isn't using `Topics.CONSTANT`?
- [ ] Is there an MCP tool call that doesn't go through `tools/registry.py`?

If any answer is "yes" — fix it before committing.

---

## 4. File & Module Rules

### One responsibility per file

Each file has one clear job. If you find yourself writing "and also" when describing
what a file does, it needs to be split.

```
GOOD: producer.py — Kafka message producer
GOOD: consumer.py — Kafka message consumer
BAD:  kafka.py — Kafka producer, consumer, and topic management
```

### File size limits

| File type | Soft limit | Hard limit |
|-----------|------------|------------|
| Any `.py` file | 200 lines | 400 lines |
| Any function | 30 lines | 50 lines |
| Any class | 150 lines | 300 lines |

Exceeding the hard limit requires a comment explaining why.
It almost always means the file should be split.

### Import rules

```python
# CORRECT import order (ruff enforces this):
# 1. Standard library
import asyncio
from uuid import UUID

# 2. Third-party
from pydantic import BaseModel
from litestar import get

# 3. Internal — always absolute imports
from nexus.kafka.topics import Topics
from nexus.db.models import Task

# NEVER use relative imports in this project
# BAD:  from ..kafka.topics import Topics
# GOOD: from nexus.kafka.topics import Topics
```

### Settings rule

```python
# CORRECT — always via settings module
from nexus.settings import settings
db_url = settings.DATABASE_URL

# WRONG — never direct env access
import os
db_url = os.environ["DATABASE_URL"]  # banned
```

---

## 5. Python Rules — Enforced

These rules are checked by CI. Violations fail the build.

### Type hints — mandatory everywhere

```python
# CORRECT
async def process_task(task_id: UUID, trace_id: UUID, instruction: str) -> TaskResult:
    ...

# WRONG — missing type hints
async def process_task(task_id, trace_id, instruction):
    ...
```

When `Any` is genuinely unavoidable:

```python
from typing import Any

# CORRECT — explain why Any is used
data: Any  # third-party library returns untyped JSON blob, validated below by Pydantic
```

### Async/await — all I/O is async

```python
# CORRECT
async def get_task(task_id: UUID) -> Task:
    async with db_session() as session:
        return await session.get(Task, task_id)

# WRONG — sync DB call in async context
def get_task(task_id: UUID) -> Task:
    with db_session() as session:
        return session.get(Task, task_id)  # blocks the event loop
```

When sync call is unavoidable:

```python
import asyncio

# CORRECT — wrap sync in thread
result = await asyncio.to_thread(some_sync_library_call, arg1, arg2)
```

### task_id and trace_id propagation — mandatory

```python
# CORRECT — every I/O function receives and passes through both IDs
async def write_memory(
    agent_id: UUID,
    task_id: UUID,    # always present
    trace_id: UUID,   # always present
    summary: str,
) -> None:
    logger.info("writing episodic memory", extra={
        "task_id": str(task_id),
        "trace_id": str(trace_id),
        "agent_id": str(agent_id),
    })
    ...

# WRONG — IDs not propagated
async def write_memory(agent_id: UUID, summary: str) -> None:
    ...
```

### Pydantic models at all boundaries

```python
# CORRECT — Pydantic model crosses module boundary
class TaskResult(BaseModel):
    task_id: UUID
    output: str
    tokens_used: int
    outcome: Literal["success", "failed", "partial"]

async def complete_task(result: TaskResult) -> None: ...

# WRONG — raw dict crosses module boundary
async def complete_task(result: dict) -> None: ...
```

### Structured logging — no print()

```python
import structlog
logger = structlog.get_logger()

# CORRECT
logger.info(
    "task_completed",
    task_id=str(task_id),
    trace_id=str(trace_id),
    agent_id=agent_id,
    tokens_used=tokens_used,
    outcome=outcome,
)

# WRONG — print is banned
print(f"Task {task_id} completed")  # fails CI
```

### Exception handling

```python
# CORRECT — specific exception + always log before re-raising or handling
try:
    result = await kafka.publish(Topics.AGENT_RESPONSES, message)
except KafkaConnectionError as e:
    logger.error(
        "kafka_publish_failed",
        task_id=str(task_id),
        topic=Topics.AGENT_RESPONSES,
        error=str(e),
    )
    raise  # re-raise after logging

# WRONG — bare except swallows the error silently
try:
    result = await kafka.publish(Topics.AGENT_RESPONSES, message)
except Exception:
    pass  # banned — never swallow exceptions silently
```

### Docstrings — mandatory on all public functions and classes

```python
# CORRECT
async def load_context(agent_id: UUID, task_id: UUID, instruction: str) -> AgentContext:
    """Load relevant memory context for an agent before task execution.

    Queries episodic memory for semantically similar past tasks and
    semantic memory for relevant project facts. Both are included in
    the returned context for injection into the LLM prompt.

    Args:
        agent_id: The agent that will receive this context.
        task_id: Current task identifier for logging.
        instruction: The task instruction used for semantic similarity search.

    Returns:
        AgentContext with episodic memories and semantic facts.

    Raises:
        MemoryReadError: If PostgreSQL is unreachable.
    """
    ...

# WRONG — no docstring on public function
async def load_context(agent_id: UUID, task_id: UUID, instruction: str) -> AgentContext:
    ...
```

---

## 6. TypeScript Rules — Enforced

### Strict TypeScript — no `any`

```typescript
// CORRECT
interface TaskResult {
  task_id: string;
  output: string;
  tokens_used: number;
  outcome: 'success' | 'failed' | 'partial';
}

async function fetchTask(taskId: string): Promise<TaskResult> { ... }

// WRONG
async function fetchTask(taskId: any): Promise<any> { ... }
```

### TanStack Query for all server state

```typescript
// CORRECT — data fetching in a hook
// src/hooks/useTask.ts
export function useTask(taskId: string) {
  return useQuery({
    queryKey: ['task', taskId],
    queryFn: () => taskApi.getTask(taskId),
  });
}

// Component uses the hook — no fetch logic
export function TaskView({ taskId }: { taskId: string }) {
  const { data, isLoading } = useTask(taskId);
  ...
}

// WRONG — fetch in component
export function TaskView({ taskId }: { taskId: string }) {
  useEffect(() => {
    fetch(`/api/tasks/${taskId}`).then(...);  // banned
  }, [taskId]);
}
```

### Component responsibilities

```typescript
// CORRECT — component renders only, no business logic
export function AgentCard({ agentId }: { agentId: string }) {
  const { data: agent } = useAgent(agentId);           // hook handles data
  const handleApprove = useApproveAction(agentId);     // hook handles action

  return <div onClick={handleApprove}>{agent?.name}</div>;
}

// WRONG — business logic in component
export function AgentCard({ agentId }: { agentId: string }) {
  const [agent, setAgent] = useState(null);
  useEffect(() => {                                     // data fetch in component
    fetch(`/api/agents/${agentId}`).then(r => r.json()).then(setAgent);
  }, []);
  const handleApprove = async () => {                  // business logic in component
    await fetch(`/api/approvals/${agentId}`, { method: 'POST' });
  };
}
```

### Environment variables

```typescript
// CORRECT
const apiUrl = import.meta.env.VITE_API_URL;

// WRONG — hardcoded URL
const apiUrl = 'http://localhost:8000';
```

---

## 7. Database Rules — Enforced

### All schema changes via Alembic

```bash
# CORRECT — generate a migration
alembic revision --autogenerate -m "add_cost_estimate_to_tasks"
# Review the generated migration file
# Never run directly — always via: make migrate

# WRONG — never run DDL directly
# psql -c "ALTER TABLE tasks ADD COLUMN cost_estimate numeric(10,4);"
```

### Migration file rules

Every migration file must have:
1. A descriptive name: `add_cost_estimate_to_tasks`, not `update_table`
2. Both `upgrade()` and `downgrade()` implemented
3. A comment at the top explaining why the change is needed

```python
"""Add cost_estimate column to tasks table.

Needed by the Costing Agent to store pre-execution cost estimates
for comparison against actual costs in llm_usage.

Revision ID: abc123
"""
```

### Never delete columns directly

```python
# CORRECT — deprecation pattern
# Step 1: Add deprecated_at column (this migration)
op.add_column('tasks', sa.Column('deprecated_old_field_at', sa.DateTime, nullable=True))

# Step 2: Stop writing to old_field in application code
# Step 3: In a LATER migration (after deployment confirms no reads):
# op.drop_column('tasks', 'old_field')

# WRONG — immediate drop
op.drop_column('tasks', 'old_field')  # breaks running agents that still reference it
```

### Query rules

```python
# CORRECT — parameterized query via Advanced Alchemy
result = await session.execute(
    select(Task).where(Task.assigned_agent_id == agent_id)
)

# WRONG — raw SQL with interpolation (SQL injection + no type safety)
result = await session.execute(
    f"SELECT * FROM tasks WHERE assigned_agent_id = '{agent_id}'"
)
```

---

## 8. Testing Rules — Before You Ship

### Coverage requirement

Unit tests must cover:
- The happy path
- At least one failure path
- Boundary conditions (empty inputs, max values)

`pytest --cov=nexus --cov-fail-under=80` must pass before any PR.

### Test structure

```python
# tests/unit/test_agent_memory.py

import pytest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from nexus.memory.episodic import EpisodicMemory
from nexus.db.models import EpisodicMemoryRecord


class TestEpisodicMemoryWrite:
    """Tests for EpisodicMemory.write_episode()."""

    async def test_write_episode_success(self, mock_db_session):
        """Happy path: episode is written and embedding task is queued."""
        memory = EpisodicMemory(session=mock_db_session)
        task_id = uuid4()

        await memory.write_episode(
            agent_id=uuid4(),
            task_id=task_id,
            summary="Test task completed",
            outcome="success",
        )

        mock_db_session.add.assert_called_once()
        mock_db_session.commit.assert_called_once()

    async def test_write_episode_queues_embedding(self, mock_db_session):
        """Embedding generation is queued asynchronously, not blocking."""
        ...

    async def test_write_episode_db_failure_raises(self, mock_db_session):
        """DB failure raises MemoryWriteError, not silently swallowed."""
        mock_db_session.commit.side_effect = Exception("DB unavailable")

        with pytest.raises(MemoryWriteError):
            await memory.write_episode(...)
```

### Naming rules

```python
# CORRECT test names — describe behavior, not implementation
def test_agent_fails_task_when_token_budget_exceeded(): ...
def test_require_approval_pauses_execution_for_irreversible_tools(): ...
def test_kafka_consumer_is_idempotent_on_duplicate_message(): ...

# WRONG test names — describe code, not behavior
def test_check_budget(): ...
def test_require_approval(): ...
def test_consumer(): ...
```

### Mocking rules

```python
# CORRECT — mock external dependencies, test your logic
@pytest.fixture
def mock_kafka_producer():
    return AsyncMock(spec=KafkaProducer)

# WRONG — mock the thing you're testing
@pytest.fixture
def mock_agent_memory():
    return AsyncMock(spec=EpisodicMemory)  # you should be testing EpisodicMemory, not mocking it
```

---

## 9. How to Update CHANGELOG.md

**Update CHANGELOG.md before every commit. No exceptions.**

### When to update

- Every new feature added
- Every bug fixed
- Every refactor that changes behavior
- Every dependency version change
- Every database schema change
- Every new Kafka topic added
- Every new API endpoint added

### Format

```markdown
## [YYYY-MM-DD] — {one-line summary of what changed}

### Added
- {new feature or file} — {why it was added}
- {new API endpoint} — {what it does}

### Changed
- {what changed} — {why it changed, what it was before}

### Fixed
- {bug description} — {root cause, what fixed it}

### Removed
- {what was removed} — {why}

### Database
- Migration: `{migration_name}` — {what it changes}

### Breaking
- {breaking change} — {migration path for callers}

**Authored by:** {agent_name or 'human'}
**Task ID:** {task_id if applicable}
**PR:** #{pr_number}
```

### Example entry

```markdown
## [2026-03-15] — Add EpisodicMemory write_episode() with async embedding

### Added
- `nexus/memory/episodic.py` — EpisodicMemory class with write_episode() and load_context()
- `nexus/memory/embeddings.py` — Google embedding-001 client via Taskiq async task

### Changed
- `nexus/agents/base.py` — AgentBase._execute_with_guards() now calls memory.write_episode()
  before publishing result (previously result was published without memory write)

### Database
- Migration: `add_episodic_memory_table` — creates episodic_memory table with pgvector index

**Authored by:** engineer_agent
**Task ID:** 018e4f2c-3a1b-7d9e-8f4a-2b5c6d7e8f9a
**PR:** #12
```

---

## 10. How to Update ERRORLOG.md

**Update ERRORLOG.md whenever you find a bug, a silent failure, a wrong assumption,
or any unexpected behavior — even if you fix it immediately.**

The purpose is to build a knowledge base of what went wrong so future agents
(and humans) don't make the same mistake twice.

### When to update

- Any bug you find, whether in your own code or existing code
- Any time a test reveals incorrect behavior
- Any time you discover a wrong assumption in CLAUDE.md or AGENTS.md
- Any time an integration between two modules behaves unexpectedly
- Any time you hit an environment or dependency issue
- Any time a CI check fails for a non-obvious reason

### Format

```markdown
## ERROR-{NNN} — {short description}

**Date:** YYYY-MM-DD
**Severity:** critical | high | medium | low
**Status:** open | fixed | mitigated | wont-fix
**Found by:** {agent_name or 'human'} during {task description}
**Affected files:** {list of files}

### What happened
{Describe exactly what the incorrect behavior was. Be specific.}

### Root cause
{Why did it happen? What was the wrong assumption or missing guard?}

### Fix applied
{What was changed to fix it? Link to commit or PR if applicable.}
{If status is 'open', describe what fix is needed.}

### Prevention
{What rule, test, or guard prevents this from happening again?}
{If a new test was written, name it.}
{If CLAUDE.md or AGENTS.md should be updated, note what section.}

---
```

### Example entry

```markdown
## ERROR-001 — EpisodicMemory write called after result published

**Date:** 2026-03-15
**Severity:** high
**Status:** fixed
**Found by:** engineer_agent during test_agent_base_guard_chain
**Affected files:** nexus/agents/base.py

### What happened
In AgentBase._execute_with_guards(), the result was published to Kafka before
write_episode() was called. If write_episode() failed (e.g. DB unavailable),
the task was marked completed externally but had no memory entry. Future tasks
for the same agent had a gap in episodic history.

### Root cause
The original implementation had the sequence:
  1. handle_task()
  2. kafka.publish(result)   ← wrong: published before memory saved
  3. memory.write_episode()

The CLAUDE.md spec says memory write MUST happen before publish, but this
ordering was not enforced by a test.

### Fix applied
Reordered in base.py to:
  1. handle_task()
  2. memory.write_episode()  ← now first
  3. kafka.publish(result)   ← only after memory is confirmed written
Also added test: test_memory_written_before_result_published() in tests/behavior/

### Prevention
- Test test_memory_written_before_result_published() now guards this ordering.
- AGENTS.md §3 Step 3 now explicitly mentions this as a behavior test target.

---
```

### Error severity guide

| Severity | Meaning |
|----------|---------|
| `critical` | Data loss, security issue, or silent incorrect behavior that corrupts state |
| `high` | Incorrect behavior that affects task outcomes or agent memory |
| `medium` | Incorrect behavior that degrades quality but doesn't corrupt state |
| `low` | Minor issue, cosmetic bug, or suboptimal but not wrong behavior |

---

## 11. When to Create a Decision Record

Write a new entry in `DECISIONS.md` whenever you make an architectural decision
that future code will depend on.

### Triggers — always write an ADR when you:

- Add a new Python dependency to `pyproject.toml`
- Add a new npm package to `package.json`
- Choose between two implementation approaches
- Change the interface between two modules
- Add a new Kafka topic
- Add a new database table or significant column
- Change the structure of a Pydantic model that is used in Kafka messages
- Choose a third-party service or API
- Override or modify a decision already recorded in DECISIONS.md

### Do NOT write an ADR for:

- Bug fixes that don't change architecture
- Adding a new function inside an existing module
- Writing tests
- Updating documentation
- Reformatting code

### Decision record format (see DECISIONS.md for full template)

```markdown
## ADR-{NNN} — {short title}

**Date:** YYYY-MM-DD
**Status:** proposed | accepted | superseded | deprecated
**Decided by:** {agent_name or 'human'}
**Relates to:** {CLAUDE.md section or other ADR}

### Context
{What situation forced this decision? What were the constraints?}

### Decision
{What was decided? Be specific.}

### Alternatives considered
{What else was considered and why it was rejected?}

### Consequences
{What does this decision enable? What does it constrain?
What will be harder because of this decision?}
```

---

## 12. Commit & Branch Rules

### Branch naming

```bash
# CORRECT
feature/add-costing-agent
fix/kafka-consumer-idempotency-gap
chore/update-pydantic-ai-dependency
agent/018e4f2c/add-episodic-memory-write   # agent branches include task_id

# WRONG
my-feature
fix
update
```

### Commit message format — Conventional Commits

```
type(scope): short description in imperative mood

[optional body: explain WHY, not WHAT]

[optional footer: BREAKING CHANGE, closes #issue]
```

**Types:** `feat` | `fix` | `chore` | `test` | `docs` | `refactor` | `perf`

**Scopes:** `backend` | `frontend` | `kafka` | `db` | `agents` | `tools` | `gateway` | `infra`

```bash
# CORRECT commits
feat(agents): add EpisodicMemory write_episode with async embedding generation
fix(kafka): ensure consumer is idempotent on duplicate message delivery
chore(db): add migration for human_approvals table
test(agents): add behavior tests for AgentBase guard chain ordering
docs(agents): update AGENTS.md with embedding timing decision

# WRONG commits
update agents
fix bug
WIP
added stuff
```

### Commit size rule

One commit = one logical change. If your commit message needs "and" in it,
consider splitting into two commits.

```bash
# WRONG — two unrelated changes in one commit
feat(agents): add episodic memory write and fix kafka consumer bug

# CORRECT — separate commits
feat(agents): add episodic memory write with async embedding
fix(kafka): resolve duplicate message handling in consumer base class
```

---

## 13. Pull Request Checklist

Before opening a PR, confirm every item:

### Code quality
- [ ] `ruff check .` passes with zero warnings
- [ ] `mypy nexus/ --strict` passes with zero errors
- [ ] No `print()` statements anywhere in changed files
- [ ] No hardcoded secrets, URLs, or ports
- [ ] All new functions have type hints
- [ ] All public functions have docstrings
- [ ] All new Kafka topic strings use `Topics.CONSTANT`

### Tests
- [ ] New unit tests written for new code (test file exists before implementation)
- [ ] `pytest tests/unit/ --cov=nexus --cov-fail-under=80` passes
- [ ] `pytest tests/behavior/` passes (if behavior tests affected)
- [ ] All tests written following the naming convention in §8

### Documentation
- [ ] `CHANGELOG.md` updated with this change
- [ ] `ERRORLOG.md` updated if any bugs were found during development
- [ ] `DECISIONS.md` updated if any architectural decision was made
- [ ] `BACKLOG.md` updated if any out-of-scope improvements were noticed

### Architecture
- [ ] No new imports of MCP package directly in agent code (always via `tools/`)
- [ ] No hardcoded Kafka topic strings (always `Topics.CONSTANT`)
- [ ] No raw `dict` objects crossing module boundaries (Pydantic models)
- [ ] No `os.environ` access (always `settings.`)
- [ ] If irreversible tool added: `require_approval()` guard is present in `adapter.py`
- [ ] If new DB table added: migration file exists and `make migrate` was tested

### PR description must include
- What was built / changed
- Why it was needed
- How it was tested
- Any risks or caveats
- Link to relevant CHANGELOG entry

---

## 14. What You Must NEVER Do

These are absolute prohibitions. No exceptions.

### Never in production code

```python
# 1. Never print() — use structured logger
print("debugging")  # BANNED

# 2. Never hardcode secrets
api_key = "sk-ant-api03-..."  # BANNED

# 3. Never access os.environ directly
db_url = os.environ["DATABASE_URL"]  # BANNED — use settings.DATABASE_URL

# 4. Never use a raw topic string
await kafka.publish("agent.commands", msg)  # BANNED — use Topics.AGENT_COMMANDS

# 5. Never call MCP tools directly from agent code
result = await web_search.search(query)  # BANNED in agent code
# CORRECT: let Pydantic AI call the tool via the registry

# 6. Never swallow exceptions silently
try:
    await risky_operation()
except Exception:
    pass  # BANNED — always log and either handle or re-raise

# 7. Never block the event loop
time.sleep(5)  # BANNED — use await asyncio.sleep(5)
requests.get(url)  # BANNED — use aiohttp or httpx async
```

### Never in database code

```python
# 8. Never drop a column without a deprecation step first
op.drop_column('tasks', 'old_field')  # BANNED without prior deprecation migration

# 9. Never write raw SQL with f-strings
f"SELECT * FROM tasks WHERE id = '{task_id}'"  # BANNED — SQL injection risk
```

### Never in agent behavior

```python
# 10. Never call an irreversible tool without require_approval()
await file_ops.write(path, content)  # BANNED in adapter without require_approval()

# 11. Never publish result before writing episodic memory
await kafka.publish(Topics.AGENT_RESPONSES, result)  # BANNED if memory not written yet
await memory.write_episode(...)  # must come BEFORE publish

# 12. Never make an LLM call without checking token budget first
response = await self.llm.run(...)  # BANNED without prior _check_budget() call
```

### Never in tests

```python
# 13. Never write tests after the implementation
# Write tests first. Verify they fail. Then implement.

# 14. Never mock the thing you are testing
mock_episodic_memory = AsyncMock(spec=EpisodicMemory)  # if you are testing EpisodicMemory
```

---

## 15. When to Stop and Ask for Human Input

Stop coding and request human input when:

### Architectural uncertainty
- The task requires a decision not covered in CLAUDE.md or DECISIONS.md
- You are about to add a new dependency or technology
- You need to change a Pydantic model used in Kafka messages (breaking change)
- You need to modify a table that existing agents are actively reading

### Scope uncertainty
- The task description is ambiguous enough that two valid interpretations exist
- Completing the task requires changing code in more than 5 files
- The task would require adding more than one new database table

### Risk triggers
- You are about to modify `AgentBase` — every agent inherits from it
- You are about to modify `topics.py` — all agents depend on it
- You are about to modify `tools/guards.py` — all irreversible tool calls depend on it
- You are about to modify a database migration that has already been applied

### When to write to human.input_needed (for deployed agents)

If you are the **Engineer Agent running inside NEXUS**, publish to `human.input_needed`:
- Before calling any irreversible tool (`file_write`, `git_push`, `send_email`)
- When token budget reaches 90%
- When you have made 20 tool calls without completing the task
- When you discover the task requires escalated permissions
- When you find a critical bug that affects other agents

**Format for human.input_needed message:**
```python
{
    "task_id": task_id,
    "trace_id": trace_id,
    "agent_id": self.agent_id,
    "reason": "irreversible_action | budget_threshold | tool_limit | escalation | critical_bug",
    "description": "Human-readable explanation of what input is needed",
    "context": {
        # relevant details for the human to make a decision
    }
}
```

---

*Document version: 1.0*
*Last updated: 2026-03*
*Applies to: All agents and automated tools working on the NEXUS codebase*
*Owner: NEXUS Project — read alongside CLAUDE.md*

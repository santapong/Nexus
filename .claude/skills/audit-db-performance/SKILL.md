---
name: audit-db-performance
description: Run a high-level PostgreSQL performance audit of the NEXUS schema and queries. Use when the user asks for a database review, query optimization, or before scaling to production. Produces a markdown report of missing indexes, N+1 risks, and unbounded queries. Read-only.
---

# Database Performance Audit Skill

Audits NEXUS for the database performance issues that will bite at scale (1k+ tasks/day).

## When to invoke

- Before scaling beyond ~100 active tasks/day
- After any new alembic migration
- After adding new API endpoints that touch high-volume tables (`tasks`, `llm_usage`, `audit_log`, `episodic_memory`)
- When a production query is slow

## Workflow

Run as a single Explore subagent with the prompt template below.

### 1. Index audit

Read every file in `backend/nexus/alembic/versions/`. For each table, list:

- All indexes (composite columns matter — `(a, b)` is **not** the same as `(b, a)`)
- All `WHERE` and `ORDER BY` clauses on that table across `backend/nexus/api/` and `backend/nexus/memory/`
- Whether each query pattern is covered by an index

**Tables that warrant special attention:**

| Table | High-volume query patterns to verify |
|-------|-------------------------------------|
| `tasks` | `WHERE workspace_id = ? AND status = ? ORDER BY created_at DESC` — needs composite `(workspace_id, status, created_at DESC)` |
| `llm_usage` | `GROUP BY model_name WHERE created_at >= ?` — needs `(model_name, created_at DESC)` |
| `episodic_memory` | `ORDER BY embedding <=> ? LIMIT 5` — needs **ivfflat** index, lists ≈ sqrt(rows) |
| `semantic_memory` | `WHERE agent_id = ? AND namespace = ?` — needs composite `(agent_id, namespace)` |
| `audit_log` | `WHERE event_type = ? ORDER BY created_at DESC` — needs `(event_type, created_at DESC)` |
| `billing_records` | `WHERE billing_type = ? ORDER BY created_at DESC` — needs `(billing_type, created_at DESC)` |
| `human_approvals` | `WHERE agent_id = ? AND status = ?` — needs `(agent_id, status)` |

### 2. pgvector

For every table with a `vector(1536)` column:

- ivfflat index exists with `vector_cosine_ops`?
- `lists` parameter sane? Rule of thumb: `lists = sqrt(rows)`; for ≤ 1M rows use 100–1000
- Query uses `<=>` (cosine) — matches the operator class

### 3. N+1 queries

Scan `backend/nexus/api/*.py` for loops over results that call `db.execute(select(...))` per item. Patterns:

```python
# BAD
tasks = await db.execute(select(Task).where(...))
for task in tasks.scalars():
    agent = await db.execute(select(Agent).where(Agent.id == task.agent_id))  # N+1
```

Replace with `selectinload()` or a single JOIN.

### 4. Pagination

Every list endpoint should have:
- `limit: int = Parameter(default=50, le=200)`
- `offset: int = Parameter(default=0, ge=0)`
- Or cursor-based pagination on `created_at`

Endpoints to verify: `analytics.py`, `tasks.py`, `audit.py`, episodic-memory recall, `marketplace.py`.

### 5. Connection pooling

`backend/nexus/db/session.py`. Confirm:
- `pool_size` and `max_overflow` set (not defaults)
- `pool_pre_ping=True`
- `pool_recycle=3600` (or shorter than DB idle timeout)
- One session per request (no manual session creation in route handlers — that bypasses RLS)

### 6. Async correctness

Grep for `db.execute(` without `await`:

```bash
grep -rn 'db.execute(\|session.execute(' backend/nexus/ | grep -v 'await'
```

Every result is a bug (returns a coroutine instead of a result).

### 7. JSONB indexes

For every JSONB column queried via `->` or `->>`:
- Is there a GIN index on the JSONB column, or expression index on the specific path?
- Common offenders: `tasks.output`, `episodic_memory.full_context`, `prompts.notes`

### 8. Growth-bound queries

- `audit_log` — append-only, ~10k rows/day. **Must be partitioned by date OR archived.** Check for `archived_at` column + active archival job.
- `llm_usage` — same volume. Partition or archive.
- `tasks.full_context` if stored — can be huge; consider moving to object storage past N days.

### 9. Workspace filtering

For every multi-tenant table, every query must include `WHERE workspace_id = ?`. Run:

```bash
grep -rn 'select(BillingRecord\|select(AuditLog\|select(Task' backend/nexus/api/ \
  | grep -v 'workspace_id'
```

Any hit is a tenant-isolation bug **and** a performance bug (full-table scan).

### 10. Hot-path queries

These run on every task — must be sub-millisecond:

- Budget check (Redis primary, DB fallback)
- Episodic recall (top-5 cosine similarity)
- Agent config load
- Idempotency check

Confirm each has an index + cache + connection pool path.

## Output format

```
# Database Performance Audit — YYYY-MM-DD

## Critical (will cause production outage at scale)
- **[file:line or TABLE.column] Title** — description + fix

## High
- ...

## Medium
- ...

## Notes
- Indexes that look correct
- Query patterns that look correct
```

## Rules

- Read-only. Generate `alembic revision -m '...'` commands as suggestions, do not run them.
- Include the actual table/column/index name in every finding.
- Cap the report at 1500 words.

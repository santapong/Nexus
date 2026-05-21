"""Hot-path performance indexes (audit findings DB 1-6).

Adds six missing indexes identified by the database performance audit. Each
index is created with ``IF NOT EXISTS`` inside an autocommit block so we can
use ``CREATE INDEX CONCURRENTLY``-equivalent behaviour where supported and
avoid blocking writes on large tables.

Revision ID: 012
Revises: 011
Create Date: 2026-05-21

Indexes:
1. ``ix_episodic_memory_embedding`` — IVFFlat (vector_cosine_ops, lists=100)
   on ``episodic_memory(embedding)``. Hot-path cosine-similarity recall query
   in ``memory/episodic.py`` currently degrades to a sequential scan as the
   table grows. Mirrors the existing pattern used by
   ``ix_workspace_files_embedding`` in migration 011.

2. ``ix_tasks_workspace_status_created`` — composite on
   ``tasks(workspace_id, status, created_at DESC)``. The dashboard task-list
   query filters by workspace + status and orders by recency. Existing
   single-column indexes can only be combined via bitmap-OR which is much
   slower.

3. ``ix_llm_usage_model_created`` — composite on
   ``llm_usage(model_name, created_at DESC)``. Analytics endpoints aggregate
   per-model cost/usage with a date filter; current indexes cover agent +
   created_at but not model.

4. ``ix_semantic_memory_agent_namespace`` — composite on
   ``semantic_memory(agent_id, namespace)``. Every task load runs a
   per-agent + per-namespace fact lookup. Existing single-column
   ``agent_id`` index forces a linear scan across the agent's namespaces.

5. ``ix_audit_log_event_type_created`` — composite on
   ``audit_log(event_type, created_at DESC)``. Filter pattern in
   ``api/audit.py``. F11 will partition this table later; this index still
   helps until then.

6. ``ix_human_approvals_agent_status`` — composite on
   ``human_approvals(agent_id, status)``. Powers per-agent pending-approval
   lookups (e.g. "show me everything blocked on Engineer").
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers
revision: str = "012"
down_revision: str | None = "011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# CREATE INDEX CONCURRENTLY cannot run inside a transaction block. We use
# Alembic's autocommit_block() to switch the migration's connection out of
# transactional mode for the duration of the index creation. Each statement
# uses IF NOT EXISTS so a partial re-run is safe.
_CREATE_STATEMENTS: tuple[str, ...] = (
    # 1) episodic_memory embedding — IVFFlat for cosine similarity recall
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_episodic_memory_embedding "
    "ON episodic_memory USING ivfflat (embedding vector_cosine_ops) "
    "WITH (lists = 100)",
    # 2) tasks(workspace_id, status, created_at DESC) — dashboard list query
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_tasks_workspace_status_created "
    "ON tasks (workspace_id, status, created_at DESC)",
    # 3) llm_usage(model_name, created_at DESC) — analytics aggregation
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_llm_usage_model_created "
    "ON llm_usage (model_name, created_at DESC)",
    # 4) semantic_memory(agent_id, namespace) — per-task fact load
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_semantic_memory_agent_namespace "
    "ON semantic_memory (agent_id, namespace)",
    # 5) audit_log(event_type, created_at DESC) — audit viewer filter
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_audit_log_event_type_created "
    "ON audit_log (event_type, created_at DESC)",
    # 6) human_approvals(agent_id, status) — per-agent pending approvals
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_human_approvals_agent_status "
    "ON human_approvals (agent_id, status)",
)

_DROP_STATEMENTS: tuple[str, ...] = (
    "DROP INDEX CONCURRENTLY IF EXISTS ix_human_approvals_agent_status",
    "DROP INDEX CONCURRENTLY IF EXISTS ix_audit_log_event_type_created",
    "DROP INDEX CONCURRENTLY IF EXISTS ix_semantic_memory_agent_namespace",
    "DROP INDEX CONCURRENTLY IF EXISTS ix_llm_usage_model_created",
    "DROP INDEX CONCURRENTLY IF EXISTS ix_tasks_workspace_status_created",
    "DROP INDEX CONCURRENTLY IF EXISTS ix_episodic_memory_embedding",
)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for stmt in _CREATE_STATEMENTS:
            op.execute(stmt)


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for stmt in _DROP_STATEMENTS:
            op.execute(stmt)

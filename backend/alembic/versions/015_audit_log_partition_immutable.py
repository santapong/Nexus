"""Audit log partitioning + DB-level immutability.

Revision ID: 015
Revises: 011
Create Date: 2026-05-21

⚠️  CONFIRMATION_REQUIRED — DESTRUCTIVE MIGRATION ⚠️

This migration rewrites the `audit_log` table to:

1. Convert it to a PostgreSQL declarative range-partitioned table on
   `created_at` with one partition per calendar month. Initial partitions
   cover 2026-05 through 2026-08; subsequent partitions are created by
   the archival job in `nexus.audit.service`.

2. Install a BEFORE UPDATE/DELETE trigger that enforces row-level
   immutability:

     - DELETE is always forbidden.
     - UPDATE is forbidden once `archived_at` is non-NULL.
     - UPDATE is forbidden when any column other than `archived_at`
       changes.

   In a partitioned table, triggers attached to the parent are not
   automatically inherited by child partitions for row-level events,
   so we attach the trigger to every child partition explicitly. The
   archival job must do the same when it creates new partitions
   (see `_attach_immutability_trigger` in `nexus/audit/service.py`).

What this migration does, in order:

  a. Rename existing `audit_log` to `audit_log_legacy`.
  b. Create new `audit_log` as PARTITION BY RANGE (created_at).
     - The primary key must include `created_at` (Postgres requirement
       for partitioned tables). PK becomes (id, created_at).
  c. Create four initial monthly partitions (current + next 3 months).
  d. Re-create the FK from audit_log.task_id → tasks.id, indexes, and
     RLS policy.
  e. Copy data from `audit_log_legacy` into the new partitioned table
     (rows whose `created_at` falls outside the initial range are
     parked in an `audit_log_overflow` DEFAULT partition; if any rows
     land there a NOTICE is raised — operators must add the missing
     month partitions before dropping it).
  f. Drop `audit_log_legacy`.
  g. Create the `audit_log_prevent_modification()` trigger function and
     attach it to every child partition.

REVIEWER CHECKLIST before running in production:

  [ ] Backup the database. This rewrites a heavy append-only table.
  [ ] Confirm `audit_log` row count and estimated duration (rows/sec on
      target hardware). On a 100M-row table this can take >1h.
  [ ] Take a maintenance window — `audit_log` will be locked for the
      duration of the COPY.
  [ ] Verify that no application code does anything other than INSERT
      or `UPDATE ... SET archived_at = now()` against `audit_log`. The
      trigger will reject anything else (including ORM dirty-row writes
      that touch unrelated columns).
  [ ] Confirm `nexus.audit.service.archive_audit_partitions` is wired
      into the scheduler before the first partition exits the
      90-day hot window.

Rolling back is also destructive (recreates non-partitioned table and
copies data back). Prefer fixing forward.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers
revision: str = "015"
down_revision: str | None = "014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Initial partition window — current month + next 3 months.
# Format: (suffix, range_start, range_end_exclusive)
_INITIAL_PARTITIONS: list[tuple[str, str, str]] = [
    ("2026_05", "2026-05-01", "2026-06-01"),
    ("2026_06", "2026-06-01", "2026-07-01"),
    ("2026_07", "2026-07-01", "2026-08-01"),
    ("2026_08", "2026-08-01", "2026-09-01"),
]


_TRIGGER_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION audit_log_prevent_modification()
RETURNS trigger AS $$
BEGIN
    -- Hard block on DELETE; audit rows are durable evidence.
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'audit_log rows cannot be deleted (table=%, id=%)',
            TG_TABLE_NAME, OLD.id;
    END IF;

    IF TG_OP = 'UPDATE' THEN
        -- Once archived_at is set, the row is sealed.
        IF OLD.archived_at IS NOT NULL THEN
            RAISE EXCEPTION
                'audit_log rows are immutable once archived (table=%, id=%)',
                TG_TABLE_NAME, OLD.id;
        END IF;

        -- The only legal mutation is archived_at: NULL -> timestamptz.
        -- Compare the row with archived_at stripped; if anything else
        -- differs, reject.
        IF (row_to_json(OLD)::jsonb - 'archived_at')
           <> (row_to_json(NEW)::jsonb - 'archived_at') THEN
            RAISE EXCEPTION
                'audit_log columns other than archived_at are immutable '
                '(table=%, id=%)',
                TG_TABLE_NAME, OLD.id;
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def _attach_immutability_trigger(partition_name: str) -> None:
    """Attach the immutability trigger to a single partition."""
    op.execute(
        f"""
        DROP TRIGGER IF EXISTS trg_audit_log_immutable
            ON {partition_name};
        CREATE TRIGGER trg_audit_log_immutable
            BEFORE UPDATE OR DELETE ON {partition_name}
            FOR EACH ROW
            EXECUTE FUNCTION audit_log_prevent_modification();
        """
    )


def upgrade() -> None:
    # ── 1. Capture existing indexes/RLS, then rename legacy table ────────
    op.execute("DROP POLICY IF EXISTS audit_log_workspace_isolation ON audit_log")
    op.execute("ALTER TABLE audit_log DISABLE ROW LEVEL SECURITY")

    # Drop indexes on the legacy table; we'll recreate them on the new one.
    # Use IF EXISTS in case a deployment has skewed index sets.
    for idx in (
        "ix_audit_log_task_id",
        "ix_audit_log_trace_id",
        "ix_audit_log_created_at",
        "ix_audit_log_workspace",
        "ix_audit_log_archived",
        "ix_audit_agent_created",
    ):
        op.execute(f"DROP INDEX IF EXISTS {idx}")

    op.execute("ALTER TABLE audit_log RENAME TO audit_log_legacy")

    # ── 2. Create partitioned audit_log ──────────────────────────────────
    # The PK must include the partition key (created_at).
    op.execute(
        """
        CREATE TABLE audit_log (
            id uuid NOT NULL DEFAULT uuid_generate_v4(),
            task_id uuid NOT NULL,
            trace_id varchar(36) NOT NULL,
            agent_id varchar(100) NOT NULL,
            event_type varchar(100) NOT NULL,
            event_data jsonb NOT NULL,
            sa_orm_sentinel integer,
            workspace_id varchar(36),
            archived_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (id, created_at)
        ) PARTITION BY RANGE (created_at);
        """
    )

    # FK to tasks(id) on a partitioned table is allowed in PG14+ and is
    # enforced per-partition automatically.
    op.execute(
        """
        ALTER TABLE audit_log
            ADD CONSTRAINT audit_log_task_id_fkey
            FOREIGN KEY (task_id) REFERENCES tasks(id);
        """
    )

    # ── 3. Initial partitions ────────────────────────────────────────────
    for suffix, start, end in _INITIAL_PARTITIONS:
        partition_name = f"audit_log_{suffix}"
        op.execute(
            f"""
            CREATE TABLE {partition_name} PARTITION OF audit_log
                FOR VALUES FROM ('{start}') TO ('{end}');
            """
        )

    # DEFAULT partition catches rows outside any explicit range. The
    # archival job is responsible for emptying this by creating the
    # missing month partitions and re-routing rows. Without it, the
    # legacy COPY below would fail for out-of-range rows.
    op.execute(
        """
        CREATE TABLE audit_log_overflow PARTITION OF audit_log DEFAULT;
        """
    )

    # ── 4. Indexes on the partitioned parent (cascade to partitions) ────
    op.execute("CREATE INDEX ix_audit_log_task_id ON audit_log (task_id)")
    op.execute("CREATE INDEX ix_audit_log_trace_id ON audit_log (trace_id)")
    op.execute("CREATE INDEX ix_audit_log_created_at ON audit_log (created_at)")
    op.execute("CREATE INDEX ix_audit_log_workspace ON audit_log (workspace_id)")
    op.execute(
        """
        CREATE INDEX ix_audit_log_archived
            ON audit_log (archived_at)
            WHERE archived_at IS NULL;
        """
    )
    op.execute(
        """
        CREATE INDEX ix_audit_agent_created
            ON audit_log (agent_id, created_at DESC);
        """
    )

    # ── 5. Copy legacy data into the partitioned table ───────────────────
    # We use INSERT ... SELECT so that the partition router places each
    # row in the right child (or in audit_log_overflow). On large tables
    # this is the slow step.
    op.execute(
        """
        INSERT INTO audit_log (
            id, task_id, trace_id, agent_id, event_type, event_data,
            sa_orm_sentinel, workspace_id, archived_at, created_at
        )
        SELECT
            id, task_id, trace_id, agent_id, event_type, event_data,
            sa_orm_sentinel, workspace_id, archived_at, created_at
        FROM audit_log_legacy;
        """
    )

    # Warn if any rows landed in the overflow partition.
    op.execute(
        """
        DO $$
        DECLARE
            overflow_count integer;
        BEGIN
            SELECT COUNT(*) INTO overflow_count FROM audit_log_overflow;
            IF overflow_count > 0 THEN
                RAISE NOTICE
                    'audit_log_overflow contains % rows outside the '
                    'initial monthly partition range. Create the '
                    'missing month partitions and migrate before '
                    'dropping the overflow partition.',
                    overflow_count;
            END IF;
        END $$;
        """
    )

    # ── 6. Drop legacy table ─────────────────────────────────────────────
    op.execute("DROP TABLE audit_log_legacy")

    # ── 7. Re-enable RLS on the partitioned parent ───────────────────────
    op.execute("ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_log FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY audit_log_workspace_isolation ON audit_log
        USING (
            workspace_id::text = current_setting('nexus.workspace_id', true)
            OR current_setting('nexus.workspace_id', true) = 'superuser'
            OR workspace_id IS NULL
        )
        """
    )

    # ── 8. Immutability trigger function ─────────────────────────────────
    op.execute(_TRIGGER_FUNCTION_SQL)

    # Triggers on a partitioned parent do NOT cascade to children for
    # row-level events; we attach them per-partition. The archival job
    # must do the same for any new partitions it creates.
    for suffix, _start, _end in _INITIAL_PARTITIONS:
        _attach_immutability_trigger(f"audit_log_{suffix}")
    _attach_immutability_trigger("audit_log_overflow")


def downgrade() -> None:
    """Reverse the migration — also destructive.

    Rebuilds a plain (non-partitioned) audit_log, copies rows back, and
    drops the partitioned version. Triggers are removed implicitly when
    the partitions are dropped.
    """
    op.execute("DROP POLICY IF EXISTS audit_log_workspace_isolation ON audit_log")
    op.execute("ALTER TABLE audit_log DISABLE ROW LEVEL SECURITY")

    # Stage data out before destroying the partitioned table.
    op.execute(
        """
        CREATE TABLE audit_log_legacy AS
            SELECT * FROM audit_log;
        """
    )

    op.execute("DROP TABLE audit_log CASCADE")
    op.execute("DROP FUNCTION IF EXISTS audit_log_prevent_modification()")

    op.create_table(
        "audit_log",
        sa.Column(
            "id",
            sa.Uuid(),
            nullable=False,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("trace_id", sa.String(36), nullable=False),
        sa.Column("agent_id", sa.String(100), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column(
            "event_data",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
        ),
        sa.Column("sa_orm_sentinel", sa.Integer(), nullable=True),
        sa.Column("workspace_id", sa.String(36), nullable=True),
        sa.Column(
            "archived_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
    )
    op.create_index("ix_audit_log_task_id", "audit_log", ["task_id"])
    op.create_index("ix_audit_log_trace_id", "audit_log", ["trace_id"])
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])
    op.create_index("ix_audit_log_workspace", "audit_log", ["workspace_id"])
    op.create_index(
        "ix_audit_log_archived",
        "audit_log",
        ["archived_at"],
        postgresql_where=sa.text("archived_at IS NULL"),
    )
    op.create_index(
        "ix_audit_agent_created",
        "audit_log",
        ["agent_id", sa.text("created_at DESC")],
    )

    op.execute(
        """
        INSERT INTO audit_log (
            id, task_id, trace_id, agent_id, event_type, event_data,
            sa_orm_sentinel, workspace_id, archived_at, created_at
        )
        SELECT
            id, task_id, trace_id, agent_id, event_type, event_data,
            sa_orm_sentinel, workspace_id, archived_at, created_at
        FROM audit_log_legacy;
        """
    )
    op.execute("DROP TABLE audit_log_legacy")

    op.execute("ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_log FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY audit_log_workspace_isolation ON audit_log
        USING (
            workspace_id::text = current_setting('nexus.workspace_id', true)
            OR current_setting('nexus.workspace_id', true) = 'superuser'
            OR workspace_id IS NULL
        )
        """
    )

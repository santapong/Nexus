"""Audit logging service.

Provides a centralized function and event type enum for writing
structured audit events to the audit_log table. All agent actions,
prompt changes, budget events, and approval flows should go through
this service.

Also exposes the partitioned-audit-log archival job:

  * `ensure_future_audit_partitions` — keeps a rolling window of
    monthly partitions ahead of `now()` so inserts never hit the
    DEFAULT/overflow partition.
  * `archive_audit_partitions` — for partitions whose entire range is
    older than the configured cold-storage threshold (default 90 days):
    dump rows to `settings.audit_cold_storage_path`, DETACH the
    partition (one cycle later: DROP it), and mark the rows
    `archived_at = now()`.

`archive_audit_partitions` is the Taskiq-scheduled entry point. The
scheduling decorator is intentionally TODO'd — wire it from the
scheduler module once the per-deployment cadence is settled
(`scheduler_check_interval_seconds` is hourly by default; this job
only needs to run daily).
"""

from __future__ import annotations

import enum
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import AuditLog
from nexus.settings import settings

logger = structlog.get_logger()


class AuditEventType(enum.StrEnum):
    """Standardized event types for the audit log."""

    TASK_RECEIVED = "task_received"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"
    TOOL_CALL_LIMIT_REACHED = "tool_call_limit_reached"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_RESOLVED = "approval_resolved"
    BUDGET_EXCEEDED = "budget_exceeded"
    PROMPT_ACTIVATED = "prompt_activated"
    PROMPT_ROLLBACK = "prompt_rollback"
    PROMPT_CREATED = "prompt_created"
    HEARTBEAT_SILENCE = "auto_fail_heartbeat_silence"
    AUDIT_PARTITION_CREATED = "audit_partition_created"
    AUDIT_PARTITION_DETACHED = "audit_partition_detached"
    AUDIT_PARTITION_DROPPED = "audit_partition_dropped"
    AUDIT_PARTITION_ARCHIVED = "audit_partition_archived"


async def log_event(
    *,
    session: AsyncSession,
    task_id: str,
    trace_id: str,
    agent_id: str,
    event_type: AuditEventType | str,
    event_data: dict[str, Any],
) -> None:
    """Write an audit event to the audit_log table.

    Args:
        session: Active database session (caller manages commit).
        task_id: Task UUID string.
        trace_id: Trace UUID string for request correlation.
        agent_id: Agent identifier (UUID string or role-based ID).
        event_type: Standardized event type from AuditEventType.
        event_data: Structured event payload (stored as JSONB).
    """
    event_type_str = event_type.value if isinstance(event_type, AuditEventType) else event_type

    entry = AuditLog(
        task_id=task_id,
        trace_id=trace_id,
        agent_id=agent_id,
        event_type=event_type_str,
        event_data=event_data,
    )
    session.add(entry)

    logger.info(
        "audit_event",
        event_type=event_type_str,
        task_id=task_id,
        agent_id=agent_id,
    )


# ── Partition management helpers ─────────────────────────────────────────


_TRIGGER_ATTACH_SQL = """
DROP TRIGGER IF EXISTS trg_audit_log_immutable ON {partition};
CREATE TRIGGER trg_audit_log_immutable
    BEFORE UPDATE OR DELETE ON {partition}
    FOR EACH ROW
    EXECUTE FUNCTION audit_log_prevent_modification();
"""


def _month_floor(d: date) -> date:
    """Return the first day of the month containing d."""
    return d.replace(day=1)


def _next_month(d: date) -> date:
    """Return the first day of the month after d (d must be a month start)."""
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def _partition_suffix(start: date) -> str:
    """Format the partition table suffix for a month start (YYYY_MM)."""
    return f"{start.year:04d}_{start.month:02d}"


async def ensure_future_audit_partitions(
    db_session: AsyncSession,
    *,
    months_ahead: int = 3,
    now: datetime | None = None,
) -> list[str]:
    """Create monthly audit_log partitions covering current + N future months.

    Idempotent: uses `CREATE TABLE IF NOT EXISTS` semantics via a
    PL/pgSQL check. Also attaches the immutability trigger to any newly
    created partitions.

    Args:
        db_session: Async database session (caller commits).
        months_ahead: How many months past the current month to keep
            partitions ready for. Defaults to 3.
        now: Override for "current time" (used in tests).

    Returns:
        List of partition table names that were created (empty if all
        were already present).
    """
    current = (now or datetime.now(UTC)).date()
    start = _month_floor(current)

    created: list[str] = []
    for _ in range(months_ahead + 1):
        end = _next_month(start)
        partition = f"audit_log_{_partition_suffix(start)}"

        # Probe pg_class for the partition. If absent, create + attach trigger.
        result = await db_session.execute(
            text("SELECT to_regclass(:name) IS NOT NULL AS exists"),
            {"name": partition},
        )
        exists = bool(result.scalar())
        if not exists:
            await db_session.execute(
                text(
                    f"CREATE TABLE {partition} PARTITION OF audit_log "
                    f"FOR VALUES FROM ('{start.isoformat()}') "
                    f"TO ('{end.isoformat()}')"
                )
            )
            await db_session.execute(text(_TRIGGER_ATTACH_SQL.format(partition=partition)))
            created.append(partition)
            logger.info(
                "audit_partition_created",
                partition=partition,
                range_start=start.isoformat(),
                range_end=end.isoformat(),
            )

        start = end

    if created:
        await db_session.commit()
    return created


async def _list_cold_partitions(
    db_session: AsyncSession,
    cutoff: date,
) -> list[tuple[str, date, date]]:
    """List audit_log_YYYY_MM partitions whose range_end <= cutoff.

    Returns a list of (partition_name, range_start, range_end) tuples.
    Detached partitions are skipped (they no longer appear under the
    parent in pg_inherits).
    """
    result = await db_session.execute(
        text(
            """
            SELECT
                c.relname AS partition_name,
                pg_get_expr(c.relpartbound, c.oid) AS bound_expr
            FROM pg_class c
            JOIN pg_inherits i ON i.inhrelid = c.oid
            JOIN pg_class p ON p.oid = i.inhparent
            WHERE p.relname = 'audit_log'
              AND c.relname LIKE 'audit_log_____\\_____'
            ORDER BY c.relname
            """
        )
    )
    out: list[tuple[str, date, date]] = []
    for row in result.all():
        name: str = row.partition_name
        bound: str = row.bound_expr or ""
        # bound looks like: FOR VALUES FROM ('2026-05-01') TO ('2026-06-01')
        try:
            from_idx = bound.index("FROM ('") + len("FROM ('")
            to_idx = bound.index("') TO ('")
            end_idx = bound.index("')", to_idx + len("') TO ('"))
            range_start = date.fromisoformat(bound[from_idx:to_idx])
            range_end = date.fromisoformat(bound[to_idx + len("') TO ('") : end_idx])
        except (ValueError, IndexError):
            # Skip partitions we can't parse (e.g. DEFAULT).
            continue
        if range_end <= cutoff:
            out.append((name, range_start, range_end))
    return out


async def _dump_partition_to_cold_storage(
    db_session: AsyncSession,
    partition: str,
    cold_path: Path,
) -> Path:
    """Dump a partition's rows as newline-delimited JSON to cold storage.

    Returns the path of the dump file. Raises on failure so the caller
    does not proceed to DETACH.
    """
    cold_path.mkdir(parents=True, exist_ok=True)
    out_file = cold_path / f"{partition}.jsonl"

    # Stream rows out via SQLAlchemy; for a multi-million-row table this
    # should be done via `COPY ... TO PROGRAM` server-side instead, but
    # that requires superuser. The portable path: paginated SELECT.
    page_size = 5000
    offset = 0
    total = 0

    # Tmp file then atomic rename so a crash mid-dump can't leave a
    # truncated cold-storage file that looks complete.
    tmp_file = out_file.with_suffix(".jsonl.tmp")
    with tmp_file.open("w", encoding="utf-8") as fh:
        while True:
            result = await db_session.execute(
                text(
                    f"SELECT id, task_id, trace_id, agent_id, event_type, "
                    f"event_data, workspace_id, archived_at, created_at "
                    f"FROM {partition} "
                    f"ORDER BY created_at, id "
                    f"LIMIT :limit OFFSET :offset"
                ),
                {"limit": page_size, "offset": offset},
            )
            rows = result.mappings().all()
            if not rows:
                break
            for row in rows:
                # Convert non-JSON types to strings.
                record = {
                    "id": str(row["id"]),
                    "task_id": str(row["task_id"]),
                    "trace_id": row["trace_id"],
                    "agent_id": row["agent_id"],
                    "event_type": row["event_type"],
                    "event_data": row["event_data"],
                    "workspace_id": row["workspace_id"],
                    "archived_at": (row["archived_at"].isoformat() if row["archived_at"] else None),
                    "created_at": row["created_at"].isoformat(),
                }
                fh.write(json.dumps(record, default=str))
                fh.write("\n")
            total += len(rows)
            if len(rows) < page_size:
                break
            offset += page_size

    tmp_file.replace(out_file)
    logger.info(
        "audit_partition_dumped",
        partition=partition,
        rows=total,
        path=str(out_file),
    )
    return out_file


async def archive_audit_partitions(
    db_session: AsyncSession,
    *,
    cold_age_days: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Two-phase archival of cold audit_log partitions.

    Cycle semantics:

      Cycle N: For each partition whose entire range is older than
        `cold_age_days`:
          1. Dump rows to `settings.audit_cold_storage_path` as JSONL.
          2. DETACH the partition (no DROP yet — gives operators one
             cycle to verify the dump).
          3. UPDATE the detached partition's rows to set
             `archived_at = now()` (note: the partition is detached so
             no parent trigger fires; we attach the trigger explicitly
             to detached partitions so UPDATEs other than archived_at
             still fail).
      Cycle N+1: For each detached partition whose dump file exists,
        DROP it.

    A partition's "lifecycle phase" is encoded in pg_inherits: if it is
    still attached, it is a candidate for detach. If it is detached and
    the dump file is present, it is a candidate for drop.

    Args:
        db_session: Async DB session (caller commits).
        cold_age_days: Override threshold (default 90 days).
        now: Override "now" for tests.

    Returns:
        Dict with `detached`, `dropped`, and `skipped` partition lists.
    """
    days = cold_age_days if cold_age_days is not None else 90
    now_dt = now or datetime.now(UTC)
    cutoff = (now_dt - timedelta(days=days)).date()
    # Use getattr so that the setting can be added to nexus.settings later
    # without forcing this module to gate on it. Default per spec:
    # /var/lib/nexus/audit_cold/.
    cold_path = Path(getattr(settings, "audit_cold_storage_path", "/var/lib/nexus/audit_cold/"))

    detached: list[str] = []
    dropped: list[str] = []
    skipped: list[str] = []

    # ── Phase A: detach + dump partitions that are still attached ───────
    candidates = await _list_cold_partitions(db_session, cutoff)
    for partition, range_start, range_end in candidates:
        try:
            await _dump_partition_to_cold_storage(db_session, partition, cold_path)
        except Exception as exc:
            # Dump failed — leave the partition attached so the next
            # cycle retries. Do not DETACH; data must remain queryable.
            logger.error(
                "audit_partition_dump_failed",
                partition=partition,
                error=str(exc),
            )
            skipped.append(partition)
            continue

        await db_session.execute(text(f"ALTER TABLE audit_log DETACH PARTITION {partition}"))
        # The trigger function is shared; re-attach to the detached
        # partition so even direct UPDATEs are still blocked.
        await db_session.execute(text(_TRIGGER_ATTACH_SQL.format(partition=partition)))
        # Stamp archived_at on the detached rows so the
        # archived/active counters in get_archive_stats reflect reality.
        await db_session.execute(
            text(f"UPDATE {partition} SET archived_at = :now WHERE archived_at IS NULL"),
            {"now": now_dt},
        )
        detached.append(partition)
        logger.info(
            "audit_partition_detached",
            partition=partition,
            range_start=range_start.isoformat(),
            range_end=range_end.isoformat(),
        )

    # ── Phase B: drop partitions detached on a previous cycle ───────────
    # A detached partition is one that still exists as a regular table
    # named audit_log_YYYY_MM but is no longer in pg_inherits.
    result = await db_session.execute(
        text(
            r"""
            SELECT c.relname
            FROM pg_class c
            WHERE c.relkind = 'r'
              AND c.relname ~ '^audit_log_[0-9]{4}_[0-9]{2}$'
              AND NOT EXISTS (
                  SELECT 1 FROM pg_inherits i WHERE i.inhrelid = c.oid
              )
            """
        )
    )
    detached_orphans = [row.relname for row in result.all()]
    for partition in detached_orphans:
        # Only drop partitions detached on a *previous* cycle, never
        # ones we just detached this run.
        if partition in detached:
            continue
        dump_file = cold_path / f"{partition}.jsonl"
        if not dump_file.exists():
            logger.warning(
                "audit_partition_drop_skipped_no_dump",
                partition=partition,
                expected_dump=str(dump_file),
            )
            skipped.append(partition)
            continue
        await db_session.execute(text(f"DROP TABLE {partition}"))
        dropped.append(partition)
        logger.info(
            "audit_partition_dropped",
            partition=partition,
            dump_file=str(dump_file),
        )

    await db_session.commit()

    return {
        "detached": detached,
        "dropped": dropped,
        "skipped": skipped,
        "cutoff": cutoff.isoformat(),
    }


# TODO(scheduler): wire archive_audit_partitions into the Taskiq
# scheduler. Should run once per day (cron "0 3 * * *" works) — anything
# faster wastes I/O, anything slower lets the overflow partition fill.
# The scheduler module owns the broker; this file should not import it
# directly to avoid pulling the Kafka broker into ad-hoc imports of
# audit.service. Suggested wiring:
#
#     from nexus.audit.service import archive_audit_partitions
#     from nexus.taskiq_app import broker
#
#     @broker.task(schedule=[{"cron": "0 3 * * *"}])
#     async def scheduled_audit_archival() -> None:
#         async with get_session() as session:
#             await archive_audit_partitions(session)

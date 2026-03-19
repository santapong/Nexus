"""Audit log retention — archive old records.

Archives audit_log records older than the configured retention period
(default: 30 days) by setting the `archived_at` timestamp. Archived
records are excluded from default API queries but remain in the database
for compliance.

Usage:
    Run as a periodic Taskiq task or manually via CLI:
    python -m nexus.audit.retention
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.settings import settings

logger = structlog.get_logger()


async def archive_old_audit_records(
    db_session: AsyncSession,
    retention_days: int | None = None,
    batch_size: int = 1000,
) -> int:
    """Archive audit records older than the retention period.

    Sets `archived_at` on records where `created_at` is older than
    `retention_days` and `archived_at` is still NULL.

    Args:
        db_session: Async database session.
        retention_days: Days to retain. Defaults to settings.audit_retention_days.
        batch_size: Max records to archive per batch (prevents long locks).

    Returns:
        Total number of records archived.
    """
    days = retention_days or settings.audit_retention_days
    cutoff = datetime.now(UTC) - timedelta(days=days)
    now = datetime.now(UTC)
    total_archived = 0

    while True:
        # Archive in batches to avoid long-running transactions
        result = await db_session.execute(
            text("""
                UPDATE audit_log
                SET archived_at = :now
                WHERE id IN (
                    SELECT id FROM audit_log
                    WHERE created_at < :cutoff
                    AND archived_at IS NULL
                    LIMIT :batch_size
                    FOR UPDATE SKIP LOCKED
                )
            """),
            {"now": now, "cutoff": cutoff, "batch_size": batch_size},
        )
        batch_count = result.rowcount
        await db_session.commit()

        total_archived += batch_count

        if batch_count < batch_size:
            break

    if total_archived > 0:
        logger.info(
            "audit_records_archived",
            total_archived=total_archived,
            retention_days=days,
            cutoff=cutoff.isoformat(),
        )
    else:
        logger.debug("audit_retention_no_records_to_archive", retention_days=days)

    return total_archived


async def get_archive_stats(db_session: AsyncSession) -> dict:
    """Get audit log archive statistics.

    Args:
        db_session: Async database session.

    Returns:
        Dict with total, active, and archived record counts.
    """
    result = await db_session.execute(
        text("""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE archived_at IS NULL) AS active,
                COUNT(*) FILTER (WHERE archived_at IS NOT NULL) AS archived
            FROM audit_log
        """)
    )
    row = result.one()
    return {
        "total": row.total,
        "active": row.active,
        "archived": row.archived,
    }

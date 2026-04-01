"""SLA compliance evaluator — rolling 30-day compliance calculation.

Reads SLA snapshots from the database and calculates whether a workspace
is meeting its SLA tier guarantees. Used by the API and alerting system.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.core.sla.definitions import SLATier, SLAThresholds, get_thresholds
from nexus.db.models import SLASnapshot

logger = structlog.get_logger()


@dataclass
class SLAComplianceReport:
    """SLA compliance report for a workspace over a time period."""

    workspace_id: UUID | None
    tier: SLATier
    thresholds: SLAThresholds
    period_days: int
    # Measured values
    measured_uptime_pct: float
    measured_avg_wait_seconds: float
    measured_error_rate_pct: float
    snapshot_count: int
    # Compliance flags
    uptime_compliant: bool
    wait_time_compliant: bool
    error_rate_compliant: bool

    @property
    def overall_compliant(self) -> bool:
        """Whether all SLA metrics are within thresholds."""
        if not self.thresholds.has_guarantees:
            return True  # Free tier always "compliant"
        return self.uptime_compliant and self.wait_time_compliant and self.error_rate_compliant

    @property
    def compliance_pct(self) -> float:
        """Overall compliance percentage (0-100)."""
        if not self.thresholds.has_guarantees:
            return 100.0
        checks = [self.uptime_compliant, self.wait_time_compliant, self.error_rate_compliant]
        return round(sum(checks) / len(checks) * 100.0, 1)


async def evaluate_compliance(
    session: AsyncSession,
    workspace_id: UUID | None = None,
    tier: SLATier = SLATier.FREE,
    period_days: int = 30,
) -> SLAComplianceReport:
    """Evaluate SLA compliance for a workspace over the given period.

    Aggregates SLA snapshots and compares against tier thresholds.

    Args:
        session: Database session.
        workspace_id: Workspace to evaluate. None = platform-wide.
        tier: The SLA tier to evaluate against.
        period_days: How many days to look back (default: 30).

    Returns:
        SLAComplianceReport with measured values and compliance flags.
    """
    thresholds = get_thresholds(tier)
    cutoff = datetime.now(timezone.utc) - timedelta(days=period_days)

    # Build filter
    base_filter = SLASnapshot.timestamp >= cutoff
    if workspace_id is not None:
        base_filter = base_filter & (SLASnapshot.workspace_id == workspace_id)
    else:
        base_filter = base_filter & (SLASnapshot.workspace_id.is_(None))

    # Aggregate snapshots
    result = await session.execute(
        select(
            func.count(SLASnapshot.id),
            func.avg(SLASnapshot.uptime_pct),
            func.avg(SLASnapshot.avg_wait_seconds),
            func.avg(SLASnapshot.error_rate),
        ).where(base_filter)
    )
    row = result.one()
    snapshot_count = row[0] or 0
    measured_uptime = float(row[1]) if row[1] is not None else 100.0
    measured_wait = float(row[2]) if row[2] is not None else 0.0
    measured_error = float(row[3]) if row[3] is not None else 0.0

    # Evaluate compliance
    uptime_ok = measured_uptime >= thresholds.uptime_pct if thresholds.has_guarantees else True
    wait_ok = (
        measured_wait <= thresholds.max_queue_wait_seconds
        if thresholds.has_guarantees and thresholds.max_queue_wait_seconds > 0
        else True
    )
    error_ok = measured_error <= thresholds.max_error_rate_pct if thresholds.has_guarantees else True

    report = SLAComplianceReport(
        workspace_id=workspace_id,
        tier=tier,
        thresholds=thresholds,
        period_days=period_days,
        measured_uptime_pct=round(measured_uptime, 2),
        measured_avg_wait_seconds=round(measured_wait, 2),
        measured_error_rate_pct=round(measured_error, 2),
        snapshot_count=snapshot_count,
        uptime_compliant=uptime_ok,
        wait_time_compliant=wait_ok,
        error_rate_compliant=error_ok,
    )

    logger.info(
        "sla_compliance_evaluated",
        workspace_id=str(workspace_id) if workspace_id else "platform",
        tier=tier.value,
        overall_compliant=report.overall_compliant,
        compliance_pct=report.compliance_pct,
        measured_uptime=report.measured_uptime_pct,
        measured_wait=report.measured_avg_wait_seconds,
        measured_error=report.measured_error_rate_pct,
    )

    return report

"""SLA monitoring API endpoints.

Provides uptime compliance status and historical SLA metrics
for workspaces. Used by the dashboard and external monitoring.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from litestar import Controller, get

from nexus.core.sla.definitions import SLA_TIERS, SLATier
from nexus.core.sla.evaluator import evaluate_compliance
from nexus.db.session import sqlalchemy_config

logger = structlog.get_logger()


class SLAController(Controller):
    path = "/api/sla"

    @get("/tiers")
    async def get_sla_tiers(self) -> dict[str, Any]:
        """Return all SLA tier definitions with their thresholds.

        Returns:
            Dictionary of tier names to their SLA guarantees.
        """
        return {
            tier.value: {
                "uptime_pct": thresholds.uptime_pct,
                "max_queue_wait_seconds": thresholds.max_queue_wait_seconds,
                "max_task_duration_seconds": thresholds.max_task_duration_seconds,
                "max_error_rate_pct": thresholds.max_error_rate_pct,
                "has_guarantees": thresholds.has_guarantees,
            }
            for tier, thresholds in SLA_TIERS.items()
        }

    @get("/status")
    async def get_sla_status(
        self,
        workspace_id: UUID | None = None,
        tier: str = "free",
        period_days: int = 30,
    ) -> dict[str, Any]:
        """Get current SLA compliance status for a workspace.

        Args:
            workspace_id: Workspace to check. None = platform-wide.
            tier: SLA tier to evaluate against (free/starter/pro/enterprise).
            period_days: Rolling window in days (default: 30).

        Returns:
            SLA compliance report with measured values and compliance flags.
        """
        try:
            sla_tier = SLATier(tier)
        except ValueError:
            return {"error": f"Invalid tier: {tier}. Must be one of: free, starter, pro, enterprise"}

        async with sqlalchemy_config.get_session() as session:
            report = await evaluate_compliance(
                session=session,
                workspace_id=workspace_id,
                tier=sla_tier,
                period_days=period_days,
            )

        return {
            "workspace_id": str(report.workspace_id) if report.workspace_id else None,
            "tier": report.tier.value,
            "period_days": report.period_days,
            "snapshot_count": report.snapshot_count,
            "overall_compliant": report.overall_compliant,
            "compliance_pct": report.compliance_pct,
            "metrics": {
                "uptime_pct": report.measured_uptime_pct,
                "avg_wait_seconds": report.measured_avg_wait_seconds,
                "error_rate_pct": report.measured_error_rate_pct,
            },
            "thresholds": {
                "uptime_pct": report.thresholds.uptime_pct,
                "max_queue_wait_seconds": report.thresholds.max_queue_wait_seconds,
                "max_error_rate_pct": report.thresholds.max_error_rate_pct,
            },
            "compliance_details": {
                "uptime": report.uptime_compliant,
                "wait_time": report.wait_time_compliant,
                "error_rate": report.error_rate_compliant,
            },
        }

    @get("/history")
    async def get_sla_history(
        self,
        workspace_id: UUID | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Get historical SLA snapshots for trend visualization.

        Args:
            workspace_id: Workspace to query. None = platform-wide.
            limit: Maximum number of snapshots to return (default: 100).

        Returns:
            List of SLA snapshots ordered by timestamp descending.
        """
        from sqlalchemy import select

        from nexus.db.models import SLASnapshot

        async with sqlalchemy_config.get_session() as session:
            query = select(SLASnapshot).order_by(SLASnapshot.timestamp.desc()).limit(min(limit, 500))

            if workspace_id is not None:
                query = query.where(SLASnapshot.workspace_id == workspace_id)
            else:
                query = query.where(SLASnapshot.workspace_id.is_(None))

            result = await session.execute(query)
            snapshots = result.scalars().all()

        return {
            "workspace_id": str(workspace_id) if workspace_id else None,
            "count": len(snapshots),
            "snapshots": [
                {
                    "timestamp": s.timestamp.isoformat(),
                    "tasks_queued": s.tasks_queued,
                    "tasks_completed": s.tasks_completed,
                    "avg_wait_seconds": s.avg_wait_seconds,
                    "error_rate": s.error_rate,
                    "agents_available": s.agents_available,
                    "uptime_pct": s.uptime_pct,
                }
                for s in snapshots
            ],
        }

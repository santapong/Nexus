"""SLA tier definitions for NEXUS workspaces.

Each pricing tier has defined uptime and performance guarantees.
These definitions are used by the evaluator to calculate compliance.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SLATier(str, Enum):
    """Workspace SLA tiers — maps to pricing plans."""

    FREE = "free"
    STARTER = "starter"
    PRO = "pro"
    ENTERPRISE = "enterprise"


@dataclass(frozen=True)
class SLAThresholds:
    """SLA thresholds for a specific tier."""

    tier: SLATier
    uptime_pct: float  # Minimum uptime percentage (e.g. 99.0)
    max_queue_wait_seconds: int  # Max acceptable task queue wait time
    max_task_duration_seconds: int  # Max acceptable task execution time
    max_error_rate_pct: float  # Max acceptable error rate

    @property
    def has_guarantees(self) -> bool:
        """Whether this tier has enforceable SLA guarantees."""
        return self.tier != SLATier.FREE


# ─── Tier definitions ─────────────────────────────────────────────────────────

SLA_TIERS: dict[SLATier, SLAThresholds] = {
    SLATier.FREE: SLAThresholds(
        tier=SLATier.FREE,
        uptime_pct=0.0,  # Best effort — no guarantee
        max_queue_wait_seconds=0,  # No guarantee
        max_task_duration_seconds=1800,  # 30 min hard cap
        max_error_rate_pct=100.0,  # No guarantee
    ),
    SLATier.STARTER: SLAThresholds(
        tier=SLATier.STARTER,
        uptime_pct=99.0,
        max_queue_wait_seconds=300,  # 5 minutes
        max_task_duration_seconds=900,  # 15 minutes
        max_error_rate_pct=10.0,
    ),
    SLATier.PRO: SLAThresholds(
        tier=SLATier.PRO,
        uptime_pct=99.5,
        max_queue_wait_seconds=120,  # 2 minutes
        max_task_duration_seconds=600,  # 10 minutes
        max_error_rate_pct=5.0,
    ),
    SLATier.ENTERPRISE: SLAThresholds(
        tier=SLATier.ENTERPRISE,
        uptime_pct=99.9,
        max_queue_wait_seconds=30,  # 30 seconds
        max_task_duration_seconds=0,  # Custom per contract
        max_error_rate_pct=1.0,
    ),
}


def get_thresholds(tier: SLATier) -> SLAThresholds:
    """Get SLA thresholds for a given tier.

    Args:
        tier: The SLA tier to look up.

    Returns:
        SLAThresholds for the requested tier.
    """
    return SLA_TIERS[tier]

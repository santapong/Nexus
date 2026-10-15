"""Process-local actor proof observations; no owner, execution or READ authority DTO."""

from dataclasses import dataclass
from datetime import datetime

from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.plan_support import CurrentPlanBinding
from nexus.company.strategy.contracts import StrategyCandidateScope
from nexus.company.strategy.current_proof_contracts import StrategyCurrentProof


@dataclass(frozen=True)
class SelectedStrategyProof:
    """Exact selected native actor binding plus both retained concrete Strategy read windows."""

    binding: CurrentPlanBinding
    proof: StrategyCurrentProof
    candidate: StrategyCandidateScope
    profile_observed_at: datetime

    def require_time(self, now: datetime) -> None:
        """Retain the first actual profile observation and every original/current deadline."""
        require_acceptance(
            isinstance(self.profile_observed_at, datetime)
            and self.profile_observed_at.utcoffset() is not None
            and self.profile_observed_at <= self.proof.observed_at <= now
        )
        self.proof.require_time(now)

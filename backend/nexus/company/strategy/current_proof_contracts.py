"""Process-local current proof observations; no execute permit or owner decision DTO."""

from dataclasses import dataclass
from datetime import datetime

from nexus.company.management.acceptance import WorkAcceptance
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.strategy.contracts import (
    StrategyBrief,
    StrategyCheckResult,
    StrategySelectionRef,
)
from nexus.company.strategy.publication_contracts import StrategyLoadedPublication
from nexus.company.strategy.publication_protection import StrategyReadProtection
from nexus.company.strategy.verifier_facts import StrategyVerifierReceipt


@dataclass(frozen=True)
class StrategyCurrentProof:
    """Native observations plus both retained read windows, to close at the caller's final clock."""

    selection: StrategySelectionRef
    original: StrategyLoadedPublication
    acceptance: WorkAcceptance
    brief: StrategyBrief
    verifier: StrategyVerifierReceipt
    check_result: StrategyCheckResult
    author_original_fence: int
    author_current_fence: int
    verifier_current_fence: int
    initial: StrategyReadProtection
    current: StrategyReadProtection
    observed_at: datetime

    def require_time(self, now: datetime) -> None:
        """Keep every initial/current source, grant, profile and genuine credential deadline."""
        require_acceptance(self.acceptance.recorded_at <= self.observed_at <= now)
        self.initial.require_time(now)
        self.current.require_time(now)

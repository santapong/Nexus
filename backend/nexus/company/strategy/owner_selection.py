"""Exact candidate comparison; no actual owner decision or execution permit."""

import hashlib

from nexus.company.management.acceptance import WorkAcceptance
from nexus.company.management.canonical import canonical_sha256
from nexus.company.strategy.contracts import (
    STRATEGY_CHECK_CRITERIA,
    STRATEGY_CHECK_RECIPE,
    STRATEGY_LIMITATIONS,
    StrategyBrief,
    StrategySelectionRef,
)


def describe_strategy_selection(
    brief: StrategyBrief, acceptance: WorkAcceptance, candidate_id: str
) -> StrategySelectionRef:
    """Resolve a finite description; native current proof and signed choice remain required."""
    brief = StrategyBrief.model_validate(brief.model_dump(warnings=False))
    acceptance = WorkAcceptance.model_validate(acceptance.model_dump(warnings=False))
    target = acceptance.target
    raw = brief.model_dump_json().encode()
    if (
        acceptance.verdict != "pass"
        or target.company_id != brief.scope.company_id
        or target.author != brief.scope.author
        or target.verifier != brief.scope.verifier
        or target.work_snapshot_sha256 != brief.scope.author_registration_sha256
        or len(target.artifacts) != 1
        or target.check_recipe != STRATEGY_CHECK_RECIPE
        or target.criterion_ids != STRATEGY_CHECK_CRITERIA
        or acceptance.limitations != STRATEGY_LIMITATIONS
        or target.artifacts[0].sha256 != hashlib.sha256(raw).hexdigest()
        or target.artifacts[0].byte_length != len(raw)
    ):
        raise ValueError(
            "Selection description requires the exact accepted original strategy target"
        )
    candidates = tuple(row for row in brief.candidates if row.scope.candidate_id == candidate_id)
    if len(candidates) != 1:
        raise ValueError("Strategy owner choice must select one exact reviewed candidate")
    return StrategySelectionRef(
        company_id=brief.scope.company_id,
        brief=target.artifacts[0],
        acceptance_id=acceptance.acceptance_id,
        candidate_id=candidate_id,
        candidate_scope_sha256=canonical_sha256(candidates[0].scope),
    )

"""Saved native-shaped proof rows for read-only tests; no real SQL or authority proof."""

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.management.acceptance import WorkAcceptance
from nexus.company.management.acceptance_models import (
    ManagementAcceptanceProof,
    ManagementWorkAcceptance,
)
from nexus.company.management.canonical import canonical_sha256
from nexus.company.strategy.acceptance import build_strategy_acceptance
from nexus.company.strategy.contracts import StrategyBrief, StrategySelectionRef
from nexus.company.strategy.owner_selection import describe_strategy_selection
from nexus.tests.unit.strategy_brief_fixture import strategy_case
from nexus.tests.unit.strategy_verifier_receipt_fixture import receipt_case
from nexus.tests.unit.test_strategy_acceptance_description import _actual_description
from nexus.tests.unit.test_strategy_check_output import inputs


@dataclass
class SelectedCase:
    session: MagicMock
    record: WorkAcceptance
    selection: StrategySelectionRef
    row: ManagementWorkAcceptance
    proofs: list[ManagementAcceptanceProof]


def saved_rows(
    record: WorkAcceptance,
) -> tuple[ManagementWorkAcceptance, list[ManagementAcceptanceProof]]:
    target = record.target
    row = ManagementWorkAcceptance(
        company_id=record.company_id,
        acceptance_id=record.acceptance_id,
        author_task_id=target.author.task_id,
        author_run_id=target.author.run_id,
        author_id=target.author.actor_id,
        verifier_task_id=target.verifier.task_id,
        verifier_run_id=target.verifier.run_id,
        verifier_id=target.verifier.actor_id,
        action_id=target.action_id,
        receipt_id=target.receipt_id,
        receipt_sha256=target.receipt_sha256,
        work_sha256=target.work_snapshot_sha256,
        target_sha256=canonical_sha256(target),
        verdict=record.verdict,
        target_json=target.model_dump_json(),
        result_json=record.model_dump_json(),
        recorded_at=record.recorded_at,
    )
    proofs = [
        ManagementAcceptanceProof(
            company_id=record.company_id,
            acceptance_id=record.acceptance_id,
            proof_id=p.proof_id,
            artifact_revision_id=p.result_artifact.artifact_revision_id,
            artifact_sha256=p.result_artifact.sha256,
            check_recipe=p.recipe,
            target_sha256=p.target_sha256,
            proof_json=p.model_dump_json(),
        )
        for p in record.proofs
    ]
    return row, proofs


def selected_case(monkeypatch: pytest.MonkeyPatch) -> SelectedCase:
    case = receipt_case(monkeypatch)
    facts, raw = _actual_description(case)
    command = strategy_case().command
    record = build_strategy_acceptance(command, inputs(), facts, raw, case.clock["now"])
    assert command.output_utf8 is not None
    brief = StrategyBrief.model_validate_json(command.output_utf8)
    selection = describe_strategy_selection(brief, record, brief.candidates[0].scope.candidate_id)
    row, proofs = saved_rows(record)
    session = MagicMock(spec=AsyncSession)
    session.in_transaction.return_value = True
    session.get = AsyncMock(return_value=row)
    session.scalar = AsyncMock(return_value=None)
    result = MagicMock()
    result.all.side_effect = lambda: proofs
    session.scalars = AsyncMock(return_value=result)
    return SelectedCase(session, record, selection, row, proofs)

"""Closed author effect state regression from actual-shaped issued native rows."""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.company.contracts.actions import ApprovalDecision
from nexus.company.strategy import input_reader as module
from nexus.company.strategy.publication_state import require_fresh_strategy_publication_state
from nexus.harness.journal_models import JournalAction
from nexus.tests.unit.strategy_publication_flow_fixture import author_lease
from nexus.tests.unit.strategy_publication_reader_fixture import reader_case


@pytest.mark.parametrize("state", ["outcome_unknown", "failed"])
async def test_present_rows_do_not_authorize_unknown_or_failed_original_action(
    monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    # This >50-line probe preserves old native facts and spies on the exact state gate.
    case = reader_case(monkeypatch)
    lease, work = author_lease(case.source.original, case.source.clock["now"])
    module_pair = module.resolve_strategy_pair_locked  # type: ignore[attr-defined]
    assert isinstance(module_pair, AsyncMock)
    module_pair.return_value.author = work
    monkeypatch.setattr(module, "execution_row", AsyncMock(return_value=work))
    monkeypatch.setattr(
        module,
        "require_generated_actor",
        AsyncMock(return_value=(case.action, lease.expires_at, MagicMock())),
    )
    case.source.session.scalar = AsyncMock(
        side_effect=lambda statement: (
            False if "pg_roles" in str(statement) else case.prepared.brief.artifact_revision_id
        )
    )
    row = case.rows[(JournalAction, case.prepared.action_id)]
    assert isinstance(row, JournalAction)
    now = case.source.clock["now"]
    row.approval_json = ApprovalDecision(
        company_id=case.action.company_id,
        decision_id=case.action.action_id,
        action_id=case.action.action_id,
        action_revision=1,
        action_hash=row.proposal_hash,
        approver_id=case.source.control.owner_id,
        decision="approved",
        issued_at=now - timedelta(seconds=30),
        expires_at=now + timedelta(seconds=30),
    ).model_dump_json()
    state_gate = MagicMock(wraps=require_fresh_strategy_publication_state)
    monkeypatch.setattr(module, "require_fresh_strategy_publication_state", state_gate)
    case.effect.state = state
    if case.effect.receipt_json is not None:
        from nexus.company.contracts.results import ActionReceipt

        receipt = ActionReceipt.model_validate_json(case.effect.receipt_json)
        case.effect.receipt_json = receipt.model_copy(update={"outcome": state}).model_dump_json()
    with pytest.raises(ValueError):
        await case.reader.revalidate_author_locked(
            case.source.session,
            case.source.control,
            lease,
            case.source.credential.identity,
            case.prepared.action_id,
            case.prepared,
            credential=case.source.credential,
        )
    state_gate.assert_called_once_with(
        case.effect, exists=True, output=case.prepared.brief, action_id=case.prepared.action_id
    )

"""Canonical native model metadata recognition; supplied SQL rows, no model/body execution."""

from copy import deepcopy
from datetime import timedelta
from typing import cast
from uuid import UUID

import pytest

from nexus.company.contracts.actions import ApprovalDecision
from nexus.company.contracts.results import ActionReceipt
from nexus.company.cycle_artifacts.issued_facts import require_cycle_publication_intent_locked
from nexus.execution.runtime_models import EffectIntent
from nexus.harness.journal_models import JournalAction
from nexus.tests.unit.selected_intent_boundary_fixture import IntentBoundary
from nexus.tests.unit.test_cycle_publication_verifier import mixed_issuance


@pytest.mark.parametrize("damage", ["artifact_id", "revision", "after_expiry", "at_expiry"])
async def test_real_publication_boundary_denies_noncanonical_model_metadata(damage: str) -> None:
    session, supplied, rows = mixed_issuance()
    case = cast(IntentBoundary, supplied)
    journal, effect = cast(JournalAction, rows[0]), cast(EffectIntent, rows[1])
    if damage in {"artifact_id", "revision"}:
        receipt = ActionReceipt.model_validate_json(effect.receipt_json or "")
        field, value = (
            ("artifact_id", UUID(int=1400))
            if damage == "artifact_id"
            else ("revision", "non-model-result-v1")
        )
        artifact = receipt.artifacts[0].model_copy(update={field: value})
        effect.receipt_json = receipt.model_copy(
            update={"artifacts": (artifact,)}
        ).model_dump_json()
    else:
        approval = ApprovalDecision.model_validate_json(journal.approval_json or "")
        expires = effect.created_at - timedelta(milliseconds=500 if damage == "after_expiry" else 0)
        journal.approval_json = approval.model_copy(
            update={"expires_at": expires}
        ).model_dump_json()
        assert journal.consumed_at is not None and journal.consumed_at < expires
    selected = [case.work, case.action, case.hold, *rows]
    before = deepcopy(
        [
            {key: value for key, value in vars(row).items() if not key.startswith("_sa_")}
            for row in selected
        ]
    )
    with pytest.raises(ValueError):
        await require_cycle_publication_intent_locked(
            session, case.work, case.proposal, case.action
        )
    assert [
        {key: value for key, value in vars(row).items() if not key.startswith("_sa_")}
        for row in selected
    ] == before
    session.add.assert_not_called()
    session.flush.assert_not_awaited()


@pytest.mark.parametrize("index", [4, 6])
async def test_canonical_model_receipt_may_be_recorded_after_original_approval_expiry(
    index: int,
) -> None:
    session, supplied, rows = mixed_issuance(index)
    case = cast(IntentBoundary, supplied)
    journal, effect = cast(JournalAction, rows[0]), cast(EffectIntent, rows[1])
    approval = ApprovalDecision.model_validate_json(journal.approval_json or "")
    expires = effect.created_at + timedelta(milliseconds=500)
    journal.approval_json = approval.model_copy(update={"expires_at": expires}).model_dump_json()
    receipt = ActionReceipt.model_validate_json(effect.receipt_json or "")
    assert effect.created_at < expires < receipt.recorded_at <= case.now
    observed = await require_cycle_publication_intent_locked(
        session, case.work, case.proposal, case.action
    )
    assert observed.effect is rows[4]
    session.add.assert_not_called()
    session.flush.assert_not_awaited()

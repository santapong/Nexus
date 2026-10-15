"""Publisher state gates are supplied-row component checks, not native execution proofs."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.contracts.results import ActionReceipt
from nexus.execution.runtime_models import EffectIntent
from nexus.tests.unit.cycle_deliverable_fixture import deliverable_case


@pytest.mark.parametrize("state", ["intent", "outcome_unknown", "failed", "succeeded"])
@pytest.mark.parametrize("exists", [False, True])
def test_pair_publication_state_never_promotes_unknown_or_partial_history(
    state: str, exists: bool
) -> None:
    from nexus.company.cycle_artifacts.deliverable_store import require_publication_state

    case = deliverable_case()
    refs = tuple(row.artifact for row in case.prepared.manifest.parts)
    receipt = ActionReceipt(
        company_id=case.basis.company_id,
        receipt_id=case.action_id,
        action_id=case.action_id,
        task_id=case.basis.author.task_id,
        trace_id=case.basis.author.trace_id,
        proposal_hash="a" * 64,
        outcome="succeeded",
        recorded_at=case.basis.observed_at,
        artifacts=tuple(
            ArtifactRef(
                company_id=ref.company_id,
                artifact_id=ref.artifact_id,
                revision=ref.revision,
                sha256=ref.sha256,
                reference="supplied-component-output",
            )
            for ref in refs
        ),
    )
    effect = EffectIntent(
        company_id=case.basis.company_id,
        action_id=case.action_id,
        task_id=receipt.task_id,
        trace_id=receipt.trace_id,
        run_id=case.basis.author.run_id,
        proposal_hash=receipt.proposal_hash,
        intent_fence=1,
        attempt_kind="tool_attempts",
        state=state,
        receipt_json=receipt.model_dump_json() if state == "succeeded" else None,
    )
    allowed = state == "intent" or (state == "succeeded" and exists)
    if allowed:
        require_publication_state(effect, refs, exists=exists, current_fence=1)
    else:
        with pytest.raises(ValueError):
            require_publication_state(effect, refs, exists=exists, current_fence=1)


def test_unissued_or_old_fence_cannot_publish_fresh_bytes() -> None:
    from nexus.company.cycle_artifacts.deliverable_store import require_publication_state

    case = deliverable_case()
    refs = tuple(row.artifact for row in case.prepared.manifest.parts)
    effect = MagicMock(
        spec=EffectIntent,
        state="intent",
        intent_fence=1,
        receipt_json=None,
        company_id=case.basis.company_id,
        action_id=case.action_id,
    )
    with pytest.raises(ValueError):
        require_publication_state(effect, refs, exists=False, current_fence=2)


@pytest.mark.parametrize("expired", ["initial", "current"])
async def test_real_two_phase_method_retains_both_windows_after_postwrite_await(
    monkeypatch: pytest.MonkeyPatch,
    expired: str,
) -> None:
    from collections.abc import AsyncIterator
    from contextlib import asynccontextmanager
    from datetime import datetime, timedelta
    from types import SimpleNamespace
    from typing import cast

    from nexus.company.cycle_artifacts import deliverable_store as module
    from nexus.company.cycle_artifacts.input_reader import CycleInputReader
    from nexus.company.cycle_artifacts.publication_contracts import (
        CycleAuthorMaterial,
        CycleReadProtection,
    )
    from nexus.tests.unit.cycle_prerequisite_fixture import signed_identity
    from nexus.tests.unit.cycle_publication_row_fixture import row_case
    from nexus.tests.unit.test_cycle_publication_intent import cycle_boundary

    case, described = cycle_boundary(), row_case()
    credential = await signed_identity(case.identity)
    clock = [case.now]
    staged: list[str] = []

    class Window:
        def __init__(self, seconds: int) -> None:
            self.deadline = case.now + timedelta(seconds=seconds)

        def require_time(self, now: datetime) -> None:
            if now >= self.deadline:
                raise ValueError("retained publication window expired")

    initial, current = (
        Window(1 if expired == "initial" else 60),
        Window(1 if expired == "current" else 60),
    )
    material = CycleAuthorMaterial(
        described.prepared, MagicMock(), cast(CycleReadProtection, Window(60))
    )
    session = MagicMock()
    session.flush = AsyncMock()

    @asynccontextmanager
    async def transaction(
        *args: object, **kwargs: object
    ) -> AsyncIterator[tuple[object, object, object]]:
        before = list(staged)
        try:
            yield session, case.control, object()
        except BaseException:
            staged[:] = before  # Supplied rollback delivery; this is not a SQL rollback claim.
            raise

    async def append(*args: object) -> None:
        staged.extend(("json", "human", "complete edges and events"))

    async def replay(*args: object) -> None:
        clock[0] = case.now + timedelta(seconds=2)

    adapter = SimpleNamespace(
        factory=object(),
        blobs=SimpleNamespace(save=AsyncMock(), storage_symbol="fixture"),
        inputs=SimpleNamespace(
            scope=CycleInputReader.scope,
            rules=SimpleNamespace(rule=lambda *args: described.write_rule),
        ),
        composition=lambda: (),
        require_composition=lambda original: None,
        references=module.CycleDeliverableStore.references,
        _exists=AsyncMock(return_value=False),
        _gate=AsyncMock(side_effect=[initial, current]),
        _replay=AsyncMock(side_effect=replay),
    )
    # Prior native proof/issuance/recipient delivery and row IO are explicit mocks. The actual
    # two-phase method, real current lease, signed credential and retained final clocks execute.
    monkeypatch.setattr(module, "runtime_transaction", transaction)
    monkeypatch.setattr(module, "execution_row", AsyncMock(return_value=case.work))
    monkeypatch.setattr(module, "db_now", AsyncMock(side_effect=lambda session: clock[0]))
    monkeypatch.setattr(module, "append_author_locked", append)
    with pytest.raises(ValueError, match="retained publication window"):
        await module.CycleDeliverableStore._publish(
            cast(module.CycleDeliverableStore, adapter),
            case.lease,
            case.identity,
            material,
            credential,
        )
    assert not staged and adapter.blobs.save.await_count == 2
    session.flush.assert_awaited_once()

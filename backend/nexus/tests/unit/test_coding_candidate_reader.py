"""Candidate reads cannot turn C identity or model metadata into owner READ authority.

Cohesion exception: the full real prepared/model-file fixture and its supplied
native history remain together so no reconstructed DTO can replace a store seal.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID, uuid5

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.builder.contained_query import clock_us
from nexus.company.access import CompanyControlScope
from nexus.company.contracts.actions import ApprovalDecision
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.coding_content import CodeChangeContent
from nexus.company.management.cycle_cost_contracts import (
    DirectoryCostWork,
    NativeCostAttempt,
    NativeCostHold,
    NativeCostSelection,
)
from nexus.company.management.lifecycle import PlanRevision
from nexus.core.llm.company_adapter_contracts import CompanyModelResult
from nexus.core.llm.company_pricing import TokenUsage, quote_cost, reconcile_cost
from nexus.execution.coding_candidate_reader import CodingCandidateReader
from nexus.execution.coding_lifecycle_bindings import CodingBundle
from nexus.execution.runtime_contracts import EffectRecord
from nexus.execution.runtime_support import snapshot
from nexus.harness.journal_budget import billing_day
from nexus.harness.journal_contracts import ActionRecord
from nexus.harness.journal_models import CompanyControl
from nexus.harness.lifecycle import ActionState
from nexus.harness.model_evidence import ModelEvidence
from nexus.tests.unit.coding_application_fixture import application
from nexus.tests.unit.test_coding_content import PATCH
from nexus.tests.unit.test_coding_intent import prepared_case, witness
from nexus.tests.unit.test_coding_owner_reads import OwnerCase, owner_case
from nexus.tests.unit.test_nexus_coding_admission import planning_origin


@dataclass
class CandidateCase:
    """Actual H input and model files; current r2/native SQL delivery is supplied."""

    owner: OwnerCase
    reader: CodingCandidateReader
    selected: NativeCostSelection
    content: CodeChangeContent


async def candidate_case(root: Path, monkeypatch: pytest.MonkeyPatch) -> CandidateCase:
    """Historical supplied finance does not fund the unchanged0.1USD C allocation."""
    from nexus.execution import coding_candidate_reader as module
    from nexus.execution import coding_lifecycle_bindings as bindings

    f = await owner_case(root, monkeypatch)
    prepared, now = f.prepared, datetime.now(UTC)
    admission = f.services.management.catalog.nexus_coding_admission
    assert admission is not None and f.delivery.action is not None
    action = f.delivery.action
    digest = f.row.proposal_hash
    model = next(
        row
        for row in f.services.management.catalog.models.models
        if row.registry_id == prepared.request.registry_id
    )
    quote = quote_cost(model.price, prepared.request.bounds, now=now)
    assert quote.amount_usd > admission.slots[1].child.allocation_usd
    content = CodeChangeContent(
        patch=PATCH,
        explanation="Apply the cited change to the captured source.",
        questions=(),
        evidence_ids=(prepared.context.manifest.inclusions[0].handle.evidence_id,),
    )
    usage = TokenUsage(input_tokens=100, output_tokens=20)
    evidence = ModelEvidence(
        request=prepared.request,
        request_hash=prepared.request_sha256,
        action_hash=digest,
        model=model,
        registry_revision=f.services.management.catalog.models.revision,
        price_version=prepared.request.price_version,
        recipe=prepared.input_recipe,
        input_estimate=prepared.input_estimate,
        result=CompanyModelResult(
            request_id=prepared.request.request_id,
            status="response",
            billing="known",
            usage=usage,
            text=content.model_dump_json(),
            structured_json=content.model_dump_json(),
        ),
        source_event_at=now + timedelta(microseconds=100),
        checked_at=now + timedelta(microseconds=101),
        owner_id=f.owner.identity.principal_id,
    )
    artifact = await f.services.evidence.save(evidence)
    receipt = ActionReceipt(
        company_id=action.company_id,
        receipt_id=uuid5(action.action_id, "model-receipt-v1"),
        action_id=action.action_id,
        task_id=action.task_id,
        trace_id=action.trace_id,
        proposal_hash=digest,
        outcome="succeeded",
        recorded_at=evidence.checked_at,
        artifacts=(artifact,),
    )
    intent = EffectRecord(
        company_id=action.company_id,
        action_id=action.action_id,
        task_id=action.task_id,
        trace_id=action.trace_id,
        run_id=prepared.binding.run_id,
        proposal_hash=digest,
        attempt_kind="model_requests",
        intent_fence=1,
        state="succeeded",
        receipt=receipt,
        verification=None,
        created_at=now,
    )
    native = snapshot(f.native).model_copy(
        update={"counters": snapshot(f.native).counters.model_copy(update={"model_requests": 1})}
    )
    selected = NativeCostSelection(
        directory=DirectoryCostWork(
            company_id=action.company_id,
            task_id=action.task_id,
            trace_id=action.trace_id,
            actor_id=action.actor_id,
            workspace_id=prepared.binding.workspace_id,
            parent_task_id=admission.procedure.binding.task_id,
            root_task_id=admission.procedure.binding.task_id,
            allocation_usd=admission.slots[1].child.allocation_usd,
            delegated_usd=Decimal(0),
            active=False,
            work=native,
        ),
        action=ActionRecord(
            company_id=action.company_id,
            proposal=action,
            proposal_hash=digest,
            state=ActionState.AUTHORIZED,
            consumed_at=now,
            approval=ApprovalDecision(
                company_id=action.company_id,
                decision_id=UUID(int=9210),
                action_id=action.action_id,
                action_revision=1,
                action_hash=digest,
                approver_id=f.owner.identity.principal_id,
                decision="approved",
                issued_at=now - timedelta(microseconds=1),
                expires_at=now + timedelta(microseconds=50),
            ),
        ),
        hold=NativeCostHold(
            company_id=action.company_id,
            action_id=action.action_id,
            task_id=action.task_id,
            day=billing_day(now),
            amount_usd=quote.amount_usd,
            actual_usd=reconcile_cost(model.price, usage, now=evidence.source_event_at).amount_usd,
            state="reconciled",
        ),
        intent=intent,
        attempt=NativeCostAttempt(
            company_id=action.company_id,
            task_id=action.task_id,
            trace_id=action.trace_id,
            attempt_id=action.action_id,
            kind="model_requests",
            fence=1,
            reserved_at=now,
        ),
    )
    reader = CodingCandidateReader(f.services, f.reader)
    result = CandidateCase(f, reader, selected, content)

    async def r2(*args: object) -> tuple[CodingBundle, int]:
        assert type(args[-1]) is int
        bound = f.delivery.native().current.current
        payload = admission.payload("execution", origin=planning_origin(admission))
        plan = PlanRevision(
            **prepared.binding.plan.model_dump(),
            payload=payload,
            proposed_by=f.owner.identity.principal_id,
            recorded_at=now,
        )
        return CodingBundle(plan, bound, snapshot(f.native)), args[-1]

    async def static(*args: object) -> int:
        assert type(args[-1]) is int
        return args[-1]

    @asynccontextmanager
    async def transaction(
        *args: object, **kwargs: object
    ) -> AsyncIterator[tuple[AsyncSession, CompanyControl, None]]:
        yield f.session, f.delivery.control, None

    monkeypatch.setattr(module, "management_owner_transaction", transaction)
    monkeypatch.setattr(module, "approved_r2_locked", r2)
    monkeypatch.setattr(module, "static_read_locked", static)
    monkeypatch.setattr(module, "db_now", AsyncMock(side_effect=lambda _: datetime.now(UTC)))
    monkeypatch.setattr(bindings, "db_clock", AsyncMock(side_effect=lambda _: datetime.now(UTC)))
    monkeypatch.setattr(
        module, "native_cost_selection", AsyncMock(side_effect=lambda *args: result.selected)
    )
    return result


async def read_candidate(f: CandidateCase) -> object:
    return await f.reader.read(
        f.owner.scope,
        f.owner.owner,
        f.owner.row.id,
        expected_current_revision_id=f.owner.prepared.binding.plan.plan_revision_id,
        end_us=clock_us() + 10_000_000,
    )


async def test_real_owner_files_native_wire_and_patch_produce_only_historical_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nexus.execution.coding_lifecycle_contracts import (
        CodingCandidateReview,
        CodingLifecycleRead,
    )

    f = await candidate_case(tmp_path, monkeypatch)
    result = cast(CodingLifecycleRead[CodingCandidateReview], await read_candidate(f))
    assert result.value.content == f.content
    assert result.value.binding == f.owner.prepared.binding
    assert result.value.historical and not result.value.company_completed
    assert str(tmp_path) not in result.value.model_dump_json(by_alias=True)
    assert not f.reader.pending_owners()
    assert not f.reader._stores and not f.owner.services._stores
    assert not f.reader._owners


@pytest.mark.parametrize("fault", ["receipt", "attempt", "hold", "artifact"])
async def test_crossed_native_anchor_cannot_open_model_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    f = await candidate_case(tmp_path, monkeypatch)
    selected = f.selected
    assert selected.intent is not None and selected.intent.receipt is not None
    if fault == "receipt":
        receipt = selected.intent.receipt.model_copy(update={"receipt_id": UUID(int=9910)})
        f.selected = selected.model_copy(
            update={"intent": selected.intent.model_copy(update={"receipt": receipt})}
        )
    elif fault == "attempt":
        assert selected.attempt is not None
        f.selected = selected.model_copy(
            update={"attempt": selected.attempt.model_copy(update={"fence": 2})}
        )
    elif fault == "hold":
        f.selected = selected.model_copy(update={"hold": None})
    else:
        receipt = selected.intent.receipt.model_copy(update={"artifacts": ()})
        f.selected = selected.model_copy(
            update={"intent": selected.intent.model_copy(update={"receipt": receipt})}
        )
    private = AsyncMock(side_effect=AssertionError("Crossed native anchor read model output"))
    monkeypatch.setattr(f.owner.services.evidence, "load", private)
    with pytest.raises(ValueError, match="known native model anchor"):
        await read_candidate(f)
    private.assert_not_awaited()


async def test_native_change_after_original_wire_read_cannot_deliver_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = await candidate_case(tmp_path, monkeypatch)
    original = f.owner.services.evidence.load

    async def changed(reference: object) -> ModelEvidence:
        from nexus.company.contracts.knowledge import ArtifactRef

        assert isinstance(reference, ArtifactRef)
        value = await original(reference)
        f.selected = f.selected.model_copy(update={"hold": None})
        return value

    monkeypatch.setattr(f.owner.services.evidence, "load", changed)
    with pytest.raises(ValueError, match="known native model anchor"):
        await read_candidate(f)


async def test_cancelled_candidate_keeps_actual_model_read_owned_until_settlement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = await candidate_case(tmp_path, monkeypatch)
    original = f.owner.services.evidence.load
    entered, finish = asyncio.Event(), asyncio.Event()

    async def blocked(reference: object) -> ModelEvidence:
        from nexus.company.contracts.knowledge import ArtifactRef

        assert isinstance(reference, ArtifactRef)
        entered.set()
        await finish.wait()
        return await original(reference)

    monkeypatch.setattr(f.owner.services.evidence, "load", blocked)
    task = asyncio.create_task(read_candidate(f))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert f.reader.pending_owners()
    finally:
        finish.set()
        await asyncio.gather(*f.reader.pending_owners(), return_exceptions=True)
    assert not f.reader.pending_owners()


async def test_candidate_wrong_company_denies_before_private_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = application(tmp_path)
    prepared, _, _, _ = prepared_case()
    actor = await witness(prepared)
    load = AsyncMock(side_effect=AssertionError("Denied scope cannot read model envelope"))
    monkeypatch.setattr(app.services.evidence, "load", load)
    with pytest.raises(ValueError):
        await app.lifecycle.candidates.read(
            CompanyControlScope(
                company_id=UUID(int=999),
                principal_id=actor.identity.principal_id,
                operation_id=UUID(int=901),
                trace_id=UUID(int=902),
            ),
            actor,
            prepared.request.action_id,
            expected_current_revision_id=prepared.binding.plan.plan_revision_id,
            end_us=clock_us() + 5_000_000,
        )
    load.assert_not_awaited()

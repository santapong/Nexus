"""Pure selectors/current owner reads over explicit SQL delivery, never native authority."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID, uuid5

import pytest

from nexus.builder.contained_query import clock_us
from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.contracts.results import ActionReceipt
from nexus.company.directory_models import DirectoryMembership
from nexus.core.llm.company_adapter_contracts import CompanyModelResult, request_hash
from nexus.core.llm.company_pricing import TokenUsage
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.qualification_reads import QualificationReader
from nexus.execution.qualification_service import QualificationPreparationService
from nexus.execution.qualification_worker_recovery import receipt_for
from nexus.execution.runtime_contracts import EffectRecord
from nexus.execution.runtime_models import EffectIntent
from nexus.harness.canonical import action_hash
from nexus.harness.journal_budget import billing_day
from nexus.harness.journal_models import CostHold, JournalAction
from nexus.harness.qualification_evidence import (
    FileQualificationEvidenceStore,
    IssuedQualificationEvidence,
    QualificationEvidence,
)
from nexus.tests.unit.test_qualification_contracts import NOW
from nexus.tests.unit.test_qualification_service import Rows, delivery


async def selected() -> tuple[QualificationPreparationService, SegmentCommand, JournalAction]:
    rows, recipe, scope, identity = await delivery()
    service = QualificationPreparationService(rows.factory, (recipe,))
    prepared = await service.prepare_qualification(scope, identity, recipe.recipe_id)
    work = prepared.work
    command = SegmentCommand(
        company_id=scope.company_id,
        task_id=prepared.request.task_id,
        trace_id=prepared.request.trace_id,
        actor_id=identity.principal_id,
        workspace_id=identity.workspace_id,
        run_id=work.registration.run_id,
        action_id=prepared.request.action_id,
        segment_id=uuid5(work.registration.run_id, "unit-descriptor"),
    )
    return service, command, cast(JournalAction, rows.rows[JournalAction])


async def test_selector_returns_frozen_catalog_recipe_without_preparation_or_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.harness.journal_submission import pending_action_record

    service, command, action = await selected()

    def forbidden(*args: object) -> None:
        raise AssertionError("Pure history selection called current pricing")

    monkeypatch.setattr(QualificationPreparationService, "_quote", staticmethod(forbidden))
    value = service.recipe_for_action(command, pending_action_record(action))
    assert value is service.configured_recipes()[0]


@pytest.mark.parametrize(
    "field", ["company_id", "task_id", "trace_id", "actor_id", "run_id", "action_id"]
)
async def test_selector_denies_cross_scope_and_run_splices(field: str) -> None:
    from nexus.harness.journal_submission import pending_action_record

    service, command, action = await selected()
    with pytest.raises(ValueError):
        service.recipe_for_action(
            command.model_copy(update={field: UUID(int=999)}), pending_action_record(action)
        )


@pytest.mark.parametrize("field", ["tool", "resource", "price_version"])
async def test_selector_checks_exact_proposal_even_with_recomputed_hash(field: str) -> None:
    from nexus.harness.journal_submission import pending_action_record

    service, command, action = await selected()
    record = pending_action_record(action)
    changed = record.proposal.model_copy(update={field: "foreign"})
    record = record.model_copy(update={"proposal": changed, "proposal_hash": action_hash(changed)})
    with pytest.raises(ValueError):
        service.recipe_for_action(command, record)


async def test_owner_catalog_and_status_reads_do_not_prepare_or_reserve() -> None:
    rows, recipe, scope, identity = await delivery()
    preparation = QualificationPreparationService(rows.factory, (recipe,))
    reader = QualificationReader(preparation)
    catalog = await reader.recipes(scope, identity)
    assert len(catalog) == 1 and catalog[0].maximum_reservation is not None
    assert "sdk_pins" not in catalog[0].model_dump_json(by_alias=True)
    assert rows.added == []
    prepared = await preparation.prepare_qualification(scope, identity, recipe.recipe_id)
    before = len(rows.added)
    status = await reader.action_status(scope, identity, prepared.request.action_id)
    assert status.action == prepared.action and status.work == prepared.work
    assert status.hold is None and status.effect is None and status.dispatch is None
    assert status.company_completed is False and len(rows.added) == before


async def test_owner_read_rechecks_actual_role_in_supplied_directory() -> None:
    rows, recipe, scope, identity = await delivery()
    cast(DirectoryMembership, rows.rows[DirectoryMembership]).role = "admin"
    with pytest.raises(ValueError):
        await QualificationReader(QualificationPreparationService(rows.factory, (recipe,))).recipes(
            scope, identity
        )


async def saved_case(
    tmp_path: Path,
) -> tuple[Rows, QualificationReader, CompanyControlScope, VerifiedIdentity, UUID]:
    """Supplied issued SDK data saved by the REAL protected store; SQL only is delivered."""
    rows, recipe, scope, identity = await delivery()
    preparation = QualificationPreparationService(rows.factory, (recipe,))
    ready = await preparation.prepare_qualification(scope, identity, recipe.recipe_id)
    call = ready.request
    original = EffectRecord(
        company_id=call.company_id,
        action_id=call.action_id,
        task_id=call.task_id,
        trace_id=call.trace_id,
        run_id=ready.work.registration.run_id,
        proposal_hash=ready.action.proposal_hash,
        intent_fence=1,
        attempt_kind="model_requests",
        state="intent",
        created_at=NOW,
        receipt=None,
        verification=None,
    )
    response = CompanyModelResult(
        request_id=call.request_id,
        status="response",
        billing="known",
        usage=TokenUsage(input_tokens=10, output_tokens=2),
        text="READY",
    )
    evidence = QualificationEvidence(
        recipe=recipe,
        request=call,
        request_sha256=request_hash(call),
        intent=original,
        provider_result=response,
        owner_id=identity.principal_id,
        checked_at=NOW,
    )
    store = FileQualificationEvidenceStore(tmp_path / "protected")
    ref = await store.save(evidence, end_us=clock_us() + 10_000_000)
    receipt, actual = receipt_for(IssuedQualificationEvidence(ref, evidence))
    raw = EffectIntent(
        **original.model_dump(exclude={"schema_version", "receipt", "verification"}),
        receipt_json=receipt.model_dump_json(by_alias=True),
        verification_json=None,
    )
    raw.state = receipt.outcome
    rows.rows[EffectIntent] = raw
    rows.rows[CostHold] = CostHold(
        action_id=call.action_id,
        company_id=call.company_id,
        task_id=call.task_id,
        day=billing_day(NOW),
        amount_usd=ready.quote.amount_usd,
        actual_usd=actual,
        state="reconciled",
    )
    return rows, QualificationReader(preparation, store), scope, identity, call.action_id


@pytest.mark.parametrize("failed", [False, True])
async def test_safe_result_uses_actual_protected_bytes_and_preserves_native_failure(
    tmp_path: Path, failed: bool
) -> None:
    rows, reader, scope, identity, action = await saved_case(tmp_path)
    if failed:
        raw = cast(EffectIntent, rows.rows[EffectIntent])
        assert raw.receipt_json
        receipt = ActionReceipt.model_validate_json(raw.receipt_json)
        raw.receipt_json = receipt.model_copy(update={"outcome": "failed"}).model_dump_json(
            by_alias=True
        )
        raw.state = "failed"
    value = await reader.result(scope, identity, action, end_us=clock_us() + 10_000_000)
    assert value.availability == "available" and value.provider_result is not None
    assert value.provider_result.text == "READY" and value.actual_usd is not None
    assert value.native_outcome == ("failed" if failed else "succeeded")
    text = value.model_dump_json(by_alias=True)
    assert str(tmp_path) not in text and '"reference"' not in text
    assert not value.profile_quality_evaluated and not value.company_completed


@pytest.mark.parametrize("fault", ["principal", "native", "hold", "missing", "tamper"])
async def test_result_denies_missing_or_crossed_proof_before_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    rows, reader, scope, identity, action = await saved_case(tmp_path)
    raw = cast(EffectIntent, rows.rows[EffectIntent])
    assert raw.receipt_json and reader.evidence
    receipt = ActionReceipt.model_validate_json(raw.receipt_json)
    ref = receipt.artifacts[0]
    if fault == "principal":
        crossed = ref.model_copy(update={"allowed_principals": (UUID(int=999),)})
        raw.receipt_json = receipt.model_copy(update={"artifacts": (crossed,)}).model_dump_json(
            by_alias=True
        )
        monkeypatch.setattr(
            reader.evidence,
            "load",
            AsyncMock(side_effect=AssertionError("No FS before allowed principal")),
        )
    elif fault == "native":
        raw.proposal_hash = "f" * 64
    elif fault == "hold":
        cast(CostHold, rows.rows[CostHold]).actual_usd = Decimal(0)
    elif fault == "missing":
        Path(ref.reference).unlink()
    else:
        path = Path(ref.reference)
        path.chmod(0o600)
        path.write_text("{}")
        path.chmod(0o400)
    value = await reader.result(scope, identity, action, end_us=clock_us() + 10_000_000)
    assert value.availability == "unavailable" and value.provider_result is None


async def test_owner_revoked_during_fs_is_denied_in_final_real_owner_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows, reader, scope, identity, action = await saved_case(tmp_path)
    assert reader.evidence
    original = reader.evidence.load

    async def revoke(reference: ArtifactRef, *, end_us: int) -> QualificationEvidence:
        value = await original(reference, end_us=end_us)
        cast(DirectoryMembership, rows.rows[DirectoryMembership]).membership_active = False
        return value

    monkeypatch.setattr(reader.evidence, "load", revoke)
    with pytest.raises(ValueError):
        await reader.result(scope, identity, action, end_us=clock_us() + 10_000_000)


async def test_result_late_file_return_never_adopts_after_original_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.harness import qualification_evidence as module

    _, reader, scope, identity, action = await saved_case(tmp_path)
    assert reader.evidence
    original = reader.evidence.load
    end = clock_us() + 10_000_000

    async def expire(reference: ArtifactRef, *, end_us: int) -> QualificationEvidence:
        value = await original(reference, end_us=end_us)
        monkeypatch.setattr(module, "clock_us", lambda: end)
        return value

    monkeypatch.setattr(reader.evidence, "load", expire)
    value = await reader.result(scope, identity, action, end_us=end)
    assert value.availability == "unavailable" and value.provider_result is None


async def test_result_final_transaction_close_cannot_publish_after_original_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from collections.abc import AsyncIterator
    from contextlib import asynccontextmanager
    from unittest.mock import MagicMock

    from nexus.harness import qualification_evidence as module

    rows, reader, scope, identity, action = await saved_case(tmp_path)
    end = clock_us() + 10_000_000
    original = rows.transaction
    before = rows.commits

    @asynccontextmanager
    async def closing() -> AsyncIterator[None]:
        async with original():
            yield
        if rows.commits == before + 2:
            monkeypatch.setattr(module, "clock_us", lambda: end)

    cast(MagicMock, rows.session).begin = MagicMock(side_effect=closing)
    with pytest.raises(TimeoutError):
        await reader.result(scope, identity, action, end_us=end)

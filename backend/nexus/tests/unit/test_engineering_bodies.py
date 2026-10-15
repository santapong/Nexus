"""Private byte/window checks with explicit mocked SQL/READ; no native runtime qualification."""

import asyncio
import hashlib
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.builder import engineering_bodies as module
from nexus.builder.engineering_bodies import (
    revalidate_complete_engineering_artifact_locked,
)
from nexus.company.brain.artifact_contracts import ArtifactSlice
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.scope_support import BrainConflictError, BrainDeniedError
from nexus.company.brain.sources import UTF8Span
from nexus.company.management.acceptance_freshness import (
    QualifiedFreshness,
    RegisteredSourceFreshness,
)
from nexus.tests.unit.engineering_body_fixture import (
    body_case,
    described_body,
    described_check,
)
from nexus.tests.unit.engineering_body_fixture import (
    load_body as load,
)


@pytest.mark.parametrize("size", [1, 16384, 16385, 262144, 524288])
async def test_complete_exact_bytes_keep_honest_first_slice(
    monkeypatch: pytest.MonkeyPatch, size: int
) -> None:
    case = body_case(monkeypatch, b"x" * size)
    result = await load(case)
    assert result.raw == case.body.raw and result.first == case.body.first
    assert result.freshness == case.body.freshness
    assert result.first.has_more == (size > 16384)
    assert case.pages.await_count <= 33
    case.slice_check.assert_awaited_once()
    case.reference_check.assert_awaited_once()
    assert case.revalidate.await_args is not None
    assert case.revalidate.await_args.args[2] is result.freshness


async def test_three_byte_utf8_retreat_is_bounded_and_contiguous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = b"x" * 16381 + ("😀" * 126976).encode() + b"xyz"
    assert len(raw) == 524288
    case = body_case(monkeypatch, raw)
    assert (await load(case)).raw == raw
    calls = case.pages.await_args_list
    assert [row.kwargs["max_bytes"] for row in calls[:4]] == [16384, 16383, 16382, 16381]
    assert [row.kwargs["start_byte"] for row in calls[:4]] == [0] * 4
    assert len(calls) <= 132


@pytest.mark.parametrize("change", ["length", "zero", "company", "hash"])
async def test_reference_mismatch_or_excess_size_denies(
    monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    case = body_case(monkeypatch)
    variants: dict[str, dict[str, object]] = {
        "length": {"byte_length": 524289},
        "zero": {"byte_length": 0},
        "company": {"company_id": UUID(int=999)},
        "hash": {"sha256": "f" * 64},
    }
    reference = case.body.first.artifact.model_copy(update=variants[change])
    with pytest.raises(ValueError):
        await module.load_complete_engineering_body(
            case.reader, case.freshness, case.scope, case.identity, reference
        )
    assert case.pages.await_count == int(change == "hash")


@pytest.mark.parametrize(
    "change", ["short", "gap", "more", "grant", "expiry", "head", "source", "classification"]
)
async def test_no_progress_or_snapshot_splice_is_returned(
    monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    case = body_case(monkeypatch)
    original = case.page

    async def page(*args: object, **kwargs: object) -> ArtifactSlice:
        value = await original(*args, **kwargs)  # type: ignore[arg-type]
        offset = value.span.start_byte
        if change == "short":
            return value.model_copy(
                update={
                    "span": UTF8Span(start_byte=0, end_byte=1),
                    "text": "x",
                    "span_sha256": hashlib.sha256(b"x").hexdigest(),
                    "has_more": True,
                }
            )
        if change == "gap":
            return value.model_copy(
                update={"span": value.span.model_copy(update={"start_byte": 1})}
            )
        if change == "more":
            return value.model_copy(update={"has_more": False})
        if offset:
            if change in {"grant", "expiry"}:
                row = value.contributors[0]
                row = row.model_copy(
                    update={"generation": 2} if change == "grant" else {"expires_at": None}
                )
                return value.model_copy(update={"contributors": (row,)})
            if change == "head":
                return value.model_copy(
                    update={
                        "source_heads": (
                            value.source_heads[0].model_copy(update={"generation": 2}),
                        )
                    }
                )
            if change == "source":
                return value.model_copy(
                    update={
                        "source_contributors": (
                            value.source_contributors[0].model_copy(update={"revision": "changed"}),
                        )
                    }
                )
            return value.model_copy(update={"data_classification": "restricted"})
        return value

    case.pages.side_effect = page
    with pytest.raises(ValueError):
        await load(case)
    case.slice_check.assert_not_awaited()


@pytest.mark.parametrize("fault", ["acl", "late_acl", "cause", "utf8"])
async def test_only_exact_utf8_cause_has_four_same_offset_attempts(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    case = body_case(monkeypatch)

    async def denied(*args: object, **kwargs: object) -> ArtifactSlice:
        if fault == "late_acl" and case.pages.await_count == 1:
            return await case.page(*args, **kwargs)  # type: ignore[arg-type]
        if fault in {"acl", "late_acl"}:
            raise BrainDeniedError("Current READ denied")
        if fault == "cause":
            raise BrainDeniedError("Artifact byte boundary splits UTF8 content")
        try:
            b"\xf0".decode()
        except UnicodeDecodeError as exc:
            raise BrainDeniedError("Artifact byte boundary splits UTF8 content") from exc
        raise AssertionError

    case.pages.side_effect = denied
    with pytest.raises(BrainDeniedError):
        await load(case)
    assert case.pages.await_count == {"utf8": 4, "late_acl": 2}.get(fault, 1)
    if fault != "late_acl":
        assert all(row.kwargs["start_byte"] == 0 for row in case.pages.await_args_list)


@pytest.mark.parametrize("where", ["reference", "policy"])
async def test_original_expiry_is_closed_after_last_await(
    monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    case = body_case(monkeypatch)

    async def expire(*args: object) -> None:
        case.now += timedelta(seconds=60)

    target = case.reference_check if where == "reference" else case.revalidate
    target.side_effect = expire
    with pytest.raises(ValueError):
        await load(case)
    assert case.body.first.contributors[0].expires_at is not None


@pytest.mark.parametrize("which", ["factory", "blobs", "policies"])
async def test_composition_is_pinned_through_native_read(
    monkeypatch: pytest.MonkeyPatch, which: str
) -> None:
    case = body_case(monkeypatch)
    original = case.page

    async def change(*args: object, **kwargs: object) -> ArtifactSlice:
        result = await original(*args, **kwargs)  # type: ignore[arg-type]
        target, name = (
            (case.freshness, "_policies") if which == "policies" else (case.reader, which)
        )
        setattr(target, name, object())
        return result

    case.pages.side_effect = change
    with pytest.raises(ValueError):
        await load(case)


async def test_first_policy_is_captured_before_next_page_and_cannot_be_replaced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = body_case(monkeypatch)
    captured: list[str] = []
    original = case.page

    async def page(*args: object, **kwargs: object) -> ArtifactSlice:
        captured.append("page")
        return await original(*args, **kwargs)  # type: ignore[arg-type]

    async def prepare(*args: object) -> tuple[QualifiedFreshness, ...]:
        captured.append("policy")
        return case.body.freshness

    case.pages.side_effect = page
    case.prepare.side_effect = prepare
    changed = case.body.freshness[0]
    changed = QualifiedFreshness(
        changed.source_id, changed.policy.model_copy(update={"freshness_seconds": None}), None, True
    )
    resolved = AsyncMock(return_value=(changed,))
    monkeypatch.setattr(case.freshness, "_resolve", resolved)

    async def revalidate(
        session: AsyncSession,
        scope: BrainReadScope,
        previous: tuple[QualifiedFreshness, ...],
        now: datetime,
    ) -> None:
        await RegisteredSourceFreshness.revalidate(case.freshness, session, scope, previous, now)

    case.revalidate.side_effect = revalidate
    with pytest.raises(ValueError):
        await load(case)
    assert captured == ["page", "policy", "page"]


async def test_paired_gate_denies_actual_stored_tail_with_unchanged_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.company.brain import artifact_store

    case = body_case(monkeypatch)
    first = case.body.first
    snapshot = artifact_store._Snapshot(
        first.artifact,
        "x" * 19999 + "y",
        first.source_contributors,
        first.contributors,
        first.source_heads,
        first.data_classification,
        False,
    )
    reader = BoundedArtifactReader(case.reader.factory, case.reader.blobs)
    reads = AsyncMock(return_value=snapshot)
    monkeypatch.setattr(reader, "_snapshot", reads)
    monkeypatch.setattr(artifact_store, "revalidate_brain_scope", AsyncMock())
    monkeypatch.setattr(artifact_store, "require_resources", AsyncMock())
    monkeypatch.setattr(artifact_store, "_clock", AsyncMock(return_value=case.now))
    # The slice-only comparison accepts this prefix; full-reference hashing must deny the tail.
    await reader.revalidate_artifact(
        case.session, case.control, case.scope, case.identity, first, case.now
    )
    with pytest.raises(BrainConflictError, match="immutable bytes"):
        await revalidate_complete_engineering_artifact_locked(
            reader, case.session, case.control, case.scope, case.identity, first, case.now
        )
    assert reads.await_count == 3


async def test_timeout_and_cancellation_return_no_body(monkeypatch: pytest.MonkeyPatch) -> None:
    case = body_case(monkeypatch)

    async def never(*args: object, **kwargs: object) -> ArtifactSlice:
        await asyncio.Event().wait()
        raise AssertionError

    case.pages.side_effect = never
    monkeypatch.setattr(module, "BODY_READ_SECONDS", 0.05)
    with pytest.raises(TimeoutError):
        await load(case)
    task = asyncio.create_task(load(case))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    case.slice_check.assert_not_awaited()


@pytest.mark.parametrize("fault", ["aggregate_timeout", "output_limit"])
async def test_collection_budget_and_output_bound_are_not_reset_per_artifact(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    from nexus.builder import engineering_inputs
    from nexus.builder.engineering_contracts import EngineeringChangeDeclaration
    from nexus.builder.engineering_metadata import EngineeringMetadata
    from nexus.builder.result_store import BuilderResultStore

    case = body_case(monkeypatch)
    declaration = MagicMock(spec=EngineeringChangeDeclaration)
    declaration.goal_id = UUID(int=99)
    loader = engineering_inputs.RegisteredEngineeringInputs(
        case.reader.factory,
        case.reader,
        MagicMock(spec=BuilderResultStore),
        (declaration,),
        case.freshness,
    )
    reference = case.body.first.artifact
    if fault == "output_limit":
        reference = reference.model_copy(update={"byte_length": 262145})
    metadata = cast(
        EngineeringMetadata,
        SimpleNamespace(
            author_output=reference,
            verifier_output=reference,
            author_spec=SimpleNamespace(protected_patch=reference),
            verifier_spec=SimpleNamespace(protected_patch=reference),
        ),
    )

    async def slow(*args: object) -> module.CompleteEngineeringBody:
        await asyncio.sleep(0.04)
        return case.body

    materialize = AsyncMock(side_effect=slow)
    monkeypatch.setattr(engineering_inputs, "load_complete_engineering_body", materialize)
    monkeypatch.setattr(engineering_inputs, "BODY_READ_SECONDS", 0.06)
    with pytest.raises(TimeoutError if fault == "aggregate_timeout" else ValueError):
        await loader._artifacts(case.scope, case.identity, metadata)
    assert materialize.await_count == (2 if fault == "aggregate_timeout" else 0)


async def test_proof_consumer_keeps_original_freshness_and_generated_size_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.builder import engineering_acceptance
    from nexus.builder.engineering_inputs import RegisteredEngineeringInputs
    from nexus.builder.engineering_proof import EngineeringProofStorage
    from nexus.company.brain.access_contracts import ResourceRef
    from nexus.company.brain.blob_store import ProtectedBlobStore
    from nexus.company.management.plan_catalog import PlanAdmissionCatalog

    case = body_case(monkeypatch)
    expected = described_check()
    proof = EngineeringProofStorage(
        MagicMock(spec=ProtectedBlobStore),
        ResourceRef(company_id=expected.company_id, resource_id=UUID(int=30)),
        case.body.freshness[0].policy,
    )
    reference = proof.reference(expected)
    body = described_body(expected.model_dump_json().encode())
    body = module.CompleteEngineeringBody(
        body.first.model_copy(update={"artifact": reference}), body.raw, body.freshness
    )
    inputs = MagicMock(spec=RegisteredEngineeringInputs)
    inputs.reader, inputs.freshness = case.reader, case.freshness
    acceptance = engineering_acceptance.EngineeringWorkAcceptanceStore(
        case.reader.factory, MagicMock(spec=PlanAdmissionCatalog), inputs, proof
    )
    monkeypatch.setattr(
        engineering_acceptance, "load_complete_engineering_body", AsyncMock(return_value=body)
    )
    first, freshness = await acceptance._checked_proof(
        case.scope, case.identity, expected, reference
    )
    assert first is body.first and freshness is body.freshness
    with pytest.raises(ValueError, match="exceeds"):
        proof.reference(expected.model_copy(update={"limitations": ("x" * 500,) * 40}))
    object.__setattr__(body, "raw", body.raw + b" ")
    with pytest.raises(ValueError):
        await acceptance._checked_proof(case.scope, case.identity, expected, reference)


@pytest.mark.parametrize("fault", ["hash", "nul", "utf8"])
async def test_full_body_integrity_is_checked_after_page_delivery(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    case = body_case(monkeypatch)
    raw = case.body.raw[:-1] + {"hash": b"y", "nul": b"\0", "utf8": b"\xff"}[fault]
    object.__setattr__(case.body, "raw", raw)
    if fault != "hash":
        reference = case.body.first.artifact.model_copy(
            update={"sha256": hashlib.sha256(raw).hexdigest()}
        )
        object.__setattr__(
            case.body, "first", case.body.first.model_copy(update={"artifact": reference})
        )
    with pytest.raises(ValueError):
        await load(case)

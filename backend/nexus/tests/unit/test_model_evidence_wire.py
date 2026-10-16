"""Actual immutable files/processes and pure native DTOs; no SQL/provider/permission proof."""

import asyncio
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.cycle_cost_contracts import (
    DirectoryCostWork,
    NativeCostAttempt,
    NativeCostHold,
    NativeCostSelection,
)
from nexus.company.management.cycle_model_facts import CycleModelFact, join_cycle_model_fact
from nexus.core.llm.company_registry import ModelRegistry
from nexus.harness.model_evidence import FileModelEvidenceStore, ModelEvidence, ModelEvidenceRecord
from nexus.tests.unit.test_cycle_model_facts import Case, case


async def saved_case(root: Path) -> tuple[Case, FileModelEvidenceStore]:
    value = case()
    assert value.evidence and value.intent and value.intent.receipt
    model = value.evidence.model.model_copy(
        update={
            "capabilities": frozenset({"text", "code", "tools", "reasoning", "structured_output"})
        }
    )
    value.registry = value.registry.model_copy(update={"models": (model,)})
    estimate = value.evidence.input_estimate
    if estimate.whole_request is not None:
        estimate = estimate.model_copy(
            update={
                "whole_request": estimate.whole_request.model_copy(
                    update={
                        "model_sha256": canonical_sha256(model),
                        "registry_sha256": canonical_sha256(value.registry),
                    }
                )
            }
        )
    value.evidence = value.evidence.model_copy(update={"model": model, "input_estimate": estimate})
    store = FileModelEvidenceStore(root)
    value.artifact = await store.save(value.evidence)
    value.intent = value.intent.model_copy(
        update={"receipt": value.intent.receipt.model_copy(update={"artifacts": (value.artifact,)})}
    )
    return value, store


def joined(value: Case, wire: bytes | None) -> CycleModelFact:
    return join_cycle_model_fact(
        value.registered,
        value.work,
        value.action,
        value.request,
        value.recipe,
        value.registry,
        attempt=value.attempt,
        intent=value.intent,
        hold=value.hold,
        artifact=value.artifact,
        evidence=value.evidence,
        wire=wire,
    )


async def test_actual_record_calls_existing_load_first_and_retains_original_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value, store = await saved_case(tmp_path)
    assert value.artifact
    original = store.load
    seen = []

    async def current(reference: ArtifactRef) -> ModelEvidence:
        seen.append(reference)
        return await original(reference)

    monkeypatch.setattr(store, "load", current)
    record = await store.load_record(value.artifact)
    assert type(record) is ModelEvidenceRecord and seen == [value.artifact]
    assert record.wire == Path(value.artifact.reference).read_bytes()
    assert hashlib.sha256(record.wire).hexdigest() == value.artifact.sha256
    assert record.evidence == value.evidence and not store.pending_owners()


@pytest.mark.parametrize("fault", ["changed_wire", "empty", "oversize", "semantic", "receipt"])
async def test_wire_or_semantic_or_native_splice_never_confirms_but_keeps_ledger_actual(
    tmp_path: Path,
    fault: str,
) -> None:
    value, store = await saved_case(tmp_path)
    assert (
        value.artifact and value.evidence and value.intent and value.intent.receipt and value.hold
    )
    record = await store.load_record(value.artifact)
    value.evidence = record.evidence
    wire = record.wire
    if fault == "changed_wire":
        wire = wire + b" "
    elif fault == "empty":
        wire = b""
    elif fault == "oversize":
        wire = b"x" * 2_000_001
    elif fault == "semantic":
        value.evidence = value.evidence.model_copy(update={"owner_id": value.request.actor_id})
    else:
        value.intent = value.intent.model_copy(
            update={"receipt": value.intent.receipt.model_copy(update={"proposal_hash": "f" * 64})}
        )
    fact = joined(value, wire)
    assert fact.billing == "unconfirmed" and fact.ledger_actual_usd == value.hold.actual_usd


async def cross_process(root: Path, mode: str) -> dict[str, object]:
    """The child owns finite file IO; restored native DTOs give no current DB/read authority."""
    if mode == "write":
        value, store = await saved_case(root / "models")
        assert value.attempt and value.hold and value.artifact
        native = NativeCostSelection(
            directory=DirectoryCostWork(
                **{
                    key: getattr(value.registered, key)
                    for key in DirectoryCostWork.model_fields
                    if key not in {"schema_version", "work"}
                },
                work=value.work,
            ),
            action=value.action,
            intent=value.intent,
            hold=NativeCostHold(
                **{
                    key: getattr(value.hold, key)
                    for key in NativeCostHold.model_fields
                    if key != "schema_version"
                }
            ),
            attempt=NativeCostAttempt(
                **{
                    key: getattr(value.attempt, key)
                    for key in NativeCostAttempt.model_fields
                    if key != "schema_version"
                }
            ),
        )
        data = {
            "native": native.model_dump(mode="json"),
            "registry": value.registry.model_dump(mode="json"),
            "artifact": value.artifact.model_dump(mode="json"),
            "recipe": value.recipe.model_dump(mode="json"),
        }
        (root / "native.json").write_text(json.dumps(data))
        assert not store.pending_owners()
        return {"saved": True, "permission": False}
    from nexus.company.contracts.knowledge import ArtifactRef
    from nexus.harness.model_authorizer_contracts import ModelInputRecipe

    data = json.loads((root / "native.json").read_bytes())
    native = NativeCostSelection.model_validate_json(json.dumps(data["native"]))
    registry = ModelRegistry.model_validate_json(json.dumps(data["registry"]))
    artifact = ArtifactRef.model_validate_json(json.dumps(data["artifact"]))
    recipe = ModelInputRecipe.model_validate_json(json.dumps(data["recipe"]))
    store = FileModelEvidenceStore(root / "models")
    record = await store.load_record(artifact)

    def result(wire: bytes | None) -> CycleModelFact:
        assert native.directory.work
        assert native.attempt and native.hold
        return join_cycle_model_fact(
            native.directory.directory_data(),
            native.directory.work,
            native.action,
            record.evidence.request,
            recipe,
            registry,
            attempt=native.attempt.native_data(),
            intent=native.intent,
            hold=native.hold.native_data(),
            artifact=artifact,
            evidence=record.evidence,
            wire=wire,
        )

    return {
        "with_wire": result(record.wire).billing,
        "without_wire": result(None).billing,
        "raw_sha_matches": hashlib.sha256(record.wire).hexdigest() == artifact.sha256,
        "permission": False,
    }


def test_same_actual_model_file_qualifies_across_process_hash_seeds_without_wire_rewrite(
    tmp_path: Path,
) -> None:
    script = (
        "import asyncio,json,os,sys;from pathlib import Path;"
        "from nexus.tests.unit.test_model_evidence_wire import cross_process;"
        "os.umask(0o077);print(json.dumps(asyncio.run(cross_process(Path(sys.argv[1]),sys.argv[2]))))"
    )
    output = []
    for seed, mode in (("0", "write"), ("1", "read")):
        run = subprocess.run(
            [sys.executable, "-c", script, str(tmp_path), mode],
            cwd=Path(__file__).resolve().parents[3],
            env={
                "PYTHONPATH": ".",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONHASHSEED": seed,
                "LANG": "C.UTF-8",
            },
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        output.append(json.loads(run.stdout))
    assert output[1] == {
        "with_wire": "known",
        "without_wire": "unconfirmed",
        "raw_sha_matches": True,
        "permission": False,
    }


async def test_existing_source_or_fault_wrapper_denies_before_additional_wire_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, store = await saved_case(tmp_path)
    assert value.artifact
    denied = ValueError("supplied current source denial")
    monkeypatch.setattr(store, "load", AsyncMock(side_effect=denied))
    wire = AsyncMock(side_effect=AssertionError("wire IO after existing read denial"))
    monkeypatch.setattr(store, "_wire_record", wire)
    with pytest.raises(ValueError) as caught:
        await store.load_record(value.artifact)
    assert caught.value is denied
    wire.assert_not_called()


async def test_actual_wire_worker_stays_owned_after_caller_cancellation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from threading import Event

    value, store = await saved_case(tmp_path)
    assert value.artifact
    entered, finish = Event(), Event()
    original = FileModelEvidenceStore._wire_record

    def blocked(
        root: Path, path: Path, reference: ArtifactRef, evidence: ModelEvidence
    ) -> ModelEvidenceRecord:
        entered.set()
        assert finish.wait(5)
        return original(root, path, reference, evidence)

    monkeypatch.setattr(FileModelEvidenceStore, "_wire_record", staticmethod(blocked))
    caller = asyncio.create_task(store.load_record(value.artifact))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        owners = store.pending_owners()
        assert owners and not all(row.done() for row in owners)
        finish.set()
        await asyncio.gather(*owners)
        assert not store.pending_owners() and caller.cancelled()
    finally:
        finish.set()
        await asyncio.gather(caller, return_exceptions=True)


@pytest.mark.parametrize("fault", ["raw_changed", "oversize", "semantic_wrapper"])
async def test_post_legacy_read_file_or_semantic_change_cannot_produce_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    value, store = await saved_case(tmp_path)
    assert value.artifact
    original = store.load

    async def changed(reference: ArtifactRef) -> ModelEvidence:
        evidence = await original(reference)
        if fault == "semantic_wrapper":
            return evidence.model_copy(update={"owner_id": evidence.request.actor_id})
        path = Path(reference.reference)
        raw = path.read_bytes()
        path.chmod(0o600)
        path.write_bytes((b"[" + raw[1:]) if fault == "raw_changed" else b"x" * 2_000_001)
        path.chmod(0o400)
        return evidence

    monkeypatch.setattr(store, "load", changed)
    with pytest.raises(ValueError):
        await store.load_record(value.artifact)
    assert not store.pending_owners()


async def test_final_fd_named_metadata_after_hash_and_parse_denies_same_length_rewrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, store = await saved_case(tmp_path)
    assert value.artifact
    path = Path(value.artifact.reference)
    original = ModelEvidence.model_validate_json
    calls = 0

    def parsed(cls: type[ModelEvidence], raw: str | bytes | bytearray) -> ModelEvidence:
        nonlocal calls
        evidence = original(raw)
        calls += 1
        if calls == 2:
            before = path.read_bytes()
            path.chmod(0o600)
            path.write_bytes(b"[" + before[1:])
            path.chmod(0o400)
        return evidence

    monkeypatch.setattr(ModelEvidence, "model_validate_json", classmethod(parsed))
    with pytest.raises(ValueError):
        await store.load_record(value.artifact)
    assert calls == 2 and not store.pending_owners()

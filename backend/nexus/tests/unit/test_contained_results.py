"""Result/ref binding does not activate execution or replace actual store/authority checks."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from nexus.builder.contained_evidence_store import ContainmentEvidenceStore
from nexus.builder.contained_evidence_types import ContainmentRef, ObservationDeadline
from nexus.builder.contained_observer import ContainmentObserver
from nexus.builder.contained_results import (
    base_result_sha256,
    require_contained_result,
    result_evidence_identity,
)
from nexus.builder.execution_contracts import BuilderExecutionSpec, BuilderRunResult
from nexus.builder.runtime_identity import RUNTIME_V2
from nexus.company.management.canonical import canonical_sha256
from nexus.tests.builder_support import described_job
from nexus.tests.contained_observer_fixture import BOOT
from nexus.tests.unit.test_contained_evidence_types import sample
from nexus.tests.unit.test_contained_observer import IO


def result() -> BuilderRunResult:
    return BuilderRunResult(
        spec=BuilderExecutionSpec(job=described_job(), policy_sha256="a" * 64),
        proposal_sha256="b" * 64,
        intent_fence=3,
        image_id="c" * 64,
        container_name="nexus-builder-" + "d" * 32,
        outcome="commands_failed",
        recorded_at=datetime.now(UTC),
        elapsed_millis=1,
    )


def test_v1_wire_remains_exact_and_excludes_absent_containment() -> None:
    value = result()
    assert "containment" not in value.model_dump()
    assert base_result_sha256(value) == canonical_sha256(value)
    assert BuilderRunResult.model_validate_json(value.model_dump_json()) == value


def test_v2_terminal_result_requires_an_original_issued_containment_reference() -> None:
    raw = result().model_dump()
    raw["spec"] = result().spec.model_copy(update={"runtime_recipe": RUNTIME_V2}).model_dump()
    with pytest.raises(ValueError, match="containment"):
        BuilderRunResult.model_validate(raw)


def test_ref_hash_cycle_exclusion_and_original_fence_are_exact() -> None:
    value = result()
    value = value.model_copy(
        update={"spec": value.spec.model_copy(update={"runtime_recipe": RUNTIME_V2})}
    )
    identity = result_evidence_identity(value, "e" * 64)
    assert identity.original_intent_fence == 3
    ref = ContainmentRef(identity=identity, sha256="f" * 64, byte_length=1)
    bound = value.model_copy(update={"containment": ref})
    assert base_result_sha256(bound) == base_result_sha256(value)
    assert canonical_sha256(bound) != canonical_sha256(value)
    for key, changed in [("original_intent_fence", 4), ("result_base_sha256", "0" * 64)]:
        bad = ref.model_copy(update={"identity": identity.model_copy(update={key: changed})})
        with pytest.raises(ValueError, match="containment"):
            BuilderRunResult.model_validate(
                bound.model_copy(update={"containment": bad}).model_dump()
            )


def test_runtime_v1_cannot_attach_new_containment_metadata() -> None:
    value = result()
    ref = ContainmentRef(
        identity=result_evidence_identity(value, "e" * 64), sha256="f" * 64, byte_length=1
    )
    with pytest.raises(ValueError, match="containment"):
        BuilderRunResult.model_validate(value.model_copy(update={"containment": ref}).model_dump())


async def test_actual_sidecar_reread_binds_original_result_and_rejects_changed_bytes(
    tmp_path: Path,
) -> None:
    value = result()
    job = value.spec.job.model_copy(update={"company_id": BOOT, "action_id": BOOT})
    spec = value.spec.model_copy(update={"job": job, "runtime_recipe": RUNTIME_V2})
    value = value.model_copy(
        update={
            "spec": spec,
            "image_id": "a" * 64,
            "container_name": "nexus-builder-" + "c" * 32,
        }
    )
    identity = result_evidence_identity(value, "e" * 64)
    from nexus.builder.runtime_identity import RUNTIME_V2_METHOD_SHA256

    observer = ContainmentObserver(IO([]), clock_us=lambda: 12_040_000)
    observation = await observer.finish(
        (sample(),),
        identity,
        spec_sha256=canonical_sha256(spec),
        proposal_sha256=value.proposal_sha256,
        selector_sha256=RUNTIME_V2_METHOD_SHA256,
        deadline=ObservationDeadline(end_us=13_000_000),
    )
    store = ContainmentEvidenceStore(tmp_path / "sidecars")
    ref = await store.save_once(observation)
    bound = BuilderRunResult.model_validate(
        value.model_copy(update={"containment": ref}).model_dump()
    )
    assert await require_contained_result(bound, store, "e" * 64) == observation
    with pytest.raises(ValueError, match="original issuance"):
        await require_contained_result(bound, store, "0" * 64)
    path = store.root / store.filename(identity)
    path.write_bytes(b"{}")
    with pytest.raises(ValueError, match="bytes"):
        await require_contained_result(bound, store, "e" * 64)

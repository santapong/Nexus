"""Pure check-output identity; native bundle linkage and publication are not exercised."""

import hashlib
from uuid import UUID

import pytest

from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.acceptance_errors import AcceptanceDeniedError
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.generated_artifact_contracts import GeneratedArtifactInputs
from nexus.company.strategy.check_output import (
    prepare_strategy_check,
    require_strategy_check_bytes,
    strategy_check_production_snapshot,
)
from nexus.company.strategy.checker import check_strategy_brief
from nexus.tests.unit.strategy_brief_fixture import strategy_case


def inputs() -> GeneratedArtifactInputs:
    case = strategy_case()
    assert case.command.snapshot is not None
    original = case.command.snapshot.inputs
    bundle = case.command.output.model_copy(
        update={"artifact_id": UUID(int=880), "artifact_revision_id": UUID(int=881)}
    )
    return original.model_copy(
        update={"artifacts": (*original.artifacts, bundle, case.command.output)}
    )


def result_ref(raw: bytes) -> ArtifactRevisionRef:
    return ArtifactRevisionRef(
        company_id=strategy_case().command.company_id,
        artifact_id=UUID(int=882),
        artifact_revision_id=UUID(int=883),
        revision="synthetic-result-v1",
        sha256=hashlib.sha256(raw).hexdigest(),
        byte_length=len(raw),
    )


def test_check_output_hash_binds_complete_check_manifest_and_original_target() -> None:
    command = strategy_case().command
    prepared = prepare_strategy_check(command, inputs(), "internal")
    production = strategy_check_production_snapshot(command, inputs())
    assert prepared.input_snapshot_sha256 == canonical_sha256(production)
    assert command.snapshot is not None
    assert prepared.input_snapshot_sha256 != canonical_sha256(command.snapshot)
    result = require_strategy_check_bytes(
        command, inputs(), result_ref(prepared.raw_bytes), prepared.raw_bytes
    )
    assert result == check_strategy_brief(command)
    assert result.verdict == "pass" and result.strategic_merit == "not_evaluated"


def test_self_consistent_relabelled_check_result_is_rejected() -> None:
    command = strategy_case().command
    original = check_strategy_brief(command)
    raw = original.model_copy(update={"verdict": "inconclusive"}).model_dump_json().encode()
    with pytest.raises(AcceptanceDeniedError):
        require_strategy_check_bytes(command, inputs(), result_ref(raw), raw)


@pytest.mark.parametrize(
    "kind", ["source", "author_output", "contributors", "evidence", "resource"]
)
def test_check_manifest_cannot_omit_original_inputs(kind: str) -> None:
    command = strategy_case().command
    declared = inputs()
    assert command.snapshot is not None
    updates: dict[str, object] = {
        "artifacts": tuple(
            row for row in declared.artifacts if row != command.snapshot.inputs.artifacts[0]
        )
        if kind == "source"
        else tuple(row for row in declared.artifacts if row != command.output)
    }
    if kind == "contributors":
        updates = {"contributors": ()}
    elif kind == "evidence":
        updates = {"evidence": ()}
    elif kind == "resource":
        updates = {"required_resource_ids": (UUID(int=999),)}
    with pytest.raises(ValueError):
        strategy_check_production_snapshot(command, declared.model_copy(update=updates))


@pytest.mark.parametrize(
    "changes", [{"output_utf8": b"changed"}, {"snapshot": None}, {"output_utf8": None}]
)
def test_absent_or_changed_author_output_cannot_compile(changes: dict[str, object]) -> None:
    with pytest.raises(AcceptanceDeniedError):
        prepare_strategy_check(
            strategy_case().command.model_copy(update=changes), inputs(), "internal"
        )


def test_full_target_and_manifest_changes_change_the_production_identity() -> None:
    command = strategy_case().command
    old = prepare_strategy_check(command, inputs(), "internal")
    changed = command.model_copy(
        update={"target": command.target.model_copy(update={"receipt_id": UUID(int=999)})}
    )
    new = prepare_strategy_check(changed, inputs(), "internal")
    assert new.input_snapshot_sha256 != old.input_snapshot_sha256
    assert new.raw_bytes != old.raw_bytes


def test_input_snapshot_raw_counts_revalidate_before_serialization() -> None:
    command = strategy_case().command
    assert command.snapshot is not None
    registration = command.snapshot.author_registration
    broken = registration.model_copy(
        update={"quota": registration.quota.model_copy(update={"model_requests": True})}
    )
    command = command.model_copy(
        update={"snapshot": command.snapshot.model_copy(update={"author_registration": broken})}
    )
    with pytest.raises(ValueError):
        prepare_strategy_check(command, inputs(), "internal")

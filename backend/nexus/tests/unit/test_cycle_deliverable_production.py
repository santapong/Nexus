"""Supplied-data exports; no actual engineering acceptance, storage or customer work."""

import json

import pytest

from nexus.company.cycle_artifacts.checker import check_cycle_artifact
from nexus.company.cycle_artifacts.common import CycleKind
from nexus.company.cycle_artifacts.contracts import checked_basis
from nexus.company.cycle_artifacts.production import (
    PreparedCycleDeliverable,
    prepare_presentation,
    prepare_support,
)
from nexus.company.management.canonical import canonical_sha256
from nexus.tests.unit.cycle_deliverable_fixture import deliverable_case


@pytest.mark.parametrize("kind", ["presentation", "support"])
def test_two_exact_outputs_preserve_original_basis_and_have_no_hash_cycle(kind: CycleKind) -> None:
    case = deliverable_case(kind)
    before = case.basis.model_dump_json()
    expected = prepare_presentation if kind == "presentation" else prepare_support
    again = expected(case.basis, case.action_id)
    assert again == case.prepared and case.basis.model_dump_json() == before
    assert case.prepared.output_manifest_sha256 == canonical_sha256(case.prepared.manifest)
    assert b'"budget_usd":"0.080000"' in case.prepared.typed_json
    assert case.prepared.output_manifest_sha256.encode() not in case.prepared.typed_json
    assert all(
        row.artifact.sha256.encode() not in case.prepared.typed_json
        for row in case.prepared.manifest.parts
    )
    assert check_cycle_artifact(case.command()).verdict == "pass"
    assert (
        "approved" not in type(case.prepared).model_fields
        and "owner_id" not in type(case.prepared).model_fields
    )


@pytest.mark.parametrize("field", ["typed_json", "human_export", "manifest"])
def test_copied_prepared_bytes_or_manifest_cannot_replace_recomputed_output(field: str) -> None:
    case = deliverable_case()
    value = case.prepared
    changed = (
        value.manifest.model_copy(update={"action_id": case.basis.author.task_id})
        if field == "manifest"
        else b"changed"
    )
    with pytest.raises(ValueError):
        PreparedCycleDeliverable.model_validate(value.model_dump() | {field: changed})


@pytest.mark.parametrize("raw", [False, 0.0, "0"])
def test_raw_copied_unchanged_zero_quota_denies_before_json_normalization(raw: object) -> None:
    case = deliverable_case()
    reg = case.basis.author_registration
    quota = reg.quota.model_copy(update={"rework_rounds": raw})
    basis = case.basis.model_copy(
        update={"author_registration": reg.model_copy(update={"quota": quota})}
    )
    with pytest.raises(ValueError):
        checked_basis(basis)
    with pytest.raises(ValueError):
        prepare_presentation(basis, case.action_id)


@pytest.mark.parametrize(
    "key,value",
    [
        ("deployment_state", "deployed"),
        ("fact_ids", ["customer_success"]),
        ("customer_id", "invented"),
    ],
)
def test_unsupported_claims_and_customer_identity_cannot_pass(key: str, value: object) -> None:
    case = deliverable_case()
    body = json.loads(case.prepared.typed_json)
    body[key] = value
    command = case.command().model_copy(update={"typed_json": json.dumps(body).encode()})
    assert check_cycle_artifact(command).verdict == "reject"


@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'{"x":NaN}', b"\xff", b"[" * 30 + b"]" * 30])
def test_malformed_or_deep_json_denies_without_passing_export(raw: bytes) -> None:
    case = deliverable_case()
    assert (
        check_cycle_artifact(case.command().model_copy(update={"typed_json": raw})).verdict
        == "reject"
    )


@pytest.mark.parametrize("field", ["original", "typed_json", "human_export"])
def test_missing_protected_material_is_honestly_inconclusive(field: str) -> None:
    case = deliverable_case()
    result = check_cycle_artifact(case.command().model_copy(update={field: None}))
    assert result.verdict == "inconclusive" and "business_readiness_unproven" in result.limitations


def test_original_input_manifest_cannot_include_the_same_action_future_output() -> None:
    case = deliverable_case()
    inputs = case.basis.inputs.model_copy(
        update={
            "artifacts": (*case.basis.inputs.artifacts, case.prepared.manifest.parts[0].artifact)
        }
    )
    with pytest.raises(ValueError, match="own future outputs"):
        prepare_presentation(case.basis.model_copy(update={"inputs": inputs}), case.action_id)

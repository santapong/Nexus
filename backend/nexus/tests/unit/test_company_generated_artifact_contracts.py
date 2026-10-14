"""Server-prepared declarations bind exact bytes/inputs; they cannot grant publication."""

import hashlib
import json
from decimal import Decimal
from uuid import uuid4

import pytest

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.sources import ArtifactRevisionRef, SourceRevisionRef
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.generated_artifact_contracts import (
    GeneratedArtifactActionParameters,
    GeneratedArtifactInputs,
    GeneratedArtifactPayload,
    GeneratedArtifactRule,
)
from nexus.company.management.generated_artifact_identity import (
    generated_derivation_id,
    generated_reference,
    require_action_payload,
)


def payload(
    raw: bytes = "รายงาน: usage unknown; date 2026-10".encode(),
) -> GeneratedArtifactPayload:
    company = uuid4()
    source = SourceRevisionRef(
        company_id=company, source_id=uuid4(), source_revision_id=uuid4(), revision="source-v2"
    )
    artifact = ArtifactRevisionRef(
        company_id=company,
        artifact_id=uuid4(),
        artifact_revision_id=uuid4(),
        revision="source-v2",
        sha256="b" * 64,
        byte_length=53,
    )
    return GeneratedArtifactPayload(
        company_id=company,
        raw_bytes=raw,
        output_sha256=hashlib.sha256(raw).hexdigest(),
        input_snapshot_sha256="c" * 64,
        recipe_version="native-internal-report-v1",
        data_classification="restricted",
        inputs=GeneratedArtifactInputs(
            company_id=company,
            artifacts=(artifact,),
            contributors=(source,),
            required_resource_ids=(uuid4(),),
        ),
    )


def action(prepared: GeneratedArtifactPayload) -> ActionProposal:
    return ActionProposal(
        company_id=prepared.company_id,
        action_id=uuid4(),
        task_id=uuid4(),
        trace_id=uuid4(),
        actor_id=uuid4(),
        revision=1,
        tool="company.report.write.v1",
        tool_version="v1",
        resource="company.report.output",
        parameters=GeneratedArtifactActionParameters(
            recipe_version=prepared.recipe_version,
            output_sha256=prepared.output_sha256,
            input_snapshot_sha256=prepared.input_snapshot_sha256,
            report_id=uuid4(),
            evidence_ids=(uuid4(),),
        ).model_dump(mode="json", exclude_none=True),
        policy_version="native-policy-v1",
        price_version="native-prices-v1",
        estimated_cost_usd=Decimal("0"),
    )


def rule(prepared: GeneratedArtifactPayload) -> GeneratedArtifactRule:
    return GeneratedArtifactRule(
        company_id=prepared.company_id,
        tool="company.report.write.v1",
        resource_symbol="company.report.output",
        target=ResourceRef(company_id=prepared.company_id, resource_id=uuid4()),
        source_policy="native.generated.report.v1",
        recipe_version=prepared.recipe_version,
    )


@pytest.mark.parametrize("raw", [b"", b"\xff", b"nul\x00input", b"x" * 262145])
def test_payload_rejects_empty_unsupported_or_unbounded_bytes(raw: bytes) -> None:
    with pytest.raises(ValueError):
        payload(raw)


@pytest.mark.parametrize(
    "changed",
    [
        "hash",
        "company",
        "classification",
        "authority",
        "duplicate_resource",
        "duplicate_artifact",
        "duplicate_source",
    ],
)
def test_payload_rejects_tamper_foreign_scope_unknown_class_or_authority(changed: str) -> None:
    prepared = payload()
    data = prepared.model_dump()
    inputs = prepared.inputs
    if changed == "hash":
        data["output_sha256"] = "f" * 64
    elif changed == "company":
        data["inputs"] = inputs.model_copy(update={"company_id": uuid4()})
    elif changed == "classification":
        data["data_classification"] = "unknown"
    elif changed == "authority":
        data["owner_approved"] = True
    else:
        field = {
            "duplicate_resource": "required_resource_ids",
            "duplicate_artifact": "artifacts",
            "duplicate_source": "contributors",
        }[changed]
        data["inputs"] = inputs.model_copy(
            update={field: (*getattr(inputs, field), *getattr(inputs, field))}
        )
    with pytest.raises(ValueError):
        GeneratedArtifactPayload.model_validate(data)


def test_stable_company_action_ids_do_not_change_with_new_bytes_and_cannot_bind_self() -> None:
    prepared = payload()
    action_id = uuid4()
    original = generated_reference(prepared, action_id)
    assert generated_reference(prepared, action_id) == original
    alternate = prepared.model_copy(
        update={
            "raw_bytes": b"alt bytes",
            "output_sha256": hashlib.sha256(b"alt bytes").hexdigest(),
        }
    )
    changed = generated_reference(alternate, action_id)
    assert (
        changed.artifact_revision_id == original.artifact_revision_id
        and changed.sha256 != original.sha256
    )
    assert generated_reference(prepared, uuid4()).artifact_id != original.artifact_id
    assert generated_derivation_id(prepared.company_id, action_id) == generated_derivation_id(
        prepared.company_id, action_id
    )
    assert generated_derivation_id(uuid4(), action_id) != generated_derivation_id(
        prepared.company_id, action_id
    )
    circular = prepared.model_copy(
        update={"inputs": prepared.inputs.model_copy(update={"artifacts": (original,)})}
    )
    with pytest.raises(ValueError):
        generated_reference(circular, action_id)


@pytest.mark.parametrize(
    "changed",
    ["tool", "version", "resource", "recipe", "output", "input", "selector", "unknown_parameter"],
)
def test_native_action_payload_binding_requires_fixed_tool_hashes_and_exact_selector(
    changed: str,
) -> None:
    prepared = payload()
    declared = action(prepared)
    selected = rule(prepared)
    if changed in {"tool", "version", "resource"}:
        field = {"tool": "tool", "version": "tool_version", "resource": "resource"}[changed]
        declared = declared.model_copy(update={field: "unregistered"})
    else:
        parameters = dict(declared.parameters)
        key = {
            "recipe": "recipe_version",
            "output": "output_sha256",
            "input": "input_snapshot_sha256",
            "selector": "verification_target_sha256",
            "unknown_parameter": "verdict",
        }[changed]
        parameters[key] = "pass" if changed == "unknown_parameter" else "f" * 64
        declared = declared.model_copy(update={"parameters": parameters})
    with pytest.raises(ValueError):
        require_action_payload(declared, selected, prepared)


def test_exact_payload_and_action_roundtrip_are_descriptive_not_publication() -> None:
    prepared = payload()
    declared = action(prepared)
    selected = rule(prepared)
    assert GeneratedArtifactPayload.model_validate_json(prepared.model_dump_json()) == prepared
    parsed = require_action_payload(declared, selected, prepared)
    assert parsed.report_id is not None and parsed.verification_target_sha256 is None
    assert prepared.input_manifest_sha256 == prepared.input_manifest_sha256
    assert len(prepared.input_manifest_sha256) == 64


@pytest.mark.parametrize(
    "values",
    [{}, {"report_id": str(uuid4()), "verification_target_sha256": "a" * 64}, {"report_id": True}],
)
def test_parameters_cannot_omit_splice_or_coerce_native_selector(values: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        GeneratedArtifactActionParameters.model_validate(
            {
                "recipe_version": "native-internal-report-v1",
                "output_sha256": "a" * 64,
                "input_snapshot_sha256": "b" * 64,
                **values,
            }
        )


def test_check_target_requires_native_author_action_and_write_cannot_borrow_it() -> None:
    values: dict[str, object] = {
        "recipe_version": "internal-report-mechanical-v1",
        "output_sha256": "a" * 64,
        "input_snapshot_sha256": "b" * 64,
        "verification_target_sha256": "c" * 64,
    }
    with pytest.raises(ValueError):
        GeneratedArtifactActionParameters.model_validate(values)
    target = GeneratedArtifactActionParameters.model_validate(
        {**values, "author_action_id": uuid4()}
    )
    assert target.author_action_id is not None and target.report_id is None
    with pytest.raises(ValueError):
        GeneratedArtifactActionParameters.model_validate(
            {
                "recipe_version": "native-internal-report-v1",
                "output_sha256": "a" * 64,
                "input_snapshot_sha256": "b" * 64,
                "report_id": uuid4(),
                "author_action_id": uuid4(),
            }
        )


@pytest.mark.parametrize("kind", ["missing", "duplicate", "check_splice"])
def test_write_requires_durable_unique_evidence_and_check_cannot_borrow_it(kind: str) -> None:
    values: dict[str, object] = {
        "recipe_version": "native-report-render-v1",
        "output_sha256": "a" * 64,
        "input_snapshot_sha256": "b" * 64,
    }
    if kind == "check_splice":
        values.update(
            {
                "verification_target_sha256": "c" * 64,
                "author_action_id": str(uuid4()),
                "evidence_ids": [str(uuid4())],
            }
        )
    else:
        values["report_id"] = str(uuid4())
        if kind == "duplicate":
            key = str(uuid4())
            values["evidence_ids"] = [key, key]
    with pytest.raises(ValueError):
        GeneratedArtifactActionParameters.model_validate_json(json.dumps(values))

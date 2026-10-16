"""Private codec/marker data is not repository/source/effect authority."""

import json
from uuid import UUID

import pytest

from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.coding_prepared_contracts import (
    CodingPreparedHeader,
    decode_header,
    encode_prepared,
    header_for,
    header_reference,
    prepared_reference,
    require_body,
)
from nexus.harness.model_authorizer_contracts import model_action_parameters
from nexus.tests.unit.test_coding_intent import prepared_case


def encoded_case() -> tuple[CodingPreparedHeader, bytes, ActionProposal]:
    prepared, catalog, _, _ = prepared_case()
    body, body_ref = encode_prepared(prepared)
    admission = catalog.nexus_coding_admission
    assert admission is not None
    header = header_for(
        prepared,
        body_ref,
        owner_id=admission.procedure.binding.actor_id,
        registration_sha256="a" * 64,
        root_registration_sha256="b" * 64,
        root_task_id=admission.procedure.binding.task_id,
        root_run_id=admission.procedure.binding.run_id,
        procedure_id=admission.procedure.procedure_id,
    )
    reference, _ = header_reference(header)
    call = prepared.request
    proposal = ActionProposal(
        company_id=call.company_id,
        action_id=call.action_id,
        task_id=call.task_id,
        trace_id=call.trace_id,
        actor_id=call.actor_id,
        tool="model.request.v1",
        tool_version="v1",
        resource="model:" + call.registry_id,
        parameters=model_action_parameters(call, prepared.input_recipe),
        preconditions=(reference.condition,),
        estimated_cost_usd="0.1",
        price_version=call.price_version,
        policy_version=prepared.context.manifest.authority.policy_version,
        revision=1,
    )
    return header, body, proposal


def test_complete_private_body_and_small_prompt_free_header_bind_exact_native_marker() -> None:
    header, body, proposal = encoded_case()
    ref, metadata = header_reference(header)
    assert ref.condition.resource == f"coding.prepared:{proposal.action_id}"
    assert prepared_reference(proposal) == ref
    assert decode_header(metadata, ref) == header
    prepared = require_body(header, body)
    assert prepared.request.input_text.encode() not in metadata
    assert "input_text" not in json.loads(metadata)
    assert header.parameters.model_dump(mode="json") == proposal.parameters
    assert header.repository_source == prepared.binding.source
    assert header.context_manifest_sha256 == prepared.binding.context_manifest_sha256


@pytest.mark.parametrize("field", ["goal", "root", "selection", "body", "registry", "parameters"])
def test_header_and_body_splicing_denied(field: str) -> None:
    header, raw, _ = encoded_case()
    original_reference, _ = header_reference(header)
    if field == "goal":
        header = header.model_copy(
            update={"goal": header.goal.model_copy(update={"revision_id": UUID(int=999)})}
        )
    elif field == "root":
        header = header.model_copy(update={"root_task_id": UUID(int=999)})
        # Root identity is an actual-native check; its approved metadata hash cannot change.
        with pytest.raises(ValueError):
            decode_header(header_reference(header)[1], original_reference)
        return
    elif field == "selection":
        header = header.model_copy(update={"repository_selection_sha256": "f" * 64})
    elif field == "body":
        raw = raw.replace(b"old", b"bad", 1)
    elif field == "registry":
        header = header.model_copy(update={"registry_sha256": "f" * 64})
    else:
        header = header.model_copy(
            update={"parameters": header.parameters.model_copy(update={"request_hash": "f" * 64})}
        )
    with pytest.raises(ValueError):
        require_body(header, raw)


@pytest.mark.parametrize(
    "kind", ["legacy", "foreign", "duplicate", "unknown-revision", "extra-field"]
)
def test_native_marker_must_be_exact_single_coding_action_bound_reference(kind: str) -> None:
    _, _, proposal = encoded_case()
    marker = proposal.preconditions[0]
    if kind == "legacy":
        marker = marker.model_copy(
            update={"resource": marker.resource.replace("coding.prepared:", "planning.prepared:")}
        )
    elif kind == "foreign":
        marker = marker.model_copy(update={"resource": "coding.prepared:" + str(UUID(int=999))})
    elif kind == "duplicate":
        proposal = proposal.model_copy(update={"preconditions": (marker, marker)})
    elif kind == "unknown-revision":
        marker = marker.model_copy(update={"revision": marker.revision + ":grant:true"})
    else:
        proposal = proposal.model_copy(
            update={"parameters": proposal.parameters | {"approved": True}}
        )
    if kind != "duplicate":
        proposal = proposal.model_copy(update={"preconditions": (marker,)})
    with pytest.raises(ValueError):
        prepared_reference(proposal)

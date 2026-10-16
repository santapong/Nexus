"""Exact private preparation bytes and public hash-only precondition composition."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from nexus.company.brain.model_context_check import _require_preconditions
from nexus.company.contracts.actions import ActionProposal, ApprovalDecision, ResourceRevision
from nexus.company.management.planning_intent import (
    PreparedPlanningRequest,
    prepare_planning_request,
)
from nexus.company.management.planning_prepared_contracts import (
    descriptor_for,
    descriptor_reference,
    encode_prepared,
    prepared_reference,
    require_body,
)
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.harness.approvals import ApprovalContext, require_exact_approval
from nexus.harness.canonical import action_hash
from nexus.harness.model_authorizer_contracts import model_action_parameters
from nexus.tests.unit.test_company_planning_intent import prepared_inputs


def fixture() -> tuple[PreparedPlanningRequest, ExecutionLease]:
    call, context, binding, scope, recipe, lease = prepared_inputs()
    prepared = prepare_planning_request(call, context, binding, scope=scope, input_recipe=recipe)
    return prepared, lease


def test_complete_alias_correct_body_and_descriptor_are_bound_without_plaintext_params() -> None:
    prepared, lease = fixture()
    raw, body = encode_prepared(prepared)
    header = descriptor_for(
        prepared, body, run_id=lease.run_id, registration_sha256="a" * 64, owner_id=UUID(int=99)
    )
    reference, metadata = descriptor_reference(header)
    assert prepared.context.input_text.encode() not in metadata
    assert prepared.context.system_text.encode() not in metadata
    assert require_body(header, raw) == prepared
    proposal = ActionProposal(
        company_id=prepared.request.company_id,
        action_id=prepared.request.action_id,
        task_id=prepared.request.task_id,
        trace_id=prepared.request.trace_id,
        actor_id=prepared.request.actor_id,
        revision=1,
        tool="model.request.v1",
        tool_version="v1",
        resource=f"model:{prepared.request.registry_id}",
        parameters=model_action_parameters(prepared.request, prepared.input_recipe),
        preconditions=(reference.condition,),
        policy_version="v1",
        price_version=prepared.request.price_version,
        estimated_cost_usd="0.01",
    )
    assert prepared_reference(proposal) == reference
    assert len(proposal.parameters) == 9
    # Brain exactness is unchanged; native approval also requires the store-verified marker.
    brain = ResourceRevision(resource="brain.resource:actual", revision="acl:1")
    proposal = proposal.model_copy(update={"preconditions": (brain, reference.condition)})
    _require_preconditions(proposal, (brain,))
    now = datetime.now(UTC)
    decision = ApprovalDecision(
        company_id=proposal.company_id,
        decision_id=UUID(int=123),
        action_id=proposal.action_id,
        action_revision=proposal.revision,
        action_hash=action_hash(proposal),
        approver_id=UUID(int=99),
        decision="approved",
        issued_at=now,
        expires_at=now + timedelta(minutes=1),
    )
    current = ApprovalContext(
        company_id=proposal.company_id,
        owner_id=decision.approver_id,
        actor_id=proposal.actor_id,
        now=now,
        policy_version=proposal.policy_version,
        price_version=proposal.price_version,
        paused=False,
        resources=(brain, reference.condition),
    )
    require_exact_approval(proposal, decision, current)
    with pytest.raises(ValueError):
        require_exact_approval(
            proposal, decision, current.model_copy(update={"resources": (brain,)})
        )
    with pytest.raises(ValueError):
        prepared_reference(
            proposal.model_copy(
                update={
                    "preconditions": (
                        brain,
                        reference.condition.model_copy(
                            update={
                                "revision": reference.condition.revision.replace(
                                    ":bytes:", ":bytes:0"
                                )
                            }
                        ),
                    )
                }
            )
        )
    with pytest.raises(ValueError):
        prepared_reference(proposal.model_copy(update={"preconditions": ()}))
    with pytest.raises(ValueError):
        require_body(header, raw + b" ")


def test_changed_scope_reference_and_body_cannot_reuse_the_same_private_preparation() -> None:
    prepared, lease = fixture()
    raw, body = encode_prepared(prepared)
    header = descriptor_for(
        prepared, body, run_id=lease.run_id, registration_sha256="a" * 64, owner_id=UUID(int=99)
    )
    altered = header.model_copy(update={"registration_sha256": "b" * 64})
    assert descriptor_reference(header)[0] != descriptor_reference(altered)[0]
    with pytest.raises(ValueError):
        require_body(header.model_copy(update={"request_sha256": "f" * 64}), raw)

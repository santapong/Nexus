"""Strict declarations do not confer owner, independent acceptance, delivery or effect authority."""

from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.acceptance import VerificationSpec, WorkAcceptance
from nexus.company.notifications.contracts import (
    CurrentWorkAcceptance,
    NativeNotificationSignal,
    NotificationPolicy,
)
from nexus.company.notifications.policy import signal_admission
from nexus.company.notifications.proposals import (
    NOTIFICATION_TOOL,
    NotificationDispatchParameters,
    NotificationProposal,
)
from nexus.tests.notification_acceptance_fixture import declared_acceptance
from nexus.tests.notification_rule_fixtures import COMPANY, OWNER, declared_draft


def test_major_work_notification_uses_exact_separate_native_acceptance_shape() -> None:
    draft = declared_draft()
    accepted = declared_acceptance()
    signal = NativeNotificationSignal.model_validate(
        draft.signal.model_dump() | {"kind": "work_accepted", "acceptance": accepted}
    )
    assert signal_admission(NotificationPolicy(enabled=True), signal).reason == "minor_completion"
    policy = NotificationPolicy(enabled=True, major_completion_task_ids=(signal.subject_id,))
    assert signal_admission(policy, signal).state == "eligible"
    with pytest.raises(ValidationError):
        NativeNotificationSignal.model_validate(signal.model_dump() | {"subject_id": UUID(int=99)})
    with pytest.raises(ValidationError):
        NativeNotificationSignal.model_validate(signal.model_dump() | {"kind": "candidate"})


def test_candidate_self_verification_and_nonpassing_shape_cannot_be_accepted_projection() -> None:
    acceptance = declared_acceptance().acceptance
    for verdict in ("reject", "inconclusive"):
        changed = acceptance.model_copy(update={"verdict": verdict})
        with pytest.raises(ValidationError):
            CurrentWorkAcceptance(company_id=COMPANY, acceptance=changed)
    with pytest.raises(ValidationError):
        WorkAcceptance.model_validate(acceptance.model_dump() | {"proofs": ()})
    with pytest.raises(ValidationError):
        VerificationSpec.model_validate(
            acceptance.target.model_dump() | {"verifier": acceptance.target.author}
        )


def declared_proposal() -> NotificationProposal:
    draft = declared_draft()
    params = NotificationDispatchParameters(
        draft_id=draft.draft_id,
        payload_sha256=draft.payload_sha256,
        recipient_policy_sha256=draft.recipient_policy.sha256,
    )
    action = ActionProposal(
        company_id=COMPANY,
        action_id=UUID(int=40),
        task_id=UUID(int=20),
        trace_id=UUID(int=21),
        actor_id=OWNER,
        revision=1,
        tool=NOTIFICATION_TOOL,
        tool_version="v1",
        resource="owner.notification",
        parameters=params.model_dump(mode="json"),
        policy_version="fixture-policy.v1",
        price_version="fixture-price.v1",
        estimated_cost_usd=Decimal("0.01"),
    )
    return NotificationProposal(
        company_id=COMPANY,
        draft_id=draft.draft_id,
        payload_sha256=draft.payload_sha256,
        recipient_policy_sha256=draft.recipient_policy.sha256,
        action=action,
    )


def test_proposal_accepts_only_exact_native_draft_parameters() -> None:
    proposal = declared_proposal()
    assert proposal.action.tool == NOTIFICATION_TOOL
    for params in (
        proposal.action.parameters | {"recipient": "other@example.invalid"},
        proposal.action.parameters | {"approved": True},
        proposal.action.parameters | {"payload_sha256": "f" * 64},
    ):
        action = proposal.action.model_copy(update={"parameters": params})
        with pytest.raises(ValidationError):
            NotificationProposal.model_validate(proposal.model_dump() | {"action": action})

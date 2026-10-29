"""The native loop selects exact journal facts; matching pins do not grant approval."""

from decimal import Decimal
from typing import Literal
from uuid import uuid4

import pytest

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.commitment_contracts import CommitmentRevisionRef
from nexus.company.management.generated_artifact_contracts import (
    GeneratedArtifactActionParameters,
    GeneratedArtifactRule,
)
from nexus.company.management.native_loop_actions import require_loop_action
from nexus.company.management.native_loop_contracts import NativeOperatingRegistration
from nexus.company.management.native_profile_contracts import NativeReportProfileRef
from nexus.company.management.transactions import ManagementDeniedError
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.canonical import action_hash
from nexus.harness.journal_contracts import ActionRecord
from nexus.harness.lifecycle import ActionState

# TASK: Check exact saved-report/action binding before native loop authorization.
# FILES TO CREATE: nexus/tests/unit/test_native_loop_action_pins.py
# TESTS: Both phases, identity/tool/hash tampering, changed report/evidence/author.
# DONE: Focused tests verify selection only, without claiming execution authority.
# RISK: Low; no runtime changes or network/database access.


def case(
    phase: Literal["author", "verifier"],
) -> tuple[NativeOperatingRegistration, ExecutionWork, ActionRecord, GeneratedArtifactRule]:
    company, report, evidence = uuid4(), uuid4(), uuid4()
    profile = NativeReportProfileRef(
        company_id=company,
        report_id=report,
        report_sha256="a" * 64,
        selection_sha256="b" * 64,
        commitment=CommitmentRevisionRef(
            company_id=company,
            commitment_id=uuid4(),
            revision_id=uuid4(),
            version="v1",
            sha256="c" * 64,
        ),
        evidence_ids=(evidence,),
    )
    registration = NativeOperatingRegistration(
        company_id=company, registration_id=uuid4(), profile=profile
    )
    work = ExecutionWork(company_id=company, task_id=uuid4(), trace_id=uuid4(), actor_id=uuid4())
    parameters = GeneratedArtifactActionParameters(
        recipe_version="native-report-v1",
        output_sha256="d" * 64,
        input_snapshot_sha256="e" * 64,
        report_id=report if phase == "author" else None,
        evidence_ids=(evidence,) if phase == "author" else (),
        verification_target_sha256="f" * 64 if phase == "verifier" else None,
        author_action_id=registration.action_id("author") if phase == "verifier" else None,
    )
    tool: Literal["company.report.write.v1", "company.report.check.v1"] = (
        "company.report.write.v1" if phase == "author" else "company.report.check.v1"
    )
    rule = GeneratedArtifactRule(
        company_id=company,
        tool=tool,
        resource_symbol="company.report.output",
        target=ResourceRef(company_id=company, resource_id=uuid4()),
        source_policy="company.report.v1",
        recipe_version="native-report-v1",
    )
    proposal = ActionProposal(
        company_id=company,
        action_id=registration.action_id(phase),
        task_id=work.task_id,
        trace_id=work.trace_id,
        actor_id=work.actor_id,
        revision=1,
        tool=tool,
        tool_version="v1",
        resource=rule.resource_symbol,
        parameters=parameters.model_dump(mode="json", exclude_none=True),
        policy_version="policy-v1",
        price_version="price-v1",
        estimated_cost_usd=Decimal("0"),
    )
    record = ActionRecord(
        company_id=company,
        proposal=proposal,
        proposal_hash=action_hash(proposal),
        approval=None,
        state=ActionState.AWAITING_APPROVAL,
        consumed_at=None,
    )
    return registration, work, record, rule


@pytest.mark.parametrize("phase", ["author", "verifier"])
def test_exact_phase_pins_are_accepted_without_making_an_owner_decision(
    phase: Literal["author", "verifier"],
) -> None:
    registration, work, record, rule = case(phase)
    assert record.approval is None
    require_loop_action(registration, work, phase, record, rule)
    assert record.approval is None and record.consumed_at is None


@pytest.mark.parametrize(
    "field",
    [
        "company_id",
        "task_id",
        "trace_id",
        "actor_id",
        "action_id",
        "tool",
        "tool_version",
        "resource",
    ],
)
def test_author_rejects_rehashed_action_from_different_exact_identity_or_tool(field: str) -> None:
    registration, work, record, rule = case("author")
    value = "other" if field in {"tool", "tool_version", "resource"} else uuid4()
    proposal = record.proposal.model_copy(update={field: value})
    changed = record.model_copy(
        update={"proposal": proposal, "proposal_hash": action_hash(proposal)}
    )
    with pytest.raises(ManagementDeniedError, match="exact native pins"):
        require_loop_action(registration, work, "author", changed, rule)


def test_author_rejects_proposal_tampering_when_journal_hash_is_unchanged() -> None:
    registration, work, record, rule = case("author")
    changed = record.model_copy(
        update={"proposal": record.proposal.model_copy(update={"revision": 2})}
    )
    with pytest.raises(ManagementDeniedError, match="exact native pins"):
        require_loop_action(registration, work, "author", changed, rule)


@pytest.mark.parametrize("selector", ["recipe_version", "report_id", "evidence_ids"])
def test_author_rejects_rehashed_changed_saved_report_selector(selector: str) -> None:
    registration, work, record, rule = case("author")
    parameters = dict(record.proposal.parameters)
    if selector == "recipe_version":
        parameters[selector] = "other-recipe-v1"
    elif selector == "report_id":
        parameters[selector] = str(uuid4())
    else:
        parameters[selector] = [str(uuid4())]
    proposal = record.proposal.model_copy(update={"parameters": parameters})
    changed = record.model_copy(
        update={"proposal": proposal, "proposal_hash": action_hash(proposal)}
    )
    with pytest.raises(ManagementDeniedError):
        require_loop_action(registration, work, "author", changed, rule)


def test_verifier_rejects_a_rehashed_reference_to_another_author() -> None:
    registration, work, record, rule = case("verifier")
    parameters = dict(record.proposal.parameters)
    parameters["author_action_id"] = str(uuid4())
    proposal = record.proposal.model_copy(update={"parameters": parameters})
    changed = record.model_copy(
        update={"proposal": proposal, "proposal_hash": action_hash(proposal)}
    )
    with pytest.raises(ManagementDeniedError, match="another actual author"):
        require_loop_action(registration, work, "verifier", changed, rule)

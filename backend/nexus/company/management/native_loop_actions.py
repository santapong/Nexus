"""Exact native journal pins bind the fixed saved occurrence before any scheduling read."""

import json
from typing import Literal

from nexus.company.management.generated_artifact_contracts import (
    GeneratedArtifactActionParameters,
    GeneratedArtifactRule,
)
from nexus.company.management.native_loop_contracts import NativeOperatingRegistration
from nexus.company.management.transactions import ManagementDeniedError
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.canonical import action_hash
from nexus.harness.journal_contracts import ActionRecord


def require_loop_action(
    registration: NativeOperatingRegistration,
    work: ExecutionWork,
    phase: Literal["author", "verifier"],
    record: ActionRecord,
    rule: GeneratedArtifactRule,
) -> None:
    """Read exact native selectors; neither an action UUID nor decoded hash is approval."""
    proposal = record.proposal
    if (
        (
            record.company_id,
            proposal.company_id,
            proposal.task_id,
            proposal.trace_id,
            proposal.actor_id,
        )
        != (work.company_id, work.company_id, work.task_id, work.trace_id, work.actor_id)
        or proposal.action_id != registration.action_id(phase)
        or action_hash(proposal) != record.proposal_hash
        or (proposal.tool, proposal.tool_version, proposal.resource)
        != (rule.tool, rule.tool_version, rule.resource_symbol)
    ):
        raise ManagementDeniedError("Registered loop action differs from its exact native pins")
    pins = GeneratedArtifactActionParameters.model_validate_json(json.dumps(proposal.parameters))
    if pins.recipe_version != rule.recipe_version:
        raise ManagementDeniedError("Registered loop action recipe differs")
    if phase == "author":
        if (
            pins.report_id != registration.profile.report_id
            or pins.evidence_ids != registration.profile.evidence_ids
        ):
            raise ManagementDeniedError("Registered loop author differs from exact saved report")
    elif pins.author_action_id != registration.action_id("author"):
        raise ManagementDeniedError("Registered loop verifier selects another actual author action")

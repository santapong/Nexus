"""Queue-only exact native planning history, with no protected body or fresh execution authority."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast
from uuid import uuid5

from sqlalchemy import text

from nexus.company.management.planning_prepared_contracts import (
    PlanningModelParameters,
)
from nexus.company.management.scheduling_queue import BINDING
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.effect_support import effect_record
from nexus.execution.model_workflow_identity import (
    require_current_model_binding,
    require_issued_model_binding,
)
from nexus.execution.planning_services import (
    REGISTRATION,
    VERSION,
    WORKFLOW,
    PlanningServices,
)
from nexus.execution.runtime_contracts import EffectRecord
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.execution.runtime_recovery import dispatched_binding
from nexus.execution.runtime_support import (
    snapshot,
)
from nexus.harness.canonical import action_hash
from nexus.harness.journal import CompanyJournal, _control
from nexus.harness.journal_budget import billing_day
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import CostHold, JournalAction
from nexus.harness.journal_submission import pending_action_record
from nexus.harness.model_authorizer_contracts import model_action_recipe_hash


@dataclass(frozen=True)
class NativePlanningHistory:
    """Private native observation only; caller DTOs never populate the production reader."""

    effect: EffectRecord | None
    request_sha256: str


def require_workflow_binding(command: SegmentCommand, row: Mapping[str, object] | None) -> None:
    """Current unissued metadata requires the distinct application deployment version."""
    require_current_model_binding(command, row, REGISTRATION)


async def native_history(
    services: PlanningServices, command: SegmentCommand
) -> NativePlanningHistory:
    """Queue-only metadata before credential/body/lease; exact dispatch is required."""
    services.require_composition()
    if command.company_id != services.management.catalog.company_id:
        raise ValueError("Planning history belongs to another configured company")
    scope = LedgerScope(
        company_id=command.company_id,
        principal_id=command.actor_id,
        task_id=command.task_id,
        trace_id=command.trace_id,
    )
    async with CompanyJournal(services.factory)._session(scope) as session:
        control = await _control(session, scope)  # Company-first consistent native observation.
        work = await session.get(ExecutionWork, (command.company_id, command.task_id))
        row = await session.get(JournalAction, command.action_id)
        if work is None or row is None:
            raise ValueError("Planning worker lacks actual work/action history")
        actual = await dispatched_binding(session, work, scope, command.segment_id)
        queue = (
            (
                await session.execute(
                    text(BINDING.text.replace("FOR UPDATE OF ws", "")),
                    {"workflow_id": command.workflow_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        record = pending_action_record(row)
        proposal = record.proposal
        parameters = PlanningModelParameters.model_validate_json(json.dumps(proposal.parameters))
        if (
            actual != command
            or (work.workflow_name, work.workflow_version) != (WORKFLOW, VERSION)
            or (proposal.company_id, proposal.task_id, proposal.trace_id, proposal.actor_id)
            != (command.company_id, command.task_id, command.trace_id, command.actor_id)
            or (proposal.tool, proposal.tool_version, proposal.resource)
            != ("model.request.v1", "v1", f"model:{parameters.registry_id}")
            or row.state != "authorized"
            or row.consumed_at is None
            or record.proposal_hash != action_hash(proposal)
            or (
                parameters.registry_id,
                parameters.registry_revision,
                parameters.price_version,
                parameters.input_recipe_id,
                parameters.input_recipe_revision,
                parameters.input_recipe_hash,
            )
            != (
                services.registry_id,
                services.management.catalog.models.revision,
                services.management.catalog.models.pricebook_version,
                services.recipe.recipe_id,
                services.recipe.revision,
                model_action_recipe_hash(services.recipe),
            )
            or work.model_registry_version != parameters.registry_revision
            or work.model_profile != services.recipe.profile
        ):
            raise ValueError("Planning native dispatch/action binding differs")
        saved = await session.get(EffectIntent, (command.company_id, command.action_id))
        if saved is None:
            require_workflow_binding(command, cast(Mapping[str, object] | None, queue))
            return NativePlanningHistory(None, parameters.request_hash)
        effect = effect_record(saved)
        hold = await session.get(CostHold, command.action_id)
        if (
            (
                effect.task_id,
                effect.trace_id,
                effect.run_id,
                effect.proposal_hash,
                effect.attempt_kind,
            )
            != (
                command.task_id,
                command.trace_id,
                command.run_id,
                record.proposal_hash,
                "model_requests",
            )
            or effect.intent_fence > work.fence
            or effect.verification is not None
            or snapshot(work).counters.model_requests < 1
            or hold is None
            or (hold.company_id, hold.task_id, hold.action_id, hold.amount_usd, hold.day)
            != (
                command.company_id,
                command.task_id,
                command.action_id,
                proposal.estimated_cost_usd,
                billing_day(effect.created_at),
            )
        ):
            raise ValueError("Planning issued history or conserved hold differs")
        receipt = effect.receipt
        if effect.state in {"succeeded", "failed"}:
            if (
                receipt is None
                or receipt.outcome != effect.state
                or hold.state != "reconciled"
                or hold.actual_usd is None
                or len(receipt.artifacts) != 1
                or (
                    receipt.company_id,
                    receipt.action_id,
                    receipt.task_id,
                    receipt.trace_id,
                    receipt.proposal_hash,
                    receipt.receipt_id,
                )
                != (
                    command.company_id,
                    command.action_id,
                    command.task_id,
                    command.trace_id,
                    effect.proposal_hash,
                    uuid5(command.action_id, "model-receipt-v1"),
                )
            ):
                raise ValueError("Planning known native receipt is incomplete or foreign")
            artifact = receipt.artifacts[0]
            if (
                artifact.company_id,
                artifact.artifact_id,
                artifact.revision,
                artifact.allowed_principals,
            ) != (
                command.company_id,
                uuid5(command.action_id, str(parameters.request_id)),
                "model-result-envelope-v1",
                (command.actor_id, control.owner_id),
            ):
                raise ValueError("Planning known artifact metadata differs from original request")
        elif (
            effect.state not in {"intent", "outcome_unknown"}
            or receipt is not None
            or hold.actual_usd is not None
            or hold.state not in {"held", "unknown"}
        ):
            raise ValueError("Planning unknown history cannot assert a known receipt or charge")
        require_issued_model_binding(
            command,
            cast(Mapping[str, object] | None, queue),
            REGISTRATION,
            effect,
            record.proposal_hash,
        )
    services.require_composition()
    return NativePlanningHistory(effect, parameters.request_hash)

"""Current READ of original Nexus report intent facts, without credentials, claims or retry."""

from sqlalchemy import func, select

from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.report_inputs import native_author
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.dispatch_models import SegmentDispatch
from nexus.execution.effect_support import effect_record
from nexus.execution.native_report_contracts import NativeReportResult
from nexus.execution.native_report_services import NativeReportServices
from nexus.execution.runtime_contracts import ExecutionDeniedError
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.execution.runtime_support import runtime_transaction, snapshot
from nexus.harness.canonical import action_hash
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import JournalAction


async def read_nexus_report_history(
    services: NativeReportServices, command: SegmentCommand
) -> NativeReportResult | None:
    if services.publisher.catalog.nexus_cycle_admission is None:
        return None
    async with services.factory() as session, session.begin():
        await session.execute(
            select(func.set_config("nexus.company_id", str(command.company_id), True))
        )
        row = await session.get(ExecutionWork, (command.company_id, command.task_id))
        dispatch = await session.get(SegmentDispatch, (command.company_id, command.action_id))
        if (
            row is None
            or dispatch is None
            or dispatch.binding_json != command.model_dump_json()
            or dispatch.workflow_id != command.workflow_id
        ):
            raise ExecutionDeniedError("Nexus report actual historical dispatch is unavailable")
        binding, _ = native_author(row)
        signed = services.identities.actor(binding)
    scope = LedgerScope(
        company_id=command.company_id,
        task_id=command.task_id,
        trace_id=command.trace_id,
        principal_id=signed.principal_id,
    )
    command.require_scope(scope)
    async with runtime_transaction(
        services.factory, scope, signed, allow_paused=True, allow_inactive=True
    ) as (session, _, _):
        actual = await session.get(ExecutionWork, (command.company_id, command.task_id))
        intent = await session.get(EffectIntent, (command.company_id, command.action_id))
        if (
            actual is None
            or native_author(actual)[0] != binding
            or snapshot(actual).registration.run_id != command.run_id
        ):
            raise ExecutionDeniedError("Nexus report actual history work differs")
        if intent is None:
            return None
        action = await session.get(JournalAction, command.action_id)
        if action is None:
            raise ExecutionDeniedError("Nexus report original action is unavailable")
        proposal = ActionProposal.model_validate_json(action.proposal_json)
        record = effect_record(intent)
        if (
            record.company_id,
            record.action_id,
            record.task_id,
            record.trace_id,
            record.run_id,
            record.proposal_hash,
            record.attempt_kind,
        ) != (
            command.company_id,
            command.action_id,
            command.task_id,
            command.trace_id,
            command.run_id,
            action_hash(proposal),
            "tool_attempts",
        ) or (
            proposal.actor_id != signed.principal_id or action.proposal_hash != record.proposal_hash
        ):
            raise ExecutionDeniedError("Nexus report original issuance differs")
        receipt = record.receipt
        if receipt is None or receipt.outcome != "succeeded" or record.state != "succeeded":
            return NativeReportResult(
                company_id=command.company_id,
                task_id=command.task_id,
                action_id=command.action_id,
                segment_id=command.segment_id,
                status="outcome_unknown",
                receipt_id=receipt.receipt_id if receipt else None,
                limitations=("known_issued_history", "no_new_call", "reconciliation_unproven"),
            )
        if (
            receipt.company_id,
            receipt.action_id,
            receipt.task_id,
            receipt.trace_id,
            receipt.proposal_hash,
        ) != (
            record.company_id,
            record.action_id,
            record.task_id,
            record.trace_id,
            record.proposal_hash,
        ):
            raise ExecutionDeniedError("Nexus report original receipt differs")
        # Historical publication is distinct from current protected availability/acceptance.
        return NativeReportResult(
            company_id=command.company_id,
            task_id=command.task_id,
            action_id=command.action_id,
            segment_id=command.segment_id,
            status="published",
            receipt_id=receipt.receipt_id,
            limitations=("known_issued_history", "current_acceptance_unproven", "no_new_call"),
        )

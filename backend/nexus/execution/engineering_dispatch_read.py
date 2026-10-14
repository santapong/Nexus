"""Company-first locked current engineering dispatch read; no lease or effect is issued."""

import json

from sqlalchemy import func, select

from nexus.builder.execution_contracts import BuilderExecutionSpec
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plans import RunBinding
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.dispatch_models import SegmentDispatch
from nexus.execution.engineering_worker_contracts import EngineeringPhase
from nexus.execution.engineering_worker_services import EngineeringWorkerServices
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CompanyControl, JournalAction


async def read_engineering_dispatch(
    services: EngineeringWorkerServices, command: SegmentCommand, workflow_id: str
) -> tuple[RunBinding, EngineeringPhase, ActionProposal, BuilderExecutionSpec]:
    """Atomic native identity read is intentionally cohesive; no external provider I/O occurs."""
    async with services.factory() as session, session.begin():
        await session.execute(
            select(func.set_config("nexus.company_id", str(command.company_id), True))
        )
        control = await session.scalar(
            select(CompanyControl)
            .where(CompanyControl.company_id == command.company_id)
            .with_for_update()
        )
        work = await session.get(ExecutionWork, (command.company_id, command.task_id))
        dispatch = await session.get(SegmentDispatch, (command.company_id, command.action_id))
        current = await ManagementPlanStore.current_binding(
            session, command.company_id, command.task_id
        )
        action_row = await session.get(JournalAction, command.action_id)
        if (
            control is None
            or work is None
            or dispatch is None
            or current is None
            or action_row is None
        ):
            raise ValueError("Engineering current dispatch records are unavailable")
        if (
            dispatch.binding_json != command.model_dump_json()
            or dispatch.workflow_id != workflow_id
        ):
            raise ValueError("Engineering dispatched command differs")
        binding = current.child.binding
        phase = engineering_phase(binding)
        action = ActionProposal.model_validate_json(action_row.proposal_json)
        spec = BuilderExecutionSpec.model_validate_json(json.dumps(action.parameters))
        services.runner.require_execution_policy(spec)
        if action_hash(action) != action_row.proposal_hash:
            raise ValueError("Engineering exact action checksum differs")
        require_command_binding(binding, action, command)
    return binding, phase, action, spec


def require_command_binding(
    binding: RunBinding, action: ActionProposal, command: SegmentCommand
) -> None:
    """Whole actual plan/action identity must match the immutable queued command."""
    if (
        binding.company_id,
        binding.task_id,
        binding.trace_id,
        binding.actor_id,
        binding.workspace_id,
        binding.run_id,
    ) != (
        command.company_id,
        command.task_id,
        command.trace_id,
        command.actor_id,
        command.workspace_id,
        command.run_id,
    ) or (
        action.company_id,
        action.task_id,
        action.trace_id,
        action.actor_id,
        action.action_id,
    ) != (
        command.company_id,
        command.task_id,
        command.trace_id,
        command.actor_id,
        command.action_id,
    ):
        raise ValueError("Engineering action and current binding differ from dispatch")


def engineering_phase(binding: RunBinding) -> EngineeringPhase:
    """Only the closed actual registered workflow/profile pair determines phase."""
    phase: EngineeringPhase = (
        "author" if binding.workflow_name == "engineering.change" else "verifier"
    )
    expected = (
        ("engineering.change", "engineering.native.v1")
        if phase == "author"
        else ("engineering.verify", "verification.native.v1")
    )
    if (
        binding.workflow_name,
        binding.model_profile,
    ) != expected or binding.workflow_version != "v1":
        raise ValueError("Engineering workflow/profile is not the closed native registration")
    return phase

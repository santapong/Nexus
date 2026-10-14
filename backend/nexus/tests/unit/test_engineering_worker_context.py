"""Closed phase and exact command identity are checked before any worker lease acquisition."""

from decimal import Decimal
from uuid import uuid4

import pytest

from nexus.company.contracts.actions import ActionProposal
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.engineering_dispatch_read import engineering_phase, require_command_binding
from nexus.tests.engineering_check_support import check_input


@pytest.mark.parametrize("phase,index", [("author", 0), ("verifier", 1)])
def test_current_registered_phase_and_command_binding(phase: str, index: int) -> None:
    value = check_input()
    binding = (value.target.author, value.target.verifier)[index]
    spec = (value.author, value.verifier)[index].spec
    command = SegmentCommand(
        company_id=binding.company_id,
        task_id=binding.task_id,
        trace_id=binding.trace_id,
        actor_id=binding.actor_id,
        workspace_id=binding.workspace_id,
        run_id=binding.run_id,
        action_id=spec.job.action_id,
        segment_id=uuid4(),
    )
    action = ActionProposal(
        company_id=command.company_id,
        task_id=command.task_id,
        trace_id=command.trace_id,
        actor_id=command.actor_id,
        action_id=command.action_id,
        revision=1,
        tool="company.builder.run.v1",
        tool_version="v1",
        resource="engineering.output",
        parameters=spec.model_dump(mode="json"),
        policy_version="fixture",
        price_version="fixture",
        estimated_cost_usd=Decimal("0.01"),
    )
    assert engineering_phase(binding) == phase
    require_command_binding(binding, action, command)
    for field in ("company_id", "task_id", "trace_id", "actor_id", "workspace_id", "run_id"):
        with pytest.raises(ValueError):
            require_command_binding(binding, action, command.model_copy(update={field: uuid4()}))
    with pytest.raises(ValueError):
        require_command_binding(binding, action, command.model_copy(update={"action_id": uuid4()}))
    for field in ("workflow_name", "workflow_version", "model_profile"):
        with pytest.raises(ValueError):
            engineering_phase(binding.model_copy(update={field: "unsupported"}))

"""Stable, non-authorizing portable scheduling commands."""

from uuid import UUID

import pytest
from pydantic import ValidationError

from nexus.execution.dbos_contracts import SegmentCommand
from nexus.harness.journal_contracts import LedgerScope


def command() -> SegmentCommand:
    return SegmentCommand(
        company_id=UUID(int=1),
        task_id=UUID(int=2),
        trace_id=UUID(int=3),
        actor_id=UUID(int=4),
        workspace_id=UUID(int=5),
        run_id=UUID(int=6),
        action_id=UUID(int=7),
        segment_id=UUID(int=8),
    )


def test_portable_command_retains_stable_segment_identity() -> None:
    value = command()
    restored = SegmentCommand.model_validate_json(value.model_dump_json())
    assert restored == value
    assert restored.workflow_id == value.workflow_id
    assert restored.model_copy(update={"segment_id": UUID(int=9)}).workflow_id != value.workflow_id


def test_scheduling_command_cannot_supply_new_limits_or_workflow_names() -> None:
    for key in ("model_requests", "budget_usd", "workflow_id", "workflow_name", "queue"):
        with pytest.raises(ValidationError):
            SegmentCommand.model_validate(command().model_dump() | {key: "override"})


@pytest.mark.parametrize("key", ["company_id", "task_id", "trace_id", "principal_id"])
def test_command_must_match_the_trusted_actor_scope(key: str) -> None:
    value = command()
    data = {
        "company_id": value.company_id,
        "task_id": value.task_id,
        "trace_id": value.trace_id,
        "principal_id": value.actor_id,
    }
    data[key] = UUID(int=99)
    with pytest.raises(ValueError, match="scope"):
        value.require_scope(LedgerScope.model_validate(data))

"""Full registered notification command and parameters precede any durable lease/effect."""

from __future__ import annotations

from uuid import UUID

import pytest

from nexus.company.contracts.actions import ActionProposal
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.notification_dispatch_read import require_notification_command
from nexus.tests.unit.test_company_notification_contracts import declared_proposal
from nexus.tests.unit.test_company_notification_worker_config import registration


def native_command() -> SegmentCommand:
    bound = registration().sender
    return SegmentCommand(
        company_id=bound.company_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        actor_id=bound.actor_id,
        workspace_id=bound.workspace_id,
        run_id=bound.run_id,
        action_id=UUID(int=880),
        segment_id=UUID(int=881),
    )


def notification_action() -> ActionProposal:
    command = native_command()
    return declared_proposal().action.model_copy(
        update={
            "company_id": command.company_id,
            "task_id": command.task_id,
            "trace_id": command.trace_id,
            "actor_id": command.actor_id,
            "action_id": command.action_id,
        }
    )


def test_full_native_command_returns_only_strict_saved_draft_parameters() -> None:
    params = require_notification_command(
        registration().sender,
        notification_action(),
        native_command(),
        "owner.notification",
    )
    assert params.draft_id == UUID(int=30)


@pytest.mark.parametrize(
    "field",
    ["company_id", "task_id", "trace_id", "actor_id", "workspace_id", "run_id", "action_id"],
)
def test_foreign_command_component_cannot_select_a_draft_or_grant_a_lease(field: str) -> None:
    with pytest.raises(ValueError):
        require_notification_command(
            registration().sender,
            notification_action(),
            native_command().model_copy(update={field: UUID(int=999)}),
            "owner.notification",
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"workflow_name": "internal.report"},
        {"workflow_version": "v2"},
        {"model_profile": "ordinary"},
    ],
)
def test_other_registered_workflow_or_profile_is_not_a_notification_procedure(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        require_notification_command(
            registration().sender.model_copy(update=changes),
            notification_action(),
            native_command(),
            "owner.notification",
        )


def test_saved_extra_parameter_or_wrong_tool_cannot_choose_private_body() -> None:
    for changes in (
        {"parameters": notification_action().parameters | {"recipient": "other.invalid"}},
        {"tool": "model.request.v1"},
    ):
        with pytest.raises(ValueError):
            require_notification_command(
                registration().sender,
                notification_action().model_copy(update=changes),
                native_command(),
                "owner.notification",
            )

"""Actual context constructor preserves its final guard; SQL/dispatch delivery is mocked only."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.builder.selected_strategy_guard import StrategySelectedBuilderGuard
from nexus.company.contracts.actions import ActionProposal
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.engineering_worker_context import prepare_engineering_context
from nexus.execution.engineering_worker_services import EngineeringWorkerServices
from nexus.tests.unit.selected_strategy_guard_fixture import guard_case


@pytest.mark.parametrize("configured", [False, True])
async def test_final_selected_guard_is_required_before_claim_and_preserved_after_factory(
    monkeypatch: pytest.MonkeyPatch,
    configured: bool,
) -> None:
    case = guard_case(monkeypatch)
    job, credential = case.original.spec.job, case.guard.credential
    bound = case.selected.binding.child.binding
    command = SegmentCommand(
        company_id=job.company_id,
        task_id=job.task_id,
        trace_id=job.trace_id,
        actor_id=job.actor_id,
        workspace_id=job.workspace_id,
        run_id=job.run_id,
        action_id=job.action_id,
        segment_id=case.original.lease.segment_id,
    )
    action = ActionProposal(
        company_id=job.company_id,
        task_id=job.task_id,
        trace_id=job.trace_id,
        actor_id=job.actor_id,
        action_id=job.action_id,
        revision=1,
        tool=case.guard.template.tool.tool,
        tool_version="v1",
        resource=job.resource_symbol,
        parameters=case.original.spec.model_dump(mode="json"),
        policy_version="fixture",
        price_version="fixture",
        estimated_cost_usd="0.01",
    )
    sources = MagicMock()
    sources.resolve.return_value = case.original
    services = EngineeringWorkerServices(
        factory=case.original.artifacts.factory,
        catalog=case.original.catalog,
        runner=MagicMock(),
        acceptance=MagicMock(),
        recovery=MagicMock(),
        identities=SimpleNamespace(current=AsyncMock(return_value=credential)),
        sources=sources,
        worker_id=case.original.lease.worker_id,
        selected_builder=case.services if configured else None,
    )
    acquired = AsyncMock(return_value=case.original.lease)
    with (
        patch(
            "nexus.execution.engineering_dispatch_read.read_engineering_dispatch",
            AsyncMock(return_value=(bound, "author", action, case.original.spec)),
        ),
        patch(
            "nexus.execution.engineering_worker_context.db_now", AsyncMock(return_value=case.now)
        ),
        patch("nexus.execution.engineering_worker_context.recover_engineering_lease", acquired),
    ):
        if configured:
            result = await prepare_engineering_context(
                services, command, workflow_id=command.workflow_id
            )
            assert type(result.guard) is StrategySelectedBuilderGuard
            assert result.guard.reader is case.services.reader
            assert result.guard.credential is credential
            acquired.assert_awaited_once()
        else:
            with pytest.raises(ValueError, match="selected engineering services"):
                await prepare_engineering_context(
                    services, command, workflow_id=command.workflow_id
                )
            acquired.assert_not_awaited()
            sources.resolve.assert_not_called()

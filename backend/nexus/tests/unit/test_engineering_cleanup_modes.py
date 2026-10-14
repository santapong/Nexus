"""Pure cleanup mode boundary tests; current stores/receipt/image/final fence are retained."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal, NoReturn, cast
from unittest.mock import AsyncMock
from uuid import uuid4, uuid5

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import nexus.builder.engineering_cleanup as module
from nexus.builder.execution_contracts import BuilderRunResult
from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.actions import ActionProposal
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.tests.engineering_check_support import check_input


class SelectedTransactionError(RuntimeError):
    """Deliberately stops pure mode-selection proof before any store/engine operation."""


@pytest.mark.parametrize("mode,permissive", [("execute", False), ("reconcile", True)])
async def test_known_cleanup_selects_current_mode_scope_without_effect_permission(
    monkeypatch: pytest.MonkeyPatch,
    mode: Literal["execute", "reconcile"],
    permissive: bool,
) -> None:
    value = check_input()
    result = value.verifier
    job = result.spec.job
    result = result.model_copy(
        update={"container_name": "nexus-builder-" + uuid5(job.company_id, str(job.action_id)).hex}
    )
    lease = _lease(result, mode)
    actual = AsyncMock()
    monkeypatch.setattr(module, "actual_action", actual)
    calls = []

    def boundary(
        factory: object,
        scope: object,
        identity: object,
        *,
        allow_paused: bool,
        allow_inactive: bool,
    ) -> NoReturn:
        calls.append((allow_paused, allow_inactive))
        raise SelectedTransactionError("selected real mode transaction")

    monkeypatch.setattr(module, "runtime_transaction", boundary)
    with pytest.raises(SelectedTransactionError):
        await module.cleanup_known_engineering_container(
            cast(async_sessionmaker[AsyncSession], object()),
            lease,
            VerifiedIdentity(principal_id=job.actor_id, workspace_id=job.workspace_id),
            _action(result),
            result.spec,
            result,
            value.verifier_receipt,
        )
    assert calls == [(permissive, permissive)] and actual.await_count == 1


def _lease(result: BuilderRunResult, mode: Literal["execute", "reconcile"]) -> ExecutionLease:
    job = result.spec.job
    return ExecutionLease(
        company_id=job.company_id,
        task_id=job.task_id,
        trace_id=job.trace_id,
        actor_id=job.actor_id,
        workspace_id=job.workspace_id,
        run_id=job.run_id,
        workflow_version="v1",
        segment_id=uuid4(),
        worker_id=uuid4(),
        fence=1,
        expires_at=datetime.now(UTC) + timedelta(seconds=60),
        mode=mode,
    )


def _action(result: BuilderRunResult) -> ActionProposal:
    job = result.spec.job
    return ActionProposal(
        company_id=job.company_id,
        action_id=job.action_id,
        task_id=job.task_id,
        trace_id=job.trace_id,
        actor_id=job.actor_id,
        revision=1,
        tool="company.builder.run.v1",
        tool_version="v1",
        resource=job.resource_symbol,
        parameters=result.spec.model_dump(mode="json"),
        policy_version="fixture-policy",
        price_version="fixture-prices",
        estimated_cost_usd=Decimal("0.01"),
    )

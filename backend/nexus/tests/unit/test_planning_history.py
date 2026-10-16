"""Exact native DBOS input projection; supplied rows are not a queue or identity witness."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.contracts.actions import ActionProposal
from nexus.execution import planning_history as module
from nexus.execution.planning_history import native_history, require_workflow_binding
from nexus.execution.planning_services import APPLICATION, QUEUE, VERSION, WORKFLOW
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.canonical import action_hash
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import CompanyControl, JournalAction
from nexus.harness.model_authorizer_contracts import model_action_parameters
from nexus.tests.unit.test_company_provider_conformance import request
from nexus.tests.unit.test_planning_services import services
from nexus.tests.unit.test_planning_worker import command


@pytest.mark.parametrize(
    "fault", [None, "queue", "application", "version", "workflow", "format", "inputs"]
)
def test_only_exact_stored_planning_queue_input_is_metadata_bound(fault: str | None) -> None:
    selected = command()
    row: dict[str, object] = {
        "name": WORKFLOW,
        "queue_name": QUEUE,
        "application_version": VERSION,
        "application_name": APPLICATION,
        "serialization": "portable_json",
        "inputs": json.dumps({"positionalArgs": [selected.model_dump_json()], "namedArgs": {}}),
    }
    fields = {
        "queue": "queue_name",
        "application": "application_name",
        "version": "application_version",
        "workflow": "name",
        "format": "serialization",
        "inputs": "inputs",
    }
    if fault is not None:
        row[fields[fault]] = "foreign"
        with pytest.raises(ValueError):
            require_workflow_binding(selected, row)
    else:
        require_workflow_binding(selected, row)


@pytest.mark.parametrize("crossed_recipe", [False, True])
async def test_actual_producer_recipe_header_is_consumed_by_native_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    crossed_recipe: bool,
) -> None:
    """Actual producer/history composition over supplied rows; no SQL, lease or SDK proof."""
    configured, selected = services(tmp_path), command()
    registry = configured.management.catalog.models
    call = request().model_copy(
        update={
            "company_id": selected.company_id,
            "task_id": selected.task_id,
            "trace_id": selected.trace_id,
            "actor_id": selected.actor_id,
            "action_id": selected.action_id,
            "attempt_id": selected.action_id,
            "registry_id": configured.registry_id,
            "registry_revision": registry.revision,
            "price_version": registry.pricebook_version,
        }
    )
    recipe = (
        configured.recipe.model_copy(update={"minimum_score": Decimal("0.12")})
        if crossed_recipe
        else configured.recipe
    )
    proposal = ActionProposal(
        company_id=selected.company_id,
        task_id=selected.task_id,
        trace_id=selected.trace_id,
        actor_id=selected.actor_id,
        action_id=selected.action_id,
        revision=1,
        tool="model.request.v1",
        tool_version="v1",
        resource=f"model:{configured.registry_id}",
        parameters=model_action_parameters(call, recipe),
        policy_version="fixture-policy",
        price_version=registry.pricebook_version,
        estimated_cost_usd="0.01",
    )
    work = ExecutionWork(
        company_id=selected.company_id,
        task_id=selected.task_id,
        workflow_name=WORKFLOW,
        workflow_version=VERSION,
        model_registry_version=registry.revision,
        model_profile=configured.recipe.profile,
    )
    action = JournalAction(
        id=selected.action_id,
        company_id=selected.company_id,
        task_id=selected.task_id,
        trace_id=selected.trace_id,
        proposal_json=proposal.model_dump_json(),
        proposal_hash=action_hash(proposal),
        state="authorized",
        consumed_at=datetime.now(UTC),
        approval_json=None,
    )
    fake = MagicMock(spec=AsyncSession)
    fake.get = AsyncMock(
        side_effect=lambda model, key: {ExecutionWork: work, JournalAction: action}.get(model)
    )
    queue = MagicMock()
    queue.mappings.return_value.one_or_none.return_value = {
        "name": WORKFLOW,
        "queue_name": QUEUE,
        "application_version": VERSION,
        "application_name": APPLICATION,
        "serialization": "portable_json",
        "inputs": json.dumps({"positionalArgs": [selected.model_dump_json()], "namedArgs": {}}),
    }
    fake.execute = AsyncMock(return_value=queue)
    session = cast(AsyncSession, fake)

    @asynccontextmanager
    async def native_session(
        self: CompanyJournal, scope: LedgerScope
    ) -> AsyncIterator[AsyncSession]:
        assert scope.task_id == selected.task_id and self._factory is configured.factory
        yield session

    monkeypatch.setattr(CompanyJournal, "_session", native_session)
    monkeypatch.setattr(
        module,
        "_control",
        AsyncMock(
            return_value=CompanyControl(
                company_id=selected.company_id,
                owner_id=selected.actor_id,
            )
        ),
    )
    dispatch = AsyncMock(return_value=selected)
    monkeypatch.setattr(module, "dispatched_binding", dispatch)
    body = AsyncMock(side_effect=AssertionError("History must not read protected input"))
    monkeypatch.setattr(configured.prepared, "load_worker", body)
    if crossed_recipe:
        with pytest.raises(ValueError, match="dispatch/action binding"):
            await native_history(configured, selected)
    else:
        value = await native_history(configured, selected)
        assert value.effect is None and value.request_sha256 == proposal.parameters["request_hash"]
    body.assert_not_awaited()
    dispatch.assert_awaited_once()

"""Actual C composition and task retention; no SQL, provider or DBOS process."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from nexus.builder.contained_query import clock_us
from nexus.execution.coding_history import require_workflow_binding
from nexus.execution.coding_operation import CodingOperation
from nexus.execution.coding_services import APPLICATION, QUEUE, REGISTRATION, VERSION, WORKFLOW
from nexus.tests.unit.coding_runtime_fixture import command, runtime_case


def test_fixed_c_abi_is_distinct_from_issued_planner_abi() -> None:
    assert (WORKFLOW, VERSION, QUEUE, APPLICATION) == (
        "company.coding.v1",
        "v1",
        "nexus.coding",
        "nexus-coding",
    )
    assert (
        REGISTRATION.workflow_name,
        REGISTRATION.workflow_version,
        REGISTRATION.queue_name,
        REGISTRATION.application_name,
    ) == (WORKFLOW, VERSION, QUEUE, APPLICATION)


@pytest.mark.parametrize(
    "fault", ["factory", "target", "sources", "authority", "authority_alias", "source_policies"]
)
def test_original_concrete_c_graph_cannot_be_swapped(tmp_path: Path, fault: str) -> None:
    value, _, _ = runtime_case(tmp_path)
    value.require_composition()
    if fault == "factory":
        object.__setattr__(value, "factory", async_sessionmaker())
    elif fault == "target":
        object.__setattr__(value, "registry_id", "foreign-model")
    elif fault == "sources":
        object.__setattr__(value, "code_sources", ())
    elif fault == "authority":
        object.__setattr__(value.contexts, "_authority", object())
    elif fault == "authority_alias":
        from nexus.company.management.planning_authority import ManagementPlanningAuthority

        object.__setattr__(
            value,
            "authority",
            ManagementPlanningAuthority(value.management, value.authority.policy, value.recipe),
        )
    else:
        from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
        from nexus.execution.planning_application_config import PlanningSourcePolicies

        freshness = value.management.freshness
        assert type(freshness) is RegisteredSourceFreshness
        policies = freshness._policies
        assert type(policies) is PlanningSourcePolicies
        freshness._policies = policies.model_copy()
    with pytest.raises(ValueError):
        value.require_composition()


async def test_constructor_and_history_operation_do_not_acquire_actor_or_prepared_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, _, _ = runtime_case(tmp_path)
    token = AsyncMock(side_effect=AssertionError("No JWT during pure composition"))
    monkeypatch.setattr(type(value.identities), "current", token)
    operation = CodingOperation(value, "native-history", clock_us() + 10_000_000)
    assert operation._store is None
    operation.finish()
    token.assert_not_awaited()


async def test_repeated_caller_cancellation_keeps_actual_leaf_and_denies_parallel_admission(
    tmp_path: Path,
) -> None:
    value, _, _ = runtime_case(tmp_path)
    entered, finish = asyncio.Event(), asyncio.Event()
    holder = []

    async def leaf() -> str:
        entered.set()
        await finish.wait()
        return "actual"

    async def driver() -> None:
        operation = CodingOperation(value, "one", clock_us() + 10_000_000)
        holder.append(operation)
        try:
            await operation.call(leaf())
        except BaseException as first:
            operation.first = first
        await operation.retire()
        operation.finish()

    task = asyncio.create_task(driver())
    await entered.wait()
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)
    assert value.pending_owners() and not task.done()
    with pytest.raises(ValueError):
        CodingOperation(value, "two", clock_us() + 10_000_000)
    finish.set()
    await task
    assert not value.pending_owners() and not value._operations


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "name",
        "queue_name",
        "application_version",
        "application_name",
        "serialization",
        "inputs",
    ],
)
def test_only_fixed_actual_dbos_portable_input_can_be_native_history(
    tmp_path: Path, fault: str | None
) -> None:
    _, prepared, lease = runtime_case(tmp_path)
    selected = command(prepared, lease)
    row = {
        "name": WORKFLOW,
        "queue_name": QUEUE,
        "application_version": VERSION,
        "application_name": APPLICATION,
        "serialization": "portable_json",
        "inputs": json.dumps({"positionalArgs": [selected.model_dump_json()], "namedArgs": {}}),
    }
    if fault is not None:
        row[fault] = "foreign"
        with pytest.raises(ValueError):
            require_workflow_binding(selected, row)
    else:
        require_workflow_binding(selected, row)


@pytest.mark.parametrize("field", ["task_id", "actor_id", "run_id", "workspace_id"])
async def test_foreign_c_command_denies_before_native_history_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    from collections.abc import AsyncIterator
    from contextlib import asynccontextmanager
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from nexus.execution.coding_history import native_history
    from nexus.harness.journal import CompanyJournal

    value, prepared, lease = runtime_case(tmp_path)
    selected = command(prepared, lease).model_copy(update={field: UUID(int=9901)})

    @asynccontextmanager
    async def forbidden(*args: object) -> AsyncIterator[AsyncSession]:
        raise AssertionError("foreign C command cannot start native history IO")
        yield AsyncSession()

    monkeypatch.setattr(CompanyJournal, "_session", forbidden)
    with pytest.raises(ValueError):
        await native_history(value, selected)

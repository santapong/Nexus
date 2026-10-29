"""Separate deployment-version ownership from logical model workflows; no DBOS launch."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.management.scheduling_contracts import WorkflowRegistration
from nexus.company.management.scheduling_queue import _enqueue_exact
from nexus.company.management.transactions import ManagementDeniedError
from nexus.execution import coding_worker, planning_worker
from nexus.execution.coding_history import require_workflow_binding as require_coding
from nexus.execution.coding_services import REGISTRATION as CODING
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.model_workflow_identity import (
    application_version,
    require_issued_model_binding,
)
from nexus.execution.planning_history import require_workflow_binding as require_planning
from nexus.execution.planning_services import REGISTRATION as PLANNING
from nexus.execution.runtime_contracts import EffectRecord, EffectState
from nexus.tests.unit.coding_runtime_fixture import runtime_case
from nexus.tests.unit.test_planning_services import services
from nexus.tests.unit.test_planning_worker import command

Role = Literal["planner", "coder"]


def stored(
    selected: SegmentCommand, registration: WorkflowRegistration, version: str
) -> dict[str, object]:
    return {
        "name": registration.workflow_name,
        "queue_name": registration.queue_name,
        "application_version": version,
        "application_name": registration.application_name,
        "serialization": "portable_json",
        "inputs": json.dumps({"positionalArgs": [selected.model_dump_json()], "namedArgs": {}}),
    }


def test_two_actual_worker_configurations_do_not_collide_in_a_shared_system_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Supply only the SDK constructor's actual v3.2 version-owner rule, not SQL/launch."""
    owners: dict[str, str] = {}

    def configure(*, config: dict[str, object]) -> None:
        version, owner = config["application_version"], config["name"]
        assert isinstance(version, str) and isinstance(owner, str)
        if version in owners and owners[version] != owner:
            raise ValueError("DBOS deployment version already belongs to another application")
        owners[version] = owner

    monkeypatch.setattr(planning_worker, "DBOS", configure)
    monkeypatch.setattr(coding_worker, "DBOS", configure)
    monkeypatch.setattr(planning_worker, "_services", None)
    monkeypatch.setattr(coding_worker, "_services", None)
    planning_worker.configure_planning_worker(
        services(tmp_path / "planning"), "postgresql://unused"
    )
    coding_worker.configure_coding_worker(
        runtime_case(tmp_path / "coding")[0], "postgresql://unused"
    )
    assert owners == {"nexus-planning-v1": "nexus-planning", "nexus-coding-v1": "nexus-coding"}
    assert PLANNING.workflow_version == CODING.workflow_version == "v1"


@pytest.mark.parametrize("role", ["planner", "coder"])
async def test_actual_atomic_enqueue_uses_the_same_unique_deployment_identity(role: Role) -> None:
    selected, registration = command(), PLANNING if role == "planner" else CODING
    version = "nexus-planning-v1" if role == "planner" else "nexus-coding-v1"
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=selected.workflow_id)
    projection = MagicMock()
    projection.mappings.return_value.one_or_none.return_value = stored(
        selected, registration, version
    )
    session.execute = AsyncMock(return_value=projection)
    await _enqueue_exact(cast(AsyncSession, session), selected, registration)
    parameters = session.scalar.await_args.args[1]
    assert parameters["version"] == version
    assert parameters["workflow_name"] == registration.workflow_name
    assert registration.workflow_version == "v1"


@pytest.mark.parametrize("role", ["planner", "coder"])
def test_legacy_v1_tuple_cannot_be_a_current_unissued_workflow(role: Role) -> None:
    registration, require = (
        (PLANNING, require_planning) if role == "planner" else (CODING, require_coding)
    )
    with pytest.raises(ValueError):
        require(command(), stored(command(), registration, "v1"))


def issued(selected: SegmentCommand, state: EffectState = "outcome_unknown") -> EffectRecord:
    """Supplied native metadata only; no SQL, receipt quality or effect permission."""
    return EffectRecord(
        company_id=selected.company_id,
        action_id=selected.action_id,
        task_id=selected.task_id,
        trace_id=selected.trace_id,
        run_id=selected.run_id,
        proposal_hash="a" * 64,
        intent_fence=1,
        attempt_kind="model_requests",
        state=state,
        created_at=datetime.now(UTC),
        receipt=None,
        verification=None,
    )


@pytest.mark.parametrize("role", ["planner", "coder"])
@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("state", ["intent", "outcome_unknown", "succeeded", "failed"])
def test_only_exact_issued_metadata_can_read_closed_legacy_or_current_tuple(
    role: Role, legacy: bool, state: EffectState
) -> None:
    selected, registration = command(), PLANNING if role == "planner" else CODING
    version = "v1" if legacy else application_version(registration)
    effect = issued(selected, state)
    require_issued_model_binding(
        selected,
        stored(selected, registration, version),
        registration,
        effect,
        effect.proposal_hash,
    )


@pytest.mark.parametrize("role", ["planner", "coder"])
@pytest.mark.parametrize(
    "field",
    ["company_id", "action_id", "task_id", "trace_id", "run_id", "proposal_hash", "attempt_kind"],
)
def test_foreign_native_effect_cannot_unlock_legacy_metadata(role: Role, field: str) -> None:
    selected, registration = command(), PLANNING if role == "planner" else CODING
    value = (
        "b" * 64
        if field == "proposal_hash"
        else ("tool_attempts" if field == "attempt_kind" else UUID(int=999))
    )
    with pytest.raises(ValueError):
        require_issued_model_binding(
            selected,
            stored(selected, registration, "v1"),
            registration,
            issued(selected).model_copy(update={field: value}),
            "a" * 64,
        )


@pytest.mark.parametrize("role", ["planner", "coder"])
def test_missing_native_effect_cannot_unlock_legacy_metadata(role: Role) -> None:
    selected, registration = command(), PLANNING if role == "planner" else CODING
    with pytest.raises(ValueError):
        require_issued_model_binding(
            selected,
            stored(selected, registration, "v1"),
            registration,
            cast(EffectRecord, None),
            "a" * 64,
        )


@pytest.mark.parametrize("role", ["planner", "coder"])
@pytest.mark.parametrize(
    "field",
    ["name", "queue_name", "application_version", "application_name", "serialization", "inputs"],
)
def test_issued_effect_never_allows_crossed_queue_tuple_or_input(role: Role, field: str) -> None:
    selected, registration = command(), PLANNING if role == "planner" else CODING
    row = stored(selected, registration, "v1") | {field: "foreign"}
    with pytest.raises(ValueError):
        require_issued_model_binding(selected, row, registration, issued(selected), "a" * 64)


@pytest.mark.parametrize("role", ["planner", "coder"])
async def test_fresh_enqueue_cannot_reuse_an_old_unissued_v1_row(role: Role) -> None:
    selected, registration = command(), PLANNING if role == "planner" else CODING
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=selected.workflow_id)
    projection = MagicMock()
    projection.mappings.return_value.one_or_none.return_value = stored(selected, registration, "v1")
    session.execute = AsyncMock(return_value=projection)
    with pytest.raises(ManagementDeniedError):
        await _enqueue_exact(cast(AsyncSession, session), selected, registration)
    assert session.scalar.await_args.args[1]["version"] == application_version(registration)


@pytest.mark.parametrize(
    "field", ["workflow_name", "workflow_version", "queue_name", "application_name"]
)
async def test_reserved_registration_cannot_be_spliced_before_sql(field: str) -> None:
    selected = PLANNING.model_copy(update={field: "foreign"})
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock()
    with pytest.raises(ValueError):
        await _enqueue_exact(cast(AsyncSession, session), command(), selected)
    session.scalar.assert_not_awaited()


def test_unrelated_legacy_registration_wire_and_deployment_version_remain_exact() -> None:
    registration = WorkflowRegistration(
        workflow_name="old.workflow",
        workflow_version="v1",
        queue_name="old.queue",
        application_name="old-app",
    )
    assert application_version(registration) == "v1"
    assert registration.model_dump_json() == (
        '{"workflow_name":"old.workflow","workflow_version":"v1",'
        '"queue_name":"old.queue","application_name":"old-app"}'
    )

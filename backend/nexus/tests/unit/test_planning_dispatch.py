"""Dispatch rejects caller-selected identity/hash before private input or native mutation."""

from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from nexus.builder.contained_query import clock_us
from nexus.company.brain.base import BrainReadScope
from nexus.execution.planning_dispatch import dispatch
from nexus.tests.unit.test_planning_services import services


@pytest.mark.parametrize("fault", ["hash", "actor", "workspace", "unregistered-scope"])
async def test_dispatch_cannot_turn_posted_scope_into_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    configured = services(tmp_path)
    load = AsyncMock()
    monkeypatch.setattr(configured.prepared, "load_actor", load)
    scope = BrainReadScope(
        company_id=UUID(int=1),
        workspace_id=UUID(int=2),
        principal_id=UUID(int=3),
        operation_id=UUID(int=100),
        trace_id=UUID(int=101),
        task_id=UUID(int=6),
        task_trace_id=UUID(int=7),
        actor_id=UUID(int=3),
    )
    if fault == "actor":
        scope = scope.model_copy(update={"principal_id": UUID(int=999), "actor_id": UUID(int=999)})
    elif fault == "workspace":
        scope = scope.model_copy(update={"workspace_id": UUID(int=999)})
    elif fault == "unregistered-scope":
        scope = scope.model_copy(update={"task_id": None, "task_trace_id": None})
    with pytest.raises(ValueError):
        await dispatch(
            configured,
            scope,
            UUID(int=5),
            "bad" if fault == "hash" else "a" * 64,
            end_us=clock_us() + 10_000_000,
        )
    load.assert_not_awaited()

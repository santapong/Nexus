"""Real Nexus family predicates over explicit SQL/current-governance delivery, no DB proof."""

from copy import copy
from typing import cast

import pytest

from nexus.company.access import VerifiedIdentity
from nexus.company.management.nexus_cycle_admission import NexusStage
from nexus.execution.nexus_cycle_partition import read_current_nexus_family_locked
from nexus.execution.runtime_models import EffectIntent
from nexus.harness.journal_models import CostHold
from nexus.tests.unit.nexus_cycle_fixture import key, origin
from nexus.tests.unit.nexus_family_fixture import family


@pytest.mark.parametrize("stage", ["planning", "execution"])
async def test_exact_actual_family_retains_same_root_and_planner(
    monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    value = family(monkeypatch, cast(NexusStage, stage))
    record = await read_current_nexus_family_locked(
        value.session,
        value.control,
        value.work,
        value.identity,
        admission=value.admission,
        catalog=value.catalog,
    )
    assert record.revision == (1 if stage == "planning" else 2)
    assert len(value.executions) == (2 if stage == "planning" else 7)
    assert value.executions[0].model_requests_delegated == 1
    assert value.executions[1].tool_attempts_limit == 0


@pytest.mark.parametrize(
    "fault",
    [
        "extra-directory",
        "extra-execution",
        "root-model-used",
        "root-quota",
        "delegated-usd",
        "delegated-tool",
        "planner-bill",
        "planner-result",
        "planner-used",
        "planner-lease",
        "revision",
        "identity",
        "owner",
        "child-model",
        "grandchild",
    ],
)
async def test_partition_splices_deny_before_any_permit(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    value = family(monkeypatch)
    root, planner = value.executions[:2]
    if fault == "extra-directory":
        value.directories.append(copy(value.directories[-1]))
    elif fault == "extra-execution":
        value.executions.append(copy(value.executions[-1]))
    elif fault == "root-model-used":
        root.model_requests_used = 1
    elif fault == "root-quota":
        root.tool_attempts_limit = 20
    elif fault == "delegated-usd":
        value.directories[0].delegated_usd += 1
    elif fault == "delegated-tool":
        root.tool_attempts_delegated = 4
    elif fault == "planner-bill":
        held = value.stored[(CostHold, origin(value.admission).action_id)]
        assert isinstance(held, CostHold)
        held.state = "unknown"
        held.actual_usd = None
    elif fault == "planner-result":
        intent = value.stored[
            (EffectIntent, (value.control.company_id, origin(value.admission).action_id))
        ]
        assert isinstance(intent, EffectIntent)
        intent.state = "outcome_unknown"
    elif fault == "planner-used":
        planner.model_requests_used = 0
    elif fault == "planner-lease":
        planner.worker_id = key("unexpected-worker")
    elif fault == "revision":
        value.events.clear()
    elif fault == "identity":
        value.identity = VerifiedIdentity(
            principal_id=value.control.owner_id, workspace_id=value.identity.workspace_id
        )
    elif fault == "owner":
        value.control.owner_id = key("different-owner")
    elif fault == "child-model":
        value.work.model_requests_limit = 1
    else:
        value.work.parent_task_id = planner.task_id
    with pytest.raises(ValueError):
        await read_current_nexus_family_locked(
            value.session,
            value.control,
            value.work,
            value.identity,
            admission=value.admission,
            catalog=value.catalog,
        )


@pytest.mark.parametrize("same_root", [True, False])
async def test_unmanaged_native_descendant_cannot_spend_parked_nexus_slices(
    monkeypatch: pytest.MonkeyPatch,
    same_root: bool,
) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from nexus.company.directory_models import RegisteredWork
    from nexus.company.management.plan_store import ManagementPlanStore
    from nexus.execution import management_checks as module
    from nexus.tests.unit.nexus_intent_fixture import boundary

    value = boundary()
    assert value.catalog.nexus_cycle_admission is not None
    session = MagicMock()
    session.scalar = AsyncMock(return_value="company_management_procedures")
    session.get = AsyncMock(
        return_value=RegisteredWork(
            root_task_id=(
                value.catalog.nexus_cycle_admission.procedure.binding.task_id
                if same_root
                else key("unrelated-root")
            )
        )
    )
    monkeypatch.setattr(module, "require_not_cancelled", AsyncMock())
    monkeypatch.setattr(ManagementPlanStore, "managed_kind", AsyncMock(return_value="unmanaged"))
    if same_root:
        with pytest.raises(ValueError, match="Unmanaged"):
            await module.require_management_execution(
                session, value.control, value.work, value.identity, value.catalog
            )
    else:
        await module.require_management_execution(
            session, value.control, value.work, value.identity, value.catalog
        )

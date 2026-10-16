"""Current owner orchestration cannot infer registration or fresh C identity from a request.

Cohesion exception: each complete supplied-row fixture stays beside the actual
family or queue predicate it exercises; it never creates native authority.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from nexus.builder.contained_query import clock_us
from nexus.company.access import CompanyControlScope
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.tests.unit.coding_application_fixture import application
from nexus.tests.unit.test_coding_intent import prepared_case, witness


async def test_c_actor_cannot_become_owner_or_trigger_lifecycle_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = application(tmp_path)
    prepared, _, _, _ = prepared_case()
    actor = await witness(prepared)
    call = AsyncMock(side_effect=AssertionError("foreign owner cannot query native work"))
    monkeypatch.setattr(app.lifecycle, "_owner", call)
    scope = CompanyControlScope(
        company_id=app.config.catalog.company_id,
        principal_id=actor.identity.principal_id,
        operation_id=UUID(int=901),
        trace_id=UUID(int=902),
    )
    with pytest.raises(ValueError):
        await app.lifecycle.status(
            scope, actor, app.config.goal.goal_id, end_us=clock_us() + 5_000_000
        )
    call.assert_not_awaited()


async def test_existing_owner_dispatch_precedes_fresh_actor_body_and_r2_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nexus.execution import coding_lifecycle_reads as metadata
    from nexus.execution.coding_dispatch import CodingDispatchRecord
    from nexus.execution.dbos_contracts import SegmentCommand
    from nexus.tests.unit.coding_application_fixture import owner_scope, owner_witness

    app = application(tmp_path)
    owner = await owner_witness(app)
    scope = owner_scope(app)
    bound = app.config.admission.slots[1].child.binding
    command = SegmentCommand(
        company_id=bound.company_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        actor_id=bound.actor_id,
        workspace_id=bound.workspace_id,
        run_id=bound.run_id,
        action_id=UUID(int=901),
        segment_id=UUID(int=902),
    )
    record = CodingDispatchRecord(
        command=command, workflow_id=command.workflow_id, disposition="existing"
    )

    async def existing(*args: object) -> tuple[CodingDispatchRecord, int]:
        assert type(args[-1]) is int
        return record, args[-1]

    monkeypatch.setattr(metadata, "existing_dispatch", existing)
    fresh = AsyncMock(side_effect=AssertionError("Issued metadata cannot need fresh r2"))
    token = AsyncMock(side_effect=AssertionError("Issued owner replay cannot acquire C token"))
    monkeypatch.setattr(app.lifecycle, "_bundle", fresh)
    monkeypatch.setattr(type(app.services.identities), "current", token)

    async def current(
        scope: CompanyControlScope, owner: AuthenticatedWorkerIdentity, end: int
    ) -> int:
        return end

    monkeypatch.setattr(app.lifecycle, "_owner", current)
    read = await app.lifecycle.dispatch(
        scope, owner, command.action_id, "a" * 64, end_us=clock_us() + 5_000_000
    )
    assert read.value == record and not read.value.company_completed
    fresh.assert_not_awaited()
    token.assert_not_awaited()


@pytest.mark.parametrize(
    "fault", [None, "r1", "head", "decision", "family", "registration", "payload"]
)
async def test_current_r2_loader_reads_actual_full_native_family_before_c_role_is_derived(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str | None
) -> None:
    """Real full-family/r2 predicates over supplied SQL; governance-source transport is supplied."""
    from nexus.company.management.goal_store import GoalStore
    from nexus.company.management.plan_models import (
        ManagementOwnerDecision,
        ManagementPlanHead,
        ManagementPlanRevision,
    )
    from nexus.execution import coding_lifecycle_bindings as module
    from nexus.tests.unit import nexus_family_fixture as fixture
    from nexus.tests.unit.coding_application_fixture import owner_scope, owner_witness
    from nexus.tests.unit.test_nexus_coding_admission import planning_origin
    from nexus.tests.unit.test_nexus_coding_planner import base_plan

    value = application(tmp_path)
    admission = value.config.admission
    monkeypatch.setattr(fixture, "case", lambda: (admission, value.config.catalog))
    monkeypatch.setattr(fixture, "base", base_plan)
    monkeypatch.setattr(fixture, "origin", planning_origin)
    f = fixture.family(monkeypatch, "planning" if fault == "r1" else "execution")
    owner, scope = await owner_witness(value), owner_scope(value)
    monkeypatch.setattr(module, "db_clock", AsyncMock(side_effect=lambda _: datetime.now(UTC)))
    monkeypatch.setattr(
        GoalStore,
        "_current",
        AsyncMock(
            return_value=SimpleNamespace(
                definition=SimpleNamespace(owner_id=f.control.owner_id, mandate=admission.mandate)
            )
        ),
    )
    monkeypatch.setattr(
        module,
        "current_mandate",
        AsyncMock(
            return_value=SimpleNamespace(mandate=SimpleNamespace(owner_id=f.control.owner_id))
        ),
    )
    monkeypatch.setattr(
        module,
        "current_charter",
        AsyncMock(return_value=SimpleNamespace(mandate=admission.mandate)),
    )
    head = f.stored[(ManagementPlanHead, (admission.company_id, admission.plan_id))]
    assert isinstance(head, ManagementPlanHead)
    decision = f.stored[(ManagementOwnerDecision, (admission.company_id, head.decision_id))]
    assert isinstance(decision, ManagementOwnerDecision)
    record = f.stored[(ManagementPlanRevision, (admission.company_id, head.current_revision_id))]
    assert isinstance(record, ManagementPlanRevision)
    if fault == "head":
        head.current_revision_id = UUID(int=999)
    elif fault == "decision":
        decision.kind = "reject"
    elif fault == "family":
        f.executions[0].model_requests_delegated -= 1
    elif fault == "registration":
        f.work.registration_hash = "e" * 64
    elif fault == "payload":
        raw = json.loads(record.snapshot_json)
        raw["coding_admission_sha256"] = "f" * 64
        record.snapshot_json = json.dumps(raw)
    if fault is None:
        bundle, end = await module.approved_r2_locked(
            value.services, f.session, f.control, scope, owner, clock_us() + 5_000_000
        )
        assert bundle.plan.revision == 2 and len(bundle.plan.payload.children) == 10
        assert bundle.binding.child == admission.slots[1].child
        assert bundle.work.registration.work == admission.slots[1].work
        assert end > clock_us()
    else:
        with pytest.raises(ValueError):
            await module.approved_r2_locked(
                value.services, f.session, f.control, scope, owner, clock_us() + 5_000_000
            )


@pytest.mark.parametrize("queue", ["exact", "missing", "crossed"])
async def test_owner_existing_dispatch_requires_original_fixed_dbos_metadata_without_actor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, queue: str
) -> None:
    """Real owner/native/dispatch predicates; supplied SQL includes the public DBOS projection."""
    from collections.abc import AsyncIterator
    from contextlib import asynccontextmanager
    from unittest.mock import MagicMock

    from sqlalchemy.ext.asyncio import AsyncSession

    from nexus.execution import coding_lifecycle_bindings as bindings
    from nexus.execution import coding_lifecycle_reads as metadata
    from nexus.execution.coding_services import APPLICATION, QUEUE, VERSION, WORKFLOW
    from nexus.execution.dispatch_models import SegmentDispatch
    from nexus.execution.runtime_models import EffectIntent, ExecutionWork
    from nexus.harness.canonical import action_hash
    from nexus.harness.journal_models import CompanyControl, JournalAction
    from nexus.tests.unit.coding_application_fixture import owner_scope, owner_witness
    from nexus.tests.unit.coding_runtime_fixture import command, native_work
    from nexus.tests.unit.test_coding_prepared_store import saved_case

    files = tmp_path / "files"
    files.mkdir(mode=0o700)
    _, prepared, lease, _, delivery = await saved_case(files, monkeypatch)
    value = application(tmp_path / "application")
    owner, scope = await owner_witness(value), owner_scope(value)
    assert delivery.action is not None
    actual = command(prepared, lease)
    row = JournalAction(
        id=actual.action_id,
        company_id=actual.company_id,
        task_id=actual.task_id,
        trace_id=actual.trace_id,
        proposal_json=delivery.action.model_dump_json(),
        proposal_hash=action_hash(delivery.action),
        state="authorized",
        approval_json=None,
        consumed_at=datetime.now(UTC),
    )
    dispatch = SegmentDispatch(
        company_id=actual.company_id,
        action_id=actual.action_id,
        task_id=actual.task_id,
        run_id=actual.run_id,
        segment_id=actual.segment_id,
        workflow_id=actual.workflow_id,
        binding_json=actual.model_dump_json(),
    )
    session = delivery.session
    session.in_transaction.return_value = True
    rows = {
        JournalAction: row,
        SegmentDispatch: dispatch,
        ExecutionWork: native_work(value.services, lease),
        EffectIntent: None,
    }
    session.get.side_effect = lambda model, key: rows.get(model)
    session.scalar.return_value = dispatch
    projected = {
        "name": WORKFLOW,
        "queue_name": QUEUE,
        "application_version": VERSION,
        "application_name": APPLICATION,
        "serialization": "portable_json",
        "inputs": json.dumps({"positionalArgs": [actual.model_dump_json()], "namedArgs": {}}),
    }
    if queue == "crossed":
        projected["queue_name"] = "nexus.planning"
    result = MagicMock()
    result.mappings.return_value.one_or_none.return_value = (
        None if queue == "missing" else projected
    )
    session.execute.return_value = result
    delivery.control.paused = True

    @asynccontextmanager
    async def tx(
        *args: object, **kwargs: object
    ) -> AsyncIterator[tuple[AsyncSession, CompanyControl, None]]:
        yield session, delivery.control, None

    monkeypatch.setattr(metadata, "management_owner_transaction", tx)
    monkeypatch.setattr(bindings, "db_clock", AsyncMock(side_effect=lambda _: datetime.now(UTC)))
    token = AsyncMock(side_effect=AssertionError("Issued owner metadata acquired C witness"))
    monkeypatch.setattr(type(value.services.identities), "current", token)
    if queue == "exact":
        found, _ = await metadata.existing_dispatch(
            value.lifecycle, scope, owner, row.id, row.proposal_hash, clock_us() + 5_000_000
        )
        assert found is not None and found.command == actual and found.disposition == "existing"
    else:
        with pytest.raises(ValueError, match="DBOS workflow ABI"):
            await metadata.existing_dispatch(
                value.lifecycle, scope, owner, row.id, row.proposal_hash, clock_us() + 5_000_000
            )
    token.assert_not_awaited()

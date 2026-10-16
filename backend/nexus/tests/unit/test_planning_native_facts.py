"""Actual mapped native rows with supplied SQL delivery; no database qualification claim."""

from datetime import timedelta
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.contracts.actions import ApprovalDecision
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.goal_store import GoalStore
from nexus.company.management.governance_models import ManagementGoalHead
from nexus.company.management.plan_models import (
    ManagementOwnerDecision,
    ManagementPlanHead,
    ManagementPlanRevision,
    ManagementPlanTask,
)
from nexus.company.management.plan_registration import registration
from nexus.company.management.planning_native_facts import (
    native_planning,
    read_end,
    require_base_plan,
)
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.execution.runtime_support import registration_digest
from nexus.harness.journal_models import CompanyControl, CostHold, JournalAction
from nexus.harness.lifecycle import ActionState
from nexus.tests.unit.test_planning_source_reader import recorded


class Rows:
    def __init__(self) -> None:
        self.rows: dict[tuple[type[object], object], object] = {}

    def in_transaction(self) -> bool:
        return True

    async def get(self, model: type[object], key: object) -> object | None:
        return self.rows.get((model, key))


async def fixture_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Rows, CompanyControlScope, CompanyControl, object]:
    from types import SimpleNamespace

    import nexus.company.management.planning_native_facts as module

    reader, native, saved = await recorded(tmp_path)
    base = reader.template.base_plan
    payload = base.payload
    company = base.company_id
    child, item = payload.children[0], payload.plan.items[0]
    company_control = CompanyControl(
        company_id=company, owner_id=child.binding.actor_id, paused=False
    )
    scope = CompanyControlScope(
        company_id=company,
        principal_id=company_control.owner_id,
        operation_id=UUID(int=400),
        trace_id=UUID(int=401),
    )
    rows = Rows()

    def put(model: type[object], key: object, value: object) -> None:
        rows.rows[(model, key)] = value

    put(
        ManagementPlanRevision,
        (company, base.plan_revision_id),
        ManagementPlanRevision(
            company_id=company,
            plan_revision_id=base.plan_revision_id,
            plan_id=base.plan_id,
            revision=base.revision,
            goal_id=payload.goal.goal_id,
            goal_revision_id=payload.goal.revision_id,
            mandate_revision_id=payload.mandate.revision_id,
            sha256=base.sha256,
            snapshot_json=payload.model_dump_json(),
            proposed_by=base.proposed_by,
            recorded_at=base.recorded_at,
        ),
    )
    head = ManagementPlanHead(
        company_id=company,
        plan_id=base.plan_id,
        current_revision_id=base.plan_revision_id,
        goal_id=payload.goal.goal_id,
        procedure_id=payload.procedure.procedure_id,
        decision_id=UUID(int=500),
        state="approved",
    )
    put(ManagementPlanHead, (company, base.plan_id), head)
    put(
        ManagementGoalHead,
        (company, payload.goal.goal_id),
        ManagementGoalHead(
            company_id=company,
            goal_id=payload.goal.goal_id,
            current_revision_id=payload.goal.revision_id,
            active=True,
        ),
    )
    decision = ManagementOwnerDecision(
        company_id=company,
        decision_id=head.decision_id,
        owner_id=company_control.owner_id,
        kind="approve",
        plan_revision_id=base.plan_revision_id,
        payload_sha256=base.sha256,
    )
    put(ManagementOwnerDecision, (company, head.decision_id), decision)
    registered = registration(child.binding, item, child.quota)
    work = ExecutionWork(
        **child.binding.model_dump(exclude={"schema_version"}),
        registration_json=registered.model_dump_json(),
        registration_hash=registration_digest(registered),
        parent_task_id=payload.procedure.binding.task_id,
        state="verifying",
        fence=2,
        worker_id=None,
        lease_until=None,
        lease_mode=None,
        lease_principal_id=None,
        segment_number=1,
        segment_id=UUID(int=501),
        waiting_action_id=None,
        **{
            f"{kind}_{suffix}": value
            for kind in ("model_requests", "tool_attempts", "rework_rounds", "plan_revisions")
            for suffix, value in (
                ("used", int(kind == "model_requests")),
                ("delegated", 0),
                ("limit", getattr(child.quota, kind)),
            )
        },
    )
    put(ExecutionWork, (company, child.binding.task_id), work)
    task = ManagementPlanTask(
        company_id=company,
        plan_revision_id=base.plan_revision_id,
        task_id=child.binding.task_id,
        run_id=child.binding.run_id,
        goal_id=payload.goal.goal_id,
        procedure_id=payload.procedure.procedure_id,
        department_id=child.charter.department_id,
        charter_revision_id=child.charter.revision_id,
        allocation_usd=child.allocation_usd,
        quota_json=child.quota.model_dump_json(),
        binding_json=child.binding.model_dump_json(),
        work_sha256=work.registration_hash,
    )
    put(ManagementPlanTask, (company, base.plan_revision_id, child.binding.task_id), task)
    approval = ApprovalDecision(
        company_id=company,
        decision_id=UUID(int=502),
        action_id=saved.request.action_id,
        action_revision=1,
        action_hash=saved.action_hash,
        approver_id=company_control.owner_id,
        decision="approved",
        issued_at=saved.source_event_at - timedelta(minutes=1),
        expires_at=saved.source_event_at + timedelta(minutes=1),
    )
    action = JournalAction(
        company_id=company,
        id=saved.request.action_id,
        task_id=child.binding.task_id,
        trace_id=child.binding.trace_id,
        proposal_json=native.proposal.model_dump_json(),
        proposal_hash=saved.action_hash,
        state=ActionState.AUTHORIZED.value,
        approval_json=approval.model_dump_json(),
        consumed_at=saved.source_event_at,
    )
    effect = EffectIntent(
        company_id=company,
        action_id=action.id,
        task_id=work.task_id,
        trace_id=work.trace_id,
        run_id=work.run_id,
        proposal_hash=saved.action_hash,
        intent_fence=1,
        attempt_kind="model_requests",
        state="succeeded",
        created_at=saved.source_event_at,
        receipt_json=native.receipt.model_dump_json(),
    )
    hold = CostHold(
        company_id=company,
        action_id=action.id,
        task_id=work.task_id,
        state="reconciled",
        actual_usd=native.actual_usd,
    )
    put(JournalAction, action.id, action)
    put(EffectIntent, (company, action.id), effect)
    put(CostHold, action.id, hold)
    monkeypatch.setattr(GoalStore, "_current", AsyncMock(return_value=None))
    monkeypatch.setattr(module, "require_resources", AsyncMock(return_value=()))
    from nexus.company.management.owner_view_sources import SourceDisclosure

    monkeypatch.setattr(module, "source_disclosure", AsyncMock(return_value=SourceDisclosure(None)))
    monkeypatch.setattr(module, "db_clock", AsyncMock(return_value=saved.checked_at))
    return (
        rows,
        scope,
        company_control,
        SimpleNamespace(
            reader=reader,
            native=native,
            saved=saved,
            head=head,
            decision=decision,
            work=work,
            action=action,
            effect=effect,
            hold=hold,
        ),
    )


@pytest.mark.parametrize(
    "change",
    [
        None,
        "receipt",
        "unknown",
        "unreleased",
        "approval",
        "goal",
        "base",
        "registration",
        "owner",
        "cost",
    ],
)
async def test_native_result_requires_original_registered_known_released_join(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str | None
) -> None:
    from types import SimpleNamespace

    rows, scope, control, raw = await fixture_rows(tmp_path, monkeypatch)
    data = cast(SimpleNamespace, raw)
    if change == "receipt":
        data.effect.receipt_json = None
    elif change == "unknown":
        data.effect.state = "outcome_unknown"
    elif change == "unreleased":
        data.work.worker_id = UUID(int=999)
    elif change == "approval":
        data.action.consumed_at = data.saved.checked_at + timedelta(hours=1)
    elif change == "goal":
        data.head.current_revision_id = UUID(int=999)
    elif change == "base":
        row = cast(
            ManagementPlanRevision,
            rows.rows[
                (
                    ManagementPlanRevision,
                    (scope.company_id, data.reader.template.base_plan.plan_revision_id),
                )
            ],
        )
        row.sha256 = "f" * 64
    elif change == "registration":
        data.work.registration_hash = "f" * 64
    elif change == "owner":
        control.owner_id = UUID(int=999)
    elif change == "cost":
        data.hold.actual_usd = None

    async def read() -> object:
        return await native_planning(
            cast(AsyncSession, rows),
            control,
            scope,
            VerifiedIdentity(principal_id=scope.principal_id, workspace_id=UUID(int=2)),
            data.action.id,
            None,
            read_end(),
            data.reader.template,
            data.reader.sources,
        )

    if change is None:
        assert await read() == data.native
    else:
        with pytest.raises(ValueError):
            await read()


async def test_approved_exact_target_replay_joins_actual_revision_instead_of_old_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from nexus.company.management.planning_proposal_bridge import map_content

    rows, scope, control, raw = await fixture_rows(tmp_path, monkeypatch)
    data = cast(SimpleNamespace, raw)
    source = data.reader._interpret(data.saved, data.native)
    target = map_content(source.content, source.origin, data.reader.template)
    target_id = UUID(int=600)
    row = ManagementPlanRevision(
        company_id=scope.company_id,
        plan_revision_id=target_id,
        plan_id=target.plan.plan_id,
        revision=2,
        goal_id=target.goal.goal_id,
        goal_revision_id=target.goal.revision_id,
        mandate_revision_id=target.mandate.revision_id,
        sha256=canonical_sha256(target),
        snapshot_json=target.model_dump_json(),
        proposed_by=scope.principal_id,
        recorded_at=data.saved.checked_at,
    )
    rows.rows[(ManagementPlanRevision, (scope.company_id, target_id))] = row
    data.head.current_revision_id = target_id
    data.decision.plan_revision_id = target_id
    data.decision.payload_sha256 = row.sha256
    await require_base_plan(
        cast(AsyncSession, rows), control, scope, target_id, data.reader.template
    )
    with pytest.raises(ValueError):
        await require_base_plan(
            cast(AsyncSession, rows), control, scope, None, data.reader.template
        )
    row.snapshot_json = data.reader.template.base_plan.payload.model_dump_json()
    with pytest.raises(ValueError):
        await require_base_plan(
            cast(AsyncSession, rows), control, scope, target_id, data.reader.template
        )

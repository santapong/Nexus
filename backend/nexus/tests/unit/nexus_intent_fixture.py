"""Actual EffectStore.begin with supplied SQL/authority delivery; no native or database proof."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.plan_catalog import PlanAdmissionCatalog
from nexus.company.management.plan_registration import registration
from nexus.execution.effect_store import EffectStore
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt, ExecutionWork
from nexus.execution.runtime_support import registration_digest
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CompanyControl, CostHold, JournalAction
from nexus.tests.unit.nexus_cycle_fixture import case, key


@dataclass
class Boundary:
    catalog: PlanAdmissionCatalog
    work: ExecutionWork
    lease: ExecutionLease
    identity: VerifiedIdentity
    action: JournalAction
    hold: CostHold
    control: CompanyControl
    now: datetime
    session: MagicMock = field(default_factory=lambda: MagicMock(spec=AsyncSession))
    previous: EffectIntent | None = None
    added: list[object] = field(default_factory=list)
    move: AsyncMock = field(default_factory=AsyncMock)

    def install(self, monkeypatch: pytest.MonkeyPatch) -> EffectStore:
        from nexus.execution import effect_store as module
        from nexus.execution import effect_support as authority

        @asynccontextmanager
        async def transaction(
            *args: object, **kwargs: object
        ) -> AsyncIterator[tuple[AsyncSession, CompanyControl, MagicMock]]:
            yield cast(AsyncSession, self.session), self.control, MagicMock()

        async def get(model: type[object], selector: object) -> object | None:
            if model is EffectIntent:
                return self.previous
            if model is JournalAction:
                return self.action
            if model is CostHold:
                return self.hold
            if model is ExecutionAttempt:
                return None
            raise AssertionError("Unexpected native get")

        async def scalar(statement: object) -> object | None:
            sql = str(statement)
            if "clock_timestamp" in sql:
                return self.now
            if "FROM company_execution_work" in sql:
                return self.work
            if "company_effect_intents.action_id" in sql:
                return None
            raise AssertionError("Unexpected native scalar")

        self.session.get = AsyncMock(side_effect=get)
        self.session.scalar = AsyncMock(side_effect=scalar)
        self.session.add.side_effect = self.added.append
        self.session.flush = AsyncMock()
        monkeypatch.setattr(module, "runtime_transaction", transaction)
        monkeypatch.setattr(authority, "require_action_authority", AsyncMock())
        monkeypatch.setattr(module, "hold_to_effect_day", self.move)
        factory = cast(async_sessionmaker[AsyncSession], MagicMock())
        store = EffectStore(factory, management_catalog=self.catalog)
        monkeypatch.setattr(store, "revalidate_execution_locked", AsyncMock())
        return store

    def known(self) -> None:
        kind = "model_requests" if self.work.model_profile == "reasoning" else "tool_attempts"
        setattr(self.work, kind + "_used", 1)
        self.hold.state = "unknown"
        self.previous = EffectIntent(
            company_id=self.work.company_id,
            action_id=self.action.id,
            task_id=self.work.task_id,
            trace_id=self.work.trace_id,
            run_id=self.work.run_id,
            proposal_hash=self.action.proposal_hash,
            intent_fence=1,
            attempt_kind=kind,
            state="outcome_unknown",
            created_at=self.now,
            receipt_json=None,
            verification_json=None,
        )


def boundary(index: int = 1) -> Boundary:
    admission, catalog = case()
    slot = admission.slots[index]
    bound = slot.child.binding
    now = datetime.now(UTC)
    expires = now + timedelta(seconds=60)
    request = registration(bound, slot.work, slot.child.quota)
    values = {
        f"{kind}_{suffix}": getattr(slot.child.quota, kind) if suffix == "limit" else 0
        for kind in ("model_requests", "tool_attempts", "rework_rounds", "plan_revisions")
        for suffix in ("limit", "used", "delegated")
    }
    work = ExecutionWork(
        company_id=bound.company_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        actor_id=bound.actor_id,
        workspace_id=bound.workspace_id,
        run_id=bound.run_id,
        parent_task_id=admission.procedure.binding.task_id,
        registration_json=request.model_dump_json(),
        registration_hash=registration_digest(request),
        workflow_name=bound.workflow_name,
        workflow_version=bound.workflow_version,
        model_profile=bound.model_profile,
        model_registry_version=bound.model_registry_version,
        state="running",
        fence=1,
        worker_id=key("boundary-worker"),
        lease_principal_id=bound.actor_id,
        lease_mode="execute",
        lease_until=expires,
        segment_id=key("boundary-segment"),
        segment_number=1,
        **values,
    )
    lease = ExecutionLease(
        company_id=bound.company_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        actor_id=bound.actor_id,
        workspace_id=bound.workspace_id,
        run_id=bound.run_id,
        workflow_version=bound.workflow_version,
        worker_id=work.worker_id,
        segment_id=work.segment_id,
        fence=1,
        expires_at=expires,
        mode="execute",
    )
    proposal = ActionProposal(
        company_id=bound.company_id,
        action_id=key("boundary-action-" + str(index)),
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        actor_id=bound.actor_id,
        revision=1,
        tool=slot.tool.tool,
        tool_version=slot.tool.tool_version,
        resource=slot.tool.resource,
        parameters={"component": "supplied-negative-only"},
        policy_version="p1",
        price_version="p1",
        estimated_cost_usd=Decimal(".01"),
    )
    action = JournalAction(
        id=proposal.action_id,
        company_id=bound.company_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        proposal_json=proposal.model_dump_json(),
        proposal_hash=action_hash(proposal),
        state="authorized",
        consumed_at=now - timedelta(seconds=1),
    )
    hold = CostHold(
        company_id=bound.company_id,
        action_id=action.id,
        task_id=bound.task_id,
        day=now.date(),
        amount_usd=Decimal(".01"),
        actual_usd=None,
        state="held",
    )
    control = CompanyControl(
        company_id=bound.company_id,
        owner_id=admission.procedure.binding.actor_id,
        daily_cap_usd=Decimal(5),
        work_cap_usd=Decimal(1),
        paused=False,
        policy_version="p1",
        price_version="p1",
    )
    return Boundary(
        catalog,
        work,
        lease,
        VerifiedIdentity(principal_id=bound.actor_id, workspace_id=bound.workspace_id),
        action,
        hold,
        control,
        now,
    )

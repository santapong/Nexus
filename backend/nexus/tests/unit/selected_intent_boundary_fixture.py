"""Supplied-session direct-begin boundary, not current database or selected-proof authority.

TASK: fresh mixed E/EV/sender cannot reserve without exact configured native checks.
OWNED: this fixture and test_selected_intent_boundary.py only.
TESTS: missing/no-op/wrong/subclass guards, binding splices, original-intent replay.
DONE: focused/static checks plus retained pre-gate failures; no database/runtime calls.
RISK: authority boundary; actual runtime authority/management are explicit fixture mocks.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal, cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

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
from nexus.tests.unit.cycle_catalog_fixture import cycle_catalog


class NoOpIntentCheck:
    """Protocol-shaped object with no native selected proof; it must confer no permission."""

    def __init__(self) -> None:
        self.calls = 0

    async def validate(self, *args: object, **kwargs: object) -> None:
        self.calls += 1


@dataclass
class IntentBoundary:
    catalog: PlanAdmissionCatalog
    work: ExecutionWork
    lease: ExecutionLease
    identity: VerifiedIdentity
    proposal: ActionProposal
    action: JournalAction
    hold: CostHold
    control: CompanyControl
    now: datetime
    session: MagicMock = field(default_factory=lambda: MagicMock(spec=AsyncSession))
    previous: EffectIntent | None = None
    added: list[object] = field(default_factory=list)
    hold_move: AsyncMock = field(default_factory=AsyncMock)
    management: AsyncMock = field(default_factory=AsyncMock)
    authority: AsyncMock = field(default_factory=AsyncMock)

    def install(self, monkeypatch: pytest.MonkeyPatch) -> EffectStore:
        """Only the outer current-scope/authority and management gates are supplied mocks."""
        import nexus.execution.effect_store as module
        import nexus.execution.effect_support as authority_module

        @asynccontextmanager
        async def transaction(
            *args: object, **kwargs: object
        ) -> AsyncIterator[tuple[AsyncSession, CompanyControl, MagicMock]]:
            yield cast(AsyncSession, self.session), self.control, MagicMock()

        self.session.get = AsyncMock(side_effect=self.get)
        self.session.scalar = AsyncMock(side_effect=self.scalar)
        self.session.add.side_effect = self.added.append
        self.session.flush = AsyncMock()
        monkeypatch.setattr(module, "runtime_transaction", transaction)
        monkeypatch.setattr(authority_module, "require_action_authority", self.authority)
        monkeypatch.setattr(module, "hold_to_effect_day", self.hold_move)
        store = EffectStore(MagicMock(), management_catalog=self.catalog)
        monkeypatch.setattr(store, "revalidate_execution_locked", self.management)
        return store

    async def get(self, model: type[object], key: object) -> object | None:
        if model is EffectIntent:
            assert key == (self.work.company_id, self.proposal.action_id)
            return self.previous
        if model is JournalAction:
            assert key == self.proposal.action_id
            return self.action
        if model is CostHold:
            assert key == self.proposal.action_id
            return self.hold
        if model is ExecutionAttempt:
            return None
        raise AssertionError(f"Unexpected supplied-session get: {model.__name__}")

    async def scalar(self, statement: object) -> object | None:
        # Inspect actual generated SQL shape, without patching execution-row/lease logic.
        sql = str(statement)
        if "clock_timestamp" in sql:
            return self.now
        if "FROM company_execution_work" in sql:
            assert "FOR UPDATE" in sql
            return self.work
        if "company_effect_intents.action_id" in sql:
            return None
        raise AssertionError("Unexpected supplied-session scalar")

    def known(self) -> EffectIntent:
        """An actual typed previously issued intent; its original fence is immutable."""
        self.work.tool_attempts_used = 1
        self.hold.state = "unknown"
        self.previous = EffectIntent(
            company_id=self.work.company_id,
            action_id=self.proposal.action_id,
            task_id=self.work.task_id,
            trace_id=self.work.trace_id,
            run_id=self.work.run_id,
            proposal_hash=self.action.proposal_hash,
            intent_fence=1,
            attempt_kind="tool_attempts",
            state="outcome_unknown",
            created_at=self.now - timedelta(seconds=2),
            receipt_json=None,
            verification_json=None,
        )
        return self.previous

    def untouched(self, *, issued: bool = False) -> None:
        """Assert no attempt/hold movement/intent mutation occurred in the real begin path."""
        for kind in ("model_requests", "tool_attempts", "rework_rounds", "plan_revisions"):
            assert getattr(self.work, kind + "_used") == int(issued and kind == "tool_attempts")
            assert getattr(self.work, kind + "_delegated") == 0
        assert self.added == []
        assert self.hold.state == ("unknown" if issued else "held")
        assert self.hold.amount_usd == Decimal("0.01") and self.hold.actual_usd is None
        assert self.hold.day == self.now.date()
        assert self.action.state == "authorized"
        assert self.action.consumed_at == self.now - timedelta(seconds=1)
        self.hold_move.assert_not_awaited()
        self.session.flush.assert_not_awaited()


def intent_boundary(verifier: bool = False) -> IntentBoundary:
    """Preserve the selected E/EV fixture API and exact catalog-derived identities."""
    return _intent_boundary("verifier" if verifier else "engineering")


def sender_intent_boundary() -> IntentBoundary:
    """Use the final catalog slot's actual sender binding, quota, tool and resources."""
    return _intent_boundary("sender")


def _intent_boundary(role: Literal["engineering", "verifier", "sender"]) -> IntentBoundary:
    """Actual typed registered work/lease/action descriptors; no selected authority asserted."""
    # Keep this >50-line coherent permanent registration/lease/journal fixture together.
    declared = cycle_catalog()
    catalog = declared.catalog.model_copy(update={"cycle_admission": declared.admission})
    slot = declared.admission.slots[{"engineering": 2, "verifier": 3, "sender": -1}[role]]
    bound, now = slot.child.binding, datetime.now(UTC)
    saved = registration(bound, slot.work, slot.child.quota)
    lease = ExecutionLease(
        company_id=bound.company_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        actor_id=bound.actor_id,
        workspace_id=bound.workspace_id,
        run_id=bound.run_id,
        workflow_version=bound.workflow_version,
        segment_id=UUID(int=801),
        worker_id=UUID(int=802),
        fence=2,
        expires_at=now + timedelta(seconds=30),
        mode="execute",
    )
    work = ExecutionWork(
        company_id=bound.company_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        actor_id=bound.actor_id,
        workspace_id=bound.workspace_id,
        run_id=bound.run_id,
        parent_task_id=declared.admission.procedure.binding.task_id,
        workflow_name=bound.workflow_name,
        workflow_version=bound.workflow_version,
        model_profile=bound.model_profile,
        model_registry_version=bound.model_registry_version,
        registration_json=saved.model_dump_json(),
        registration_hash=registration_digest(saved),
        state="running",
        fence=lease.fence,
        worker_id=lease.worker_id,
        lease_principal_id=lease.actor_id,
        lease_until=lease.expires_at,
        lease_mode=lease.mode,
        segment_number=1,
        segment_id=lease.segment_id,
        waiting_action_id=None,
    )
    for kind in ("model_requests", "tool_attempts", "rework_rounds", "plan_revisions"):
        setattr(work, kind + "_limit", getattr(slot.child.quota, kind))
        setattr(work, kind + "_used", 0)
        setattr(work, kind + "_delegated", 0)
    proposal = ActionProposal(
        company_id=bound.company_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        actor_id=bound.actor_id,
        action_id=UUID(int=803),
        revision=1,
        tool=slot.tool.tool,
        tool_version=slot.tool.tool_version,
        resource=slot.tool.resource,
        parameters={},
        policy_version="p1",
        price_version="p1",
        estimated_cost_usd=Decimal("0.01"),
    )
    action = JournalAction(
        id=proposal.action_id,
        company_id=proposal.company_id,
        task_id=proposal.task_id,
        trace_id=proposal.trace_id,
        proposal_json=proposal.model_dump_json(),
        proposal_hash=action_hash(proposal),
        state="authorized",
        approval_json=None,
        consumed_at=now - timedelta(seconds=1),
    )
    hold = CostHold(
        action_id=proposal.action_id,
        company_id=proposal.company_id,
        task_id=proposal.task_id,
        day=now.date(),
        amount_usd=Decimal("0.01"),
        actual_usd=None,
        state="held",
    )
    control = CompanyControl(
        company_id=bound.company_id,
        owner_id=UUID(int=99),
        policy_version="p1",
        price_version="p1",
        paused=False,
        daily_cap_usd=Decimal(5),
        work_cap_usd=Decimal(1),
    )
    return IntentBoundary(
        catalog,
        work,
        lease,
        VerifiedIdentity(principal_id=lease.actor_id, workspace_id=lease.workspace_id),
        proposal,
        action,
        hold,
        control,
        now,
    )

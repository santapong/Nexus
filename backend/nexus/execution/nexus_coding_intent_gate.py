"""Mandatory concrete full-profile fresh intent routing; unimplemented roles stay denied."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.management.nexus_coding_catalog import validate_nexus_coding_catalog
from nexus.company.management.plan_admission_window import PlanChildWindow
from nexus.execution.intent_checks import BeforeIntentCheck
from nexus.execution.nexus_intent_gate import NexusIntentGate, _bind_nexus_intent_check
from nexus.execution.runtime_contracts import AttemptKind, ExecutionDeniedError, ExecutionLease
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.journal_models import JournalAction

if TYPE_CHECKING:
    from nexus.execution.effect_store import EffectStore

_DENIED = "Fresh coding-family intent requires its installed concrete role checks"


def _installed(effects: EffectStore, work: ExecutionWork) -> None:
    catalog = effects._management_catalog
    if catalog is None:
        raise ExecutionDeniedError(_DENIED)
    admission = validate_nexus_coding_catalog(catalog.nexus_coding_admission, catalog)
    if admission is None:
        raise ExecutionDeniedError(_DENIED)
    slot = next((slot for slot in admission.slots if slot.work.task_id == work.task_id), None)
    # Only installed L/C and the exact concrete published-origin E/EV checks
    # may proceed to the mandatory shape gate; every other role stays denied.
    if slot is None or slot.role not in {"planner", "coder", "engineering", "engineering_check"}:
        raise ExecutionDeniedError(_DENIED)


@dataclass(frozen=True)
class NexusCodingIntentGate:
    """Actual original Nexus L/C gate; no DTO or unimplemented-role permission."""

    original: NexusIntentGate

    @property
    def children(self) -> tuple[PlanChildWindow, ...]:
        """Actual original windows retained through the final native flush clock."""
        return self.original.children

    def require_current(
        self, work: ExecutionWork, action: JournalAction, check: BeforeIntentCheck | None
    ) -> None:
        if type(self.original) is not NexusIntentGate:
            raise ExecutionDeniedError(_DENIED)
        _installed(self.original.effects, work)
        self.original.require_current(work, action, check)

    def validate_time(self, now: datetime) -> None:
        self.original.validate_time(now)


def bind_nexus_coding_intent_check(
    factory: async_sessionmaker[AsyncSession],
    effects: EffectStore,
    work: ExecutionWork,
    lease: ExecutionLease,
    identity: VerifiedIdentity,
    action: JournalAction,
    kind: AttemptKind,
    check: BeforeIntentCheck | None,
    *,
    now: datetime,
) -> NexusCodingIntentGate:
    """Only exact L or store-issued C composites are installed for this full profile."""
    try:
        _installed(effects, work)
        gate = NexusCodingIntentGate(
            _bind_nexus_intent_check(
                factory,
                effects,
                work,
                lease,
                identity,
                action,
                kind,
                check,
                now=now,
            )
        )
        gate.require_current(work, action, check)
        gate.validate_time(now)
        return gate
    except (ValueError, TypeError, AttributeError) as error:
        raise ExecutionDeniedError(_DENIED) from error

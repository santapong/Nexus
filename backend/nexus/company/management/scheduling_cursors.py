"""Opaque namespaced cursor ranges and exact paged scan identities under CompanyControl."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.event_models import BrainEvent, BrainEventCursor
from nexus.company.management.base import ValueContract
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.control_models import ManagementControlEvent
from nexus.company.management.plan_models import ManagementPlanHead
from nexus.company.management.scheduling_contracts import DueWake, ScanRequest
from nexus.company.management.transactions import ManagementDeniedError

BRAIN_CONSUMER = "nexus.management.brain"
CONTROL_CONSUMER = "nexus.management.control"


class _PlanPoint(ValueContract):
    plan_id: UUID
    revision_id: UUID
    decision_id: UUID | None
    procedure_id: UUID | None
    state: str


class _PlanIndex(ValueContract):
    plans: tuple[_PlanPoint, ...]


class _WakeIdentity(ValueContract):
    request_sha256: str
    stream: str
    event_id: UUID | None
    sequence: int


@dataclass(frozen=True)
class ScanWindow:
    """Fresh native plan index/ranges; not caller-supplied state or an effect permit."""

    brain: BrainEventCursor
    control: BrainEventCursor
    brain_end: int
    control_end: int
    plan_sha256: str
    event_key: str
    due_bucket: datetime | None


async def event_key(
    session: AsyncSession, company_id: UUID, request: ScanRequest, digest: str
) -> str:
    """An immutable actual event or canonical due bucket plus exact selector defines replay."""
    wake = request.wake
    if isinstance(wake, DueWake):
        return "scan:" + canonical_sha256(
            _WakeIdentity(request_sha256=digest, stream="due", event_id=None, sequence=0)
        )
    row: BrainEvent | ManagementControlEvent | None
    if wake.stream == "brain":
        row = await session.get(BrainEvent, (company_id, wake.event_id))
    else:
        row = await session.get(ManagementControlEvent, (company_id, wake.event_id))
    if row is None:
        raise ManagementDeniedError("Scheduler trigger is unavailable")
    return "scan:" + canonical_sha256(
        _WakeIdentity(
            request_sha256=digest, stream=wake.stream, event_id=row.event_id, sequence=row.sequence
        )
    )


async def _cursor(
    session: AsyncSession, company_id: UUID, consumer: str, recipe: str
) -> BrainEventCursor:
    cursor = await session.get(BrainEventCursor, (company_id, consumer, recipe))
    if cursor is None:
        cursor = BrainEventCursor(
            company_id=company_id, consumer=consumer, recipe_version=recipe, last_sequence=0
        )
        session.add(cursor)
        await session.flush()
    return cursor


async def plan_index_sha256(session: AsyncSession, company_id: UUID) -> str:
    rows = tuple(
        (
            await session.scalars(
                select(ManagementPlanHead)
                .where(ManagementPlanHead.company_id == company_id)
                .order_by(ManagementPlanHead.plan_id)
            )
        ).all()
    )
    return canonical_sha256(
        _PlanIndex(
            plans=tuple(
                _PlanPoint(
                    plan_id=row.plan_id,
                    revision_id=row.current_revision_id,
                    decision_id=row.decision_id,
                    procedure_id=row.procedure_id,
                    state=row.state,
                )
                for row in rows
            )
        )
    )


async def scan_window(
    session: AsyncSession,
    company_id: UUID,
    request: ScanRequest,
    recipe: str,
    key: str,
    now: datetime,
) -> ScanWindow:
    """Changed range/index requires a new page request, preventing lost unseen events."""
    brain = await _cursor(session, company_id, BRAIN_CONSUMER, recipe)
    control = await _cursor(session, company_id, CONTROL_CONSUMER, recipe)
    end_brain = (
        await session.scalar(
            select(func.max(BrainEvent.sequence)).where(BrainEvent.company_id == company_id)
        )
        or 0
    )
    end_control = (
        await session.scalar(
            select(func.max(ManagementControlEvent.sequence)).where(
                ManagementControlEvent.company_id == company_id
            )
        )
        or 0
    )
    index = await plan_index_sha256(session, company_id)
    if request.page is not None and (
        request.page.brain_sequence != end_brain
        or request.page.control_sequence != end_control
        or request.page.plan_snapshot_sha256 != index
    ):
        raise ManagementDeniedError("Scheduler page range or current plan index changed")
    bucket = None
    if isinstance(request.wake, DueWake):
        bucket = request.wake.bucket.astimezone(UTC)
        current = now.astimezone(UTC).replace(second=0, microsecond=0)
        if bucket not in (current, current - timedelta(minutes=1)):
            raise ManagementDeniedError("Scheduler due bucket is not current or previous minute")
    return ScanWindow(brain, control, end_brain, end_control, index, key, bucket)

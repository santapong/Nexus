"""Management authority audit is independent of Brain-resource event semantics."""

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID, uuid5

from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope
from nexus.company.management.base import (
    ManagementContract,
    Revision,
    RevisionRef,
    Symbol,
    ValueContract,
    require_company,
)
from nexus.company.management.canonical import canonical_json
from nexus.company.management.control_models import ManagementControlEvent as ControlEventRow
from nexus.company.management.control_support import (
    ManagementConflictError,
    mandate_record,
    mandate_ref,
)
from nexus.company.management.goals import GoalRevisionRef
from nexus.company.management.governance import CharterRevisionRef
from nexus.company.management.governance_models import (
    ManagementCharterRevision,
    ManagementGoalRevision,
    ManagementMandateRevision,
)
from nexus.company.management.transactions import ManagementDeniedError
from nexus.harness.journal_models import CompanyControl


class MandateSubject(ValueContract):
    kind: Literal["mandate"] = "mandate"
    current: RevisionRef
    previous: RevisionRef | None = None


class CharterSubject(ValueContract):
    kind: Literal["charter"] = "charter"
    current: CharterRevisionRef
    previous: CharterRevisionRef | None = None

    @model_validator(mode="after")
    def exact_department(self) -> Self:
        if self.previous is not None and self.previous.department_id != self.current.department_id:
            raise ValueError("Charter audit cannot splice another department head")
        return self


class GoalSubject(ValueContract):
    kind: Literal["goal"] = "goal"
    current: GoalRevisionRef
    previous: GoalRevisionRef | None = None

    @model_validator(mode="after")
    def exact_goal(self) -> Self:
        if self.previous is not None and self.previous.goal_id != self.current.goal_id:
            raise ValueError("Goal audit cannot splice another logical goal head")
        return self


ControlSubject = Annotated[
    MandateSubject | CharterSubject | GoalSubject, Field(discriminator="kind")
]


class ManagementControlEvent(ManagementContract):
    event_id: UUID
    sequence: Revision
    kind: Literal["publish", "revoke", "reactivate"]
    subject: ControlSubject
    owner_id: UUID
    operation_id: UUID
    trace_id: UUID
    deduplication_key: Symbol
    recorded_at: AwareDatetime

    @model_validator(mode="after")
    def exact_head_transition(self) -> Self:
        require_company(self.company_id, self.subject.current, self.subject.previous)
        if self.kind in {"revoke", "reactivate"} and self.subject.previous != self.subject.current:
            raise ValueError("Activity audit must retain the exact current subject revision")
        if (
            self.kind == "publish"
            and self.subject.previous is not None
            and self.subject.previous == self.subject.current
        ):
            raise ValueError("A new publication event must change its exact revision")
        return self


def control_event_key(scope: CompanyControlScope, kind: str, subject: ControlSubject) -> str:
    identity = f"{scope.operation_id}:{kind}:{canonical_json(subject)}"
    return f"management:{uuid5(scope.company_id, identity)}"


async def _subject_ref(
    session: AsyncSession, row: ControlEventRow, revision_id: UUID, kind: str
) -> RevisionRef | CharterRevisionRef | GoalRevisionRef:
    if kind == "mandate":
        value = await session.get(ManagementMandateRevision, (row.company_id, revision_id))
        if value is not None:
            return mandate_ref(mandate_record(value))
    elif kind == "charter":
        charter = await session.get(ManagementCharterRevision, (row.company_id, revision_id))
        if charter is not None:
            return CharterRevisionRef(
                company_id=row.company_id,
                revision_id=revision_id,
                department_id=charter.department_id,
                version=charter.version,
                sha256=charter.sha256,
            )
    elif kind == "goal":
        goal = await session.get(ManagementGoalRevision, (row.company_id, revision_id))
        if goal is not None:
            return GoalRevisionRef(
                company_id=row.company_id,
                revision_id=revision_id,
                goal_id=goal.goal_id,
                version=goal.version,
                sha256=goal.sha256,
            )
    raise ManagementDeniedError("Management audit subject is unavailable")


async def _event_record(session: AsyncSession, row: ControlEventRow) -> ManagementControlEvent:
    kind = row.subject_kind
    current_id: UUID | None = getattr(row, f"{kind}_revision_id", None)
    previous_id: UUID | None = getattr(row, f"previous_{kind}_revision_id", None)
    if current_id is None or kind not in {"mandate", "charter", "goal"}:
        raise ManagementDeniedError("Management audit subject is unavailable")
    current = await _subject_ref(session, row, current_id, kind)
    previous = await _subject_ref(session, row, previous_id, kind) if previous_id else None
    return ManagementControlEvent.model_validate(
        {
            "company_id": row.company_id,
            "event_id": row.event_id,
            "sequence": row.sequence,
            "kind": row.kind,
            "subject": {"kind": kind, "current": current, "previous": previous},
            "owner_id": row.owner_id,
            "operation_id": row.operation_id,
            "trace_id": row.trace_id,
            "deduplication_key": row.deduplication_key,
            "recorded_at": row.recorded_at,
        }
    )


async def find_control_event(
    session: AsyncSession, scope: CompanyControlScope, kind: str, subject: ControlSubject
) -> ManagementControlEvent | None:
    key = control_event_key(scope, kind, subject)
    row = await session.scalar(
        select(ControlEventRow).where(
            ControlEventRow.company_id == scope.company_id, ControlEventRow.deduplication_key == key
        )
    )
    if row is None:
        return None
    record = await _event_record(session, row)
    if (record.subject, record.kind, record.owner_id, record.operation_id, record.trace_id) != (
        subject,
        kind,
        scope.principal_id,
        scope.operation_id,
        scope.trace_id,
    ):
        raise ManagementConflictError("Management audit identity cannot be rebound")
    return record


async def append_control_event(
    session: AsyncSession,
    scope: CompanyControlScope,
    control: CompanyControl,
    kind: Literal["publish", "revoke", "reactivate"],
    subject: ControlSubject,
    now: datetime,
) -> ManagementControlEvent:
    if not session.in_transaction() or (control.company_id, control.owner_id) != (
        scope.company_id,
        scope.principal_id,
    ):
        raise ManagementDeniedError("Management audit needs its current-owner transaction")
    previous = await find_control_event(session, scope, kind, subject)
    if previous is not None:
        return previous
    sequence = (
        await session.scalar(
            select(func.max(ControlEventRow.sequence)).where(
                ControlEventRow.company_id == scope.company_id
            )
        )
        or 0
    ) + 1
    key = control_event_key(scope, kind, subject)
    result = ManagementControlEvent(
        company_id=scope.company_id,
        event_id=uuid5(scope.company_id, key),
        sequence=sequence,
        kind=kind,
        subject=subject,
        owner_id=control.owner_id,
        operation_id=scope.operation_id,
        trace_id=scope.trace_id,
        deduplication_key=key,
        recorded_at=now,
    )
    row = ControlEventRow(
        company_id=scope.company_id,
        event_id=result.event_id,
        sequence=sequence,
        kind=kind,
        subject_kind=subject.kind,
        owner_id=control.owner_id,
        operation_id=scope.operation_id,
        trace_id=scope.trace_id,
        deduplication_key=key,
        recorded_at=now,
    )
    setattr(row, f"{subject.kind}_revision_id", subject.current.revision_id)
    setattr(
        row,
        f"previous_{subject.kind}_revision_id",
        subject.previous.revision_id if subject.previous else None,
    )
    if isinstance(subject, CharterSubject):
        row.department_id = subject.current.department_id
    elif isinstance(subject, GoalSubject):
        row.goal_id = subject.current.goal_id
    session.add(row)
    await session.flush()
    return result

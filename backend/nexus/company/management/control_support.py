"""Current owner-scope control projections and exact native active references."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope
from nexus.company.brain.scope_support import BrainConflictError
from nexus.company.contracts.company import CompanyMandate, DepartmentCharter
from nexus.company.directory_models import DirectoryMembership
from nexus.company.management.base import RevisionRef
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.governance import CharterRevision, CharterRevisionRef, MandateRevision
from nexus.company.management.governance_models import (
    ManagementCharterHead,
    ManagementCharterRevision,
    ManagementMandateHead,
    ManagementMandateRevision,
)
from nexus.company.management.transactions import ManagementDeniedError
from nexus.harness.journal_models import CompanyControl


class ManagementConflictError(BrainConflictError):
    """A known management revision/payload changed and needs explicit refresh."""


def mandate_record(row: ManagementMandateRevision) -> MandateRevision:
    return MandateRevision(
        company_id=row.company_id,
        revision_id=row.revision_id,
        version=row.version,
        sha256=row.sha256,
        mandate=CompanyMandate.model_validate_json(row.payload_json),
        recorded_by=row.recorded_by,
        recorded_at=row.recorded_at,
    )


def mandate_ref(row: MandateRevision) -> RevisionRef:
    return RevisionRef.model_validate_json(
        row.model_dump_json(include=set(RevisionRef.model_fields))
    )


async def charter_record(session: AsyncSession, row: ManagementCharterRevision) -> CharterRevision:
    parent = await session.get(ManagementMandateRevision, (row.company_id, row.mandate_revision_id))
    if parent is None:
        raise ManagementDeniedError("Registered management reference is unavailable")
    return CharterRevision(
        company_id=row.company_id,
        revision_id=row.revision_id,
        department_id=row.department_id,
        version=row.version,
        sha256=row.sha256,
        charter=DepartmentCharter.model_validate_json(row.payload_json),
        mandate=mandate_ref(mandate_record(parent)),
        recorded_by=row.recorded_by,
        recorded_at=row.recorded_at,
    )


def charter_ref(row: CharterRevision) -> CharterRevisionRef:
    return CharterRevisionRef.model_validate_json(
        row.model_dump_json(include=set(CharterRevisionRef.model_fields))
    )


def require_cas(current: UUID | None, expected: UUID | None) -> None:
    if current != expected:
        raise ManagementConflictError("Current management head changed; refresh before publication")


async def db_clock(session: AsyncSession) -> datetime:
    now: datetime | None = await session.scalar(select(func.clock_timestamp()))
    if now is None or now.utcoffset() is None:
        raise ManagementDeniedError("Current management clock is unavailable")
    return now


async def require_member(
    session: AsyncSession, control: CompanyControl, principal_id: UUID
) -> None:
    member = await session.get(DirectoryMembership, (control.company_id, principal_id))
    if (
        member is None
        or not member.membership_active
        or not member.principal_active
        or (member.role == "owner" and member.principal_id != control.owner_id)
    ):
        raise ManagementDeniedError("Referenced management member is unavailable")


async def current_mandate(
    session: AsyncSession,
    scope: CompanyControlScope,
    reference: RevisionRef,
    *,
    active: bool = True,
) -> MandateRevision:
    head = await session.get(ManagementMandateHead, scope.company_id)
    row = await session.get(ManagementMandateRevision, (scope.company_id, reference.revision_id))
    if (
        reference.company_id != scope.company_id
        or head is None
        or row is None
        or (head.current_revision_id != reference.revision_id or (active and not head.active))
    ):
        raise ManagementDeniedError("Current management mandate is unavailable")
    record = mandate_record(row)
    if mandate_ref(record) != reference:
        raise ManagementDeniedError("Exact management mandate is unavailable")
    return record


async def current_charter(
    session: AsyncSession,
    scope: CompanyControlScope,
    reference: CharterRevisionRef,
    *,
    active: bool = True,
) -> CharterRevision:
    head = await session.get(ManagementCharterHead, (scope.company_id, reference.department_id))
    row = await session.get(ManagementCharterRevision, (scope.company_id, reference.revision_id))
    if (
        reference.company_id != scope.company_id
        or head is None
        or row is None
        or (head.current_revision_id != reference.revision_id or (active and not head.active))
    ):
        raise ManagementDeniedError("Current management charter is unavailable")
    record = await charter_record(session, row)
    if charter_ref(record) != reference:
        raise ManagementDeniedError("Exact management charter is unavailable")
    return record


def validate_mandate(data: CompanyMandate, control: CompanyControl) -> None:
    if (data.company_id, data.owner_id) != (control.company_id, control.owner_id):
        raise ManagementDeniedError("Management mandate does not match its current owner")
    if data.oversight != "supervised" or data.self_improvement_enabled is not False:
        raise ManagementDeniedError("Management authority promotion is not admitted")
    if data.work_cap_usd > data.daily_cap_usd:
        raise ManagementDeniedError("Declared management limits are inconsistent")
    if len(data.goals) > 100 or len(set(data.goals)) != len(data.goals):
        raise ManagementDeniedError("Management goal declaration exceeds its boundary")


def same_mandate(record: MandateRevision, data: CompanyMandate) -> None:
    if record.sha256 != canonical_sha256(data):
        raise ManagementConflictError("Management mandate version cannot be rebound")

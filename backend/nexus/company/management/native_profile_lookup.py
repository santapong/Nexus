"""Resolve existing owner report/commitment rows; decoded references grant no permission."""

from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.commitment_contracts import commitment_reference
from nexus.company.management.commitment_support import (
    commitment_record,
    require_commitment_binding,
)
from nexus.company.management.native_profile_contracts import (
    NativeReportOperatingProfile,
    NativeReportProfileRef,
)
from nexus.company.management.operating_report_contracts import SavedOperatingReport
from nexus.company.management.operating_report_store import stored_report
from nexus.company.management.operation_models import (
    ManagementCommitmentHead,
    ManagementCommitmentRevision,
    ManagementReportSnapshot,
)
from nexus.company.management.transactions import ManagementDeniedError
from nexus.harness.journal_models import CompanyControl


async def report_record(
    session: AsyncSession, company_id: UUID, report_id: UUID
) -> SavedOperatingReport:
    """Load an actual immutable report row and validate its native envelope/hash."""
    row = await session.get(ManagementReportSnapshot, (company_id, report_id))
    if row is None:
        raise ManagementDeniedError("Native profile report is unavailable")
    return stored_report(row)


async def load_profile(
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    reference: NativeReportProfileRef,
    *,
    require_due: bool,
    now: datetime,
) -> tuple[NativeReportOperatingProfile, SavedOperatingReport]:
    """Revalidate actual owner records/current pair and retain exact due precision."""
    saved = await report_record(session, scope.company_id, reference.report_id)
    if (
        reference.company_id != scope.company_id
        or saved.created_by != control.owner_id
        or canonical_sha256(saved) != reference.report_sha256
        or canonical_sha256(saved.selection) != reference.selection_sha256
    ):
        raise ManagementDeniedError("Native report profile differs from its actual owner selection")
    head = await session.get(
        ManagementCommitmentHead, (scope.company_id, reference.commitment.commitment_id)
    )
    row = await session.get(
        ManagementCommitmentRevision, (scope.company_id, reference.commitment.revision_id)
    )
    if head is None or row is None or head.current_revision_id != row.revision_id:
        raise ManagementDeniedError("Native profile commitment is no longer current")
    commitment = commitment_record(row)
    definition = commitment.definition
    if (
        commitment_reference(commitment) != reference.commitment
        or commitment.recorded_by != control.owner_id
        or definition.plan != saved.selection.plan
        or set(definition.work) != {saved.selection.author, saved.selection.verifier}
    ):
        raise ManagementDeniedError("Native profile commitment does not bind the exact report pair")
    await require_commitment_binding(session, control, scope, definition)
    due = definition.due
    if require_due and (
        due.actionable_basis != "operator_explicit"
        or due.actionable_at is None
        or due.actionable_at > now
    ):
        raise ManagementDeniedError("Native profile has no actual actionable owner due instant")
    return NativeReportOperatingProfile(
        company_id=scope.company_id, reference=reference, selection=saved.selection, due=due
    ), saved

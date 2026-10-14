"""Persist the exact owner-produced immutable report envelope; no work authority."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope, PrincipalAccess, VerifiedIdentity
from nexus.company.brain.access_support import require_resources
from nexus.company.brain.base import BrainReadScope
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.operating_report_contracts import (
    ReportData,
    ReportSelection,
    SavedOperatingReport,
)
from nexus.company.management.operating_report_projection import owner_projection
from nexus.company.management.operation_models import ManagementReportSnapshot
from nexus.execution.runtime_support import db_now


async def persist_snapshot(
    session: AsyncSession,
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    current: BrainReadScope,
    selection: ReportSelection,
    data: ReportData,
    access: PrincipalAccess,
    period_start: datetime,
    period_end: datetime,
) -> SavedOperatingReport:
    observed = await db_now(session)
    identifier = uuid4()
    grants = await require_resources(
        session, current, data.required_resource_ids, await db_now(session)
    )
    projected = owner_projection(
        data, access, identifier, period_start, period_end, observed, grants
    )
    record = SavedOperatingReport(
        company_id=scope.company_id,
        report_id=identifier,
        selection=selection,
        period_start=period_start,
        period_end=period_end,
        observed_at=observed,
        created_by=identity.principal_id,
        data=data,
        projection=projected,
        data_sha256=canonical_sha256(data),
    )
    session.add(
        ManagementReportSnapshot(
            company_id=scope.company_id,
            report_id=identifier,
            sha256=canonical_sha256(record),
            snapshot_json=record.model_dump_json(),
            created_by=identity.principal_id,
            period_start=period_start,
            period_end=period_end,
            recorded_at=observed,
        )
    )
    await session.flush()
    return record

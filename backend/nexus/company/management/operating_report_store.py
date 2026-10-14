"""Owner-authored immutable native report snapshots and exact approved protected sharing."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.access_support import require_resources
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.scope_support import require_brain_scope
from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.check_contracts import StructuredInternalReport
from nexus.company.management.operating_report_author import require_report_author
from nexus.company.management.operating_report_capture import capture_data
from nexus.company.management.operating_report_contracts import (
    SavedOperatingReport,
)
from nexus.company.management.operating_report_inputs import author_input_references
from nexus.company.management.operating_report_persistence import persist_snapshot
from nexus.company.management.operating_report_read import final_report_read
from nexus.company.management.operating_report_selection import resolve_selection
from nexus.company.management.operating_report_sharing import require_report_share
from nexus.company.management.operation_models import ManagementReportSnapshot
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.company.management.report_rules import OperatingProjection
from nexus.company.management.transactions import management_owner_transaction
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import CompanyControl


def stored_report(row: ManagementReportSnapshot) -> SavedOperatingReport:
    result = SavedOperatingReport.model_validate_json(row.snapshot_json)
    require_acceptance(
        canonical_sha256(result) == row.sha256
        and (
            result.company_id,
            result.report_id,
            result.period_start,
            result.period_end,
            result.created_by,
            result.observed_at,
        )
        == (
            row.company_id,
            row.report_id,
            row.period_start,
            row.period_end,
            row.created_by,
            row.recorded_at,
        )
    )
    return result


class OperatingReportStore:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        catalog: PlanAdmissionCatalog,
        artifacts: BoundedArtifactReader,
        freshness: RegisteredSourceFreshness,
    ) -> None:
        self.factory, self.catalog, self.artifacts, self.freshness = (
            factory,
            catalog,
            artifacts,
            freshness,
        )

    async def save_snapshot(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        plan_revision_id: UUID,
        author_task_id: UUID,
        selected_task_ids: tuple[UUID, ...],
        *,
        period_start: datetime,
        period_end: datetime,
    ) -> SavedOperatingReport:
        require_acceptance(
            period_start.utcoffset() is not None
            and period_end.utcoffset() is not None
            and period_end > period_start
        )
        async with management_owner_transaction(
            self.factory, scope, identity, allow_paused=True
        ) as (session, control, _):
            current = BrainReadScope(
                company_id=scope.company_id,
                workspace_id=identity.workspace_id,
                principal_id=identity.principal_id,
                operation_id=scope.operation_id,
                trace_id=scope.trace_id,
            )
            access = await require_brain_scope(session, control, current, identity, owner=True)
            selection = await resolve_selection(
                session, scope.company_id, plan_revision_id, author_task_id, selected_task_ids
            )
            data = await capture_data(
                session,
                control,
                current,
                identity,
                selection,
                self.catalog,
                self.artifacts,
                self.freshness,
            )
            record = await persist_snapshot(
                session, scope, identity, current, selection, data, access, period_start, period_end
            )
            await require_brain_scope(session, control, current, identity, owner=True)
            await require_report_resources(session, current, data.required_resource_ids)
            return record

    async def get_saved(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        report_id: UUID,
    ) -> SavedOperatingReport | None:
        """Owner-only immutable historical snapshot; observed_at does not imply currentness."""
        async with management_owner_transaction(
            self.factory, scope, identity, allow_paused=True
        ) as (session, control, _):
            row = await session.get(ManagementReportSnapshot, (scope.company_id, report_id))
            if row is None:
                return None
            record = stored_report(row)
            require_acceptance(record.created_by == control.owner_id)
            current = BrainReadScope(
                company_id=scope.company_id,
                workspace_id=identity.workspace_id,
                principal_id=identity.principal_id,
                operation_id=scope.operation_id,
                trace_id=scope.trace_id,
            )
            await require_brain_scope(session, control, current, identity, owner=True)
            await require_report_resources(session, current, record.data.required_resource_ids)
            return record

    async def prepare_author_output(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        report_id: UUID,
    ) -> SavedOperatingReport:
        """Read exact current selected facts for the actual author before an output exists."""
        await require_brain_scope(session, control, scope, identity)
        row = await session.get(ManagementReportSnapshot, (scope.company_id, report_id))
        require_acceptance(row is not None)
        assert row is not None
        record = stored_report(row)
        await require_report_author(session, control, scope, identity, record)
        data = await capture_data(
            session,
            control,
            scope,
            identity,
            record.selection,
            self.catalog,
            self.artifacts,
            self.freshness,
        )
        require_acceptance(canonical_sha256(data) == record.data_sha256)
        await final_report_read(session, control, scope, identity, data, None, self.freshness)
        return record

    async def prepare_author_inputs(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        report_id: UUID,
    ) -> tuple[SavedOperatingReport, tuple[ArtifactRevisionRef, ...]]:
        """Exact source/proof input roots for this actual author; returns no issuance permit."""
        record = await self.prepare_author_output(session, control, scope, identity, report_id)
        references = await author_input_references(
            session,
            control,
            scope,
            identity,
            record,
            self.artifacts,
            self.freshness,
        )
        current = await self.prepare_author_output(session, control, scope, identity, report_id)
        require_acceptance(current == record)
        return current, references

    async def current_projection(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        declared: StructuredInternalReport,
        *,
        output: ArtifactRevisionRef,
    ) -> OperatingProjection | None:
        await require_brain_scope(session, control, scope, identity)
        row = await session.get(
            ManagementReportSnapshot, (scope.company_id, declared.operating.snapshot.report_id)
        )
        if row is None:
            return None
        record = stored_report(row)
        require_acceptance(record.created_by == control.owner_id)
        await require_report_share(
            session, control, scope, identity, record, output, self.artifacts, self.freshness
        )
        artifact = await session.get(
            BrainArtifactRevision, (scope.company_id, output.artifact_revision_id)
        )
        require_acceptance(artifact is not None and len(artifact.raw_text.encode()) <= 262144)
        assert artifact is not None
        require_acceptance(
            StructuredInternalReport.model_validate_json(artifact.raw_text) == declared
        )
        data = await capture_data(
            session,
            control,
            scope,
            identity,
            record.selection,
            self.catalog,
            self.artifacts,
            self.freshness,
        )
        await require_report_resources(session, scope, record.data.required_resource_ids)
        if canonical_sha256(data) != record.data_sha256:
            return None
        await final_report_read(session, control, scope, identity, data, output, self.freshness)
        return record.projection


async def require_report_resources(
    session: AsyncSession, scope: BrainReadScope, ids: tuple[UUID, ...]
) -> None:
    grants = await require_resources(session, scope, ids, await db_now(session))
    final = await db_now(session)
    require_acceptance(all(row.expires_at is None or row.expires_at > final for row in grants))

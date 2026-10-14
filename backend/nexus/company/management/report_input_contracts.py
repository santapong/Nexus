"""Public production report input reader ABIs and exact native author registration binding."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.retrieval import CitationHandle
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.check_contracts import StructuredInternalReport
from nexus.company.management.plans import RunBinding
from nexus.company.management.report_input_sources import ReportByteReader
from nexus.company.management.report_rules import OperatingProjection
from nexus.execution.runtime_contracts import ExecutionRegistration
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import registration_digest
from nexus.harness.journal_models import CompanyControl


class ProtectedReportReader(ReportByteReader, Protocol):
    async def citation_handles(
        self,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        ids: tuple[UUID, ...],
        *,
        include_history: bool,
    ) -> tuple[CitationHandle, ...]: ...

    async def revalidate_artifact_reference(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        reference: ArtifactRevisionRef,
        now: datetime,
    ) -> None: ...


class OperatingReportReader(Protocol):
    """Server-only native report/ledger reader; declared output is a selector, never authority.

    It must authorize the actual signed reader, resolve the immutable saved report
    and current selected facts, and preserve its observed-at only while those
    facts match. A missing or unavailable projection remains unknown. This ABI
    cannot be satisfied by substituting the model's report.operating value.
    """

    async def current_projection(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        declared: StructuredInternalReport,
        *,
        output: ArtifactRevisionRef,
    ) -> OperatingProjection | None: ...


def native_author(row: ExecutionWork) -> tuple[RunBinding, ExecutionRegistration]:
    """Bind exact native author fields and recomputed immutable M1 registration."""
    binding = RunBinding(
        company_id=row.company_id,
        workspace_id=row.workspace_id,
        actor_id=row.actor_id,
        task_id=row.task_id,
        trace_id=row.trace_id,
        run_id=row.run_id,
        workflow_name=row.workflow_name,
        workflow_version=row.workflow_version,
        model_profile=row.model_profile,
        model_registry_version=row.model_registry_version,
    )
    registration = ExecutionRegistration.model_validate_json(row.registration_json)
    require_acceptance(registration_digest(registration) == row.registration_hash)
    require_acceptance(
        (
            registration.work.company_id,
            registration.work.task_id,
            registration.work.trace_id,
            registration.run_id,
            registration.workflow_name,
            registration.workflow_version,
            registration.model_profile,
            registration.model_registry_version,
        )
        == (
            binding.company_id,
            binding.task_id,
            binding.trace_id,
            binding.run_id,
            binding.workflow_name,
            binding.workflow_version,
            binding.model_profile,
            binding.model_registry_version,
        )
    )
    return binding, registration

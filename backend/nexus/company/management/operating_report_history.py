"""Actual acceptance history stays visible; only independently current proof becomes accepted."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.acceptance import WorkAcceptance
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.acceptance_models import (
    ManagementAcceptanceInvalidation,
    ManagementWorkAcceptance,
)
from nexus.company.management.acceptance_persistence import acceptance_record
from nexus.company.management.eligibility_rules import AcceptedWork, PublishedAcceptance
from nexus.company.management.report_inputs import native_author
from nexus.execution.management_checks import current_accepted_work
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import snapshot
from nexus.harness.journal_models import CompanyControl


async def work_history(
    session: AsyncSession,
    control: CompanyControl,
    reader: ExecutionWork,
    work: ExecutionWork,
    identity: VerifiedIdentity,
    artifacts: BoundedArtifactReader,
    freshness: RegisteredSourceFreshness,
) -> tuple[AcceptedWork, tuple[ArtifactRevisionRef, ...]]:
    record, invalidated = await saved_history(session, work)
    current = (
        await current_accepted_work(session, control, reader, work, identity, artifacts, freshness)
        if record and record.verdict == "pass"
        else None
    )
    native = snapshot(work)

    binding, _ = native_author(work)
    declared = AcceptedWork(
        company_id=work.company_id,
        work=binding,
        work_snapshot_sha256=work.registration_hash,
        criterion_ids=native.registration.work.acceptance,
        publication=PublishedAcceptance(
            company_id=work.company_id,
            acceptance=record,
            trusted_proofs_resolved=current is not None,
            invalidated=invalidated
            or bool(record and record.verdict == "pass" and current is None),
        ),
    )
    references = tuple(proof.result_artifact for proof in record.proofs) if record else ()
    return declared, references


async def saved_history(
    session: AsyncSession, work: ExecutionWork
) -> tuple[WorkAcceptance | None, bool]:
    row = await session.scalar(
        select(ManagementWorkAcceptance)
        .where(
            ManagementWorkAcceptance.company_id == work.company_id,
            ManagementWorkAcceptance.author_task_id == work.task_id,
            ManagementWorkAcceptance.author_run_id == work.run_id,
        )
        .order_by(
            ManagementWorkAcceptance.recorded_at.desc(),
            ManagementWorkAcceptance.acceptance_id.desc(),
        )
        .limit(1)
    )
    record = acceptance_record(row) if row else None
    invalidated = (
        bool(
            await session.scalar(
                select(ManagementAcceptanceInvalidation.invalidation_id)
                .where(
                    ManagementAcceptanceInvalidation.company_id == work.company_id,
                    ManagementAcceptanceInvalidation.acceptance_id == record.acceptance_id,
                )
                .limit(1)
            )
        )
        if record
        else False
    )
    return record, invalidated

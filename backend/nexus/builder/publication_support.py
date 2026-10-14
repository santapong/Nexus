"""Actual issuance, full input closure and every recipient window precede result publication."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.builder.execution_contracts import BuilderRunResult
from nexus.builder.source_guard import BuilderSourceGuard
from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.access_models import BrainResourceAccess
from nexus.company.brain.access_support import require_resources
from nexus.company.brain.artifact_input_models import BrainArtifactInput, BrainArtifactResourceInput
from nexus.company.brain.claims import DerivationRecord
from nexus.company.brain.derivation_models import BrainDerivation, BrainDerivationSource
from nexus.company.brain.retrieval_records import contributors
from nexus.company.brain.source_models import BrainArtifactRevision, BrainSourceRevision
from nexus.company.brain.sources import ArtifactRevisionRef, SourceRevisionRef
from nexus.company.contracts.actions import ActionProposal
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_models import EffectIntent
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import JournalAction


async def require_publication_intent(
    session: AsyncSession,
    lease: ExecutionLease,
    result: BuilderRunResult,
    guard: BuilderSourceGuard,
    target: ResourceRef,
) -> None:
    job = result.spec.job
    intent = await session.get(EffectIntent, (lease.company_id, job.action_id))
    action = await session.get(JournalAction, job.action_id)
    named = tuple(
        row.resource for row in guard.catalog.resources if row.symbol == job.resource_symbol
    )
    if (
        result.spec != guard.spec
        or result.spec.output_resource != target
        or named != (target,)
        or intent is None
        or action is None
        or action.proposal_hash != result.proposal_sha256
        or ActionProposal.model_validate_json(action.proposal_json).parameters
        != result.spec.model_dump(mode="json")
        or (
            intent.proposal_hash,
            intent.intent_fence,
            intent.run_id,
            intent.task_id,
            intent.trace_id,
        )
        != (result.proposal_sha256, result.intent_fence, lease.run_id, job.task_id, job.trace_id)
        or intent.state not in {"intent", "outcome_unknown"}
    ):
        raise ValueError("Builder protected artifact differs from exact native issuance/target")


async def publication_inputs(
    session: AsyncSession,
    guard: BuilderSourceGuard,
) -> tuple[tuple[BrainArtifactRevision, ...], tuple[SourceRevisionRef, ...], tuple[UUID, ...]]:
    references = (
        guard.source.metadata,
        *((guard.spec.protected_patch,) if guard.spec.protected_patch else ()),
    )
    originals = []
    sources: dict[UUID, SourceRevisionRef] = {}
    resources: set[UUID] = set()
    for reference in references:
        artifact = await session.get(
            BrainArtifactRevision, (reference.company_id, reference.artifact_revision_id)
        )
        if artifact is None:
            raise ValueError("Builder complete input artifact is unavailable")
        roots = tuple(
            (
                await session.scalars(
                    select(BrainSourceRevision.source_revision_id).where(
                        BrainSourceRevision.company_id == reference.company_id,
                        BrainSourceRevision.artifact_revision_id == reference.artifact_revision_id,
                    )
                )
            ).all()
        )
        if len(roots) != 1:
            raise ValueError("Builder registered input source origin is ambiguous")
        refs, ids, _ = await contributors(session, guard.scope(), roots[0])
        sources.update((row.source_revision_id, row) for row in refs)
        resources.update(ids)
        originals.append(artifact)
    return (
        tuple(originals),
        tuple(sources[key] for key in sorted(sources)),
        tuple(sorted(resources)),
    )


async def recipient_windows(
    session: AsyncSession,
    guard: BuilderSourceGuard,
    target: ResourceRef,
    resources: tuple[UUID, ...],
) -> tuple[datetime, ...]:
    now = await db_now(session)
    readers = (
        await session.scalars(
            select(BrainResourceAccess).where(
                BrainResourceAccess.company_id == target.company_id,
                BrainResourceAccess.resource_id == target.resource_id,
                BrainResourceAccess.active.is_(True),
            )
        )
    ).all()
    windows = []
    for reader in readers:
        if reader.expires_at is not None:
            if reader.expires_at <= now:
                continue
            windows.append(reader.expires_at)
        scope = guard.scope().model_copy(update={"principal_id": reader.principal_id})
        grants = await require_resources(session, scope, resources, await db_now(session))
        windows.extend(row.expires_at for row in grants if row.expires_at is not None)
    return tuple(windows)


async def require_replay_manifest(
    session: AsyncSession,
    reference: ArtifactRevisionRef,
    derivation: DerivationRecord,
    originals: tuple[BrainArtifactRevision, ...],
    resources: tuple[UUID, ...],
) -> None:
    inputs, rights = await replay_inputs(session, reference)
    record = await session.get(BrainDerivation, (reference.company_id, derivation.derivation_id))
    refs = tuple(
        (
            await session.scalars(
                select(BrainDerivationSource.source_revision_id).where(
                    BrainDerivationSource.company_id == reference.company_id,
                    BrainDerivationSource.derivation_id == derivation.derivation_id,
                )
            )
        ).all()
    )
    if (
        record is None
        or (
            record.artifact_revision_id,
            record.kind,
            record.recipe_version,
            record.model_recipe,
            record.prompt_sha256,
        )
        != (
            reference.artifact_revision_id,
            derivation.kind,
            derivation.recipe_version,
            None,
            None,
        )
        or set(inputs) != {row.artifact_revision_id for row in originals}
        or set(rights) != set(resources)
        or set(refs) != {row.source_revision_id for row in derivation.contributors}
    ):
        raise ValueError("Builder complete output provenance replay differs")


async def append_inputs(
    session: AsyncSession,
    reference: ArtifactRevisionRef,
    originals: tuple[BrainArtifactRevision, ...],
    resources: tuple[UUID, ...],
) -> None:
    for original in originals:
        session.add(
            BrainArtifactInput(
                company_id=reference.company_id,
                artifact_revision_id=reference.artifact_revision_id,
                input_artifact_revision_id=original.artifact_revision_id,
            )
        )
    for resource in resources:
        session.add(
            BrainArtifactResourceInput(
                company_id=reference.company_id,
                artifact_revision_id=reference.artifact_revision_id,
                resource_id=resource,
            )
        )
    await session.flush()


async def replay_inputs(
    session: AsyncSession, reference: ArtifactRevisionRef
) -> tuple[tuple[UUID, ...], tuple[UUID, ...]]:
    inputs = tuple(
        (
            await session.scalars(
                select(BrainArtifactInput.input_artifact_revision_id).where(
                    BrainArtifactInput.company_id == reference.company_id,
                    BrainArtifactInput.artifact_revision_id == reference.artifact_revision_id,
                )
            )
        ).all()
    )
    rights = tuple(
        (
            await session.scalars(
                select(BrainArtifactResourceInput.resource_id).where(
                    BrainArtifactResourceInput.company_id == reference.company_id,
                    BrainArtifactResourceInput.artifact_revision_id
                    == reference.artifact_revision_id,
                )
            )
        ).all()
    )
    return inputs, rights

"""Independent native bindings precede a mechanical candidate, never work acceptance."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.builder.contained_evidence_store import ContainmentEvidenceStore
from nexus.builder.contracts import BuilderValue
from nexus.builder.execution_contracts import BuilderRunResult
from nexus.builder.result_store import BuilderResultStore
from nexus.builder.source_guard import BuilderSourceGuard
from nexus.builder.verification_support import (
    actual_result_reference,
    actual_summary,
    require_verifier_binding,
)
from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access_support import require_resources
from nexus.company.brain.source_models import BrainSourceHead
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.acceptance_provenance import reference_sources
from nexus.execution.management_checks import require_management_execution
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_support import (
    db_now,
    execution_row,
    lease_scope,
    require_lease,
    runtime_transaction,
)


class BuilderVerificationCandidate(BuilderValue):
    author_action_id: UUID
    verifier_action_id: UUID
    author_result_sha256: str
    verifier_result_sha256: str
    verdict: Literal["pass", "reject", "inconclusive"]
    limitations: tuple[str, ...] = Field(min_length=1, max_length=16)


async def independent_candidate(
    factory: async_sessionmaker[AsyncSession],
    lease: ExecutionLease,
    identity: VerifiedIdentity,
    author: BuilderRunResult,
    verifier: BuilderRunResult,
    guard: BuilderSourceGuard,
    *,
    containment_store: ContainmentEvidenceStore | None = None,
    execution_method_sha256: str | None = None,
) -> BuilderVerificationCandidate:
    # The >50-line candidate boundary retains current native references around
    # both protected summaries/sidecar rereads before deriving a pure verdict.
    if (
        guard.spec != verifier.spec
        or guard.identity != identity
        or verifier.spec.job.actor_id != identity.principal_id
    ):
        raise ValueError("Builder verification binds another actor/job")
    references = await _references(factory, lease, identity, author, verifier, guard)
    for result, reference in zip((author, verifier), references, strict=True):
        await actual_summary(
            guard,
            result,
            reference,
            containment_store=containment_store,
            execution_method_sha256=execution_method_sha256,
        )
    if await _references(factory, lease, identity, author, verifier, guard) != references:
        raise ValueError("Builder verification current references changed")
    comparable = (
        author.spec.job.source == verifier.spec.job.source
        and author.spec.job.patch_sha256 == verifier.spec.job.patch_sha256
        and author.spec.policy_sha256 == verifier.spec.policy_sha256
        and author.spec.runtime_recipe == verifier.spec.runtime_recipe
        and author.spec.job.commands == verifier.spec.job.commands
        and author.spec.job.architecture == verifier.spec.job.architecture
        and author.image_id == verifier.image_id
    )
    verdict = (
        "pass"
        if comparable and author.outcome == verifier.outcome == "commands_succeeded"
        else "inconclusive"
    )
    return BuilderVerificationCandidate(
        author_action_id=author.spec.job.action_id,
        verifier_action_id=verifier.spec.job.action_id,
        author_result_sha256=BuilderResultStore.digest(author),
        verifier_result_sha256=BuilderResultStore.digest(verifier),
        verdict=verdict,
        limitations=(
            "mechanical_candidate_only",
            "registered_engineering_acceptance_publisher_unconfigured",
            "business_readiness_unproven",
        ),
    )


async def _references(
    factory: async_sessionmaker[AsyncSession],
    lease: ExecutionLease,
    identity: VerifiedIdentity,
    author: BuilderRunResult,
    verifier: BuilderRunResult,
    guard: BuilderSourceGuard,
) -> tuple[ArtifactRevisionRef, ArtifactRevisionRef]:
    async with runtime_transaction(factory, lease_scope(lease), identity) as (session, control, _):
        work = await execution_row(session, lease_scope(lease))
        require_lease(work, lease, await db_now(session), execute=True)
        await require_management_execution(
            session, control, work, identity, guard.catalog, guard.artifacts, guard.freshness
        )
        await require_verifier_binding(session, lease, author, verifier)
        first = await actual_result_reference(session, author)
        second = await actual_result_reference(session, verifier)
        for reference in (first, second):
            await guard.artifacts.revalidate_artifact_reference(
                session, control, guard.scope(), identity, reference, await db_now(session)
            )
        await guard.freshness.revalidate_references(
            session, guard.scope(), (first, second), await db_now(session)
        )
        windows = await guard.disclosure_windows(session, control)
        ids, resources = await reference_sources(session, guard.scope(), (first, second))
        grants = await require_resources(session, guard.scope(), resources, await db_now(session))
        for key in ids:
            head = await session.get(BrainSourceHead, (lease.company_id, key))
            if head is None:
                raise ValueError("Builder verification input source is unavailable")
            if head.fresh_until is not None:
                windows = (*windows, head.fresh_until)
        final = await db_now(session)
        require_lease(work, lease, final, execute=True)
        if any(value <= final for value in windows) or any(
            row.expires_at is not None and row.expires_at <= final for row in grants
        ):
            raise ValueError("Builder verification source permission expired")
        return first, second

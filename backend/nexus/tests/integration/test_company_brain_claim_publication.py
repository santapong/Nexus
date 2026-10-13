"""Real claims, exact citations, actor capability, head CAS and immutable source reports."""

from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.base import SourceTime
from nexus.company.brain.claim_models import BrainClaimHead, BrainClaimRevision
from nexus.company.brain.claim_store import BrainClaimStore
from nexus.company.brain.publication_contracts import (
    ClaimDraft,
    ClaimPublication,
    ClaimPublicationBatch,
)
from nexus.company.brain.scope_support import BrainConflictError, BrainDeniedError
from nexus.company.brain.sources import EvidenceRef
from nexus.company.directory_contracts import MembershipChange
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.tests.brain_publication_support import actor_scope, sources
from nexus.tests.brain_publication_support import publication_factory as publication_factory
from nexus.tests.integration.test_company_brain_ingestion import RESOURCE, owner_scope
from nexus.tests.integration.test_company_directory import (
    ACTOR,
    COMPANY,
    OWNER,
    TASK,
    control,
    work,
)
from nexus.tests.integration.test_company_execution_store import identity


def publication(evidence: EvidenceRef, **changes: object) -> ClaimPublication:
    return ClaimPublication.model_validate(
        {
            "company_id": COMPANY,
            "resource": ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
            "draft": ClaimDraft(
                company_id=COMPANY,
                claim_id=UUID(int=3010),
                kind="observation",
                text="The source reports that the product is active.",
                evidence=(evidence,),
                source_event=SourceTime(precision="day", value="2026-10-13", basis="source report"),
            ),
            "revision": "r1",
        }
        | changes
    )


async def test_owner_source_report_retains_exact_citations_and_duplicate_head(
    publication_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    retriever, evidence = await sources(publication_factory, tmp_path)
    store = BrainClaimStore(publication_factory, retriever)
    command = publication(evidence)
    first = await store.publish_manual(owner_scope(), identity(OWNER), command, source_report=True)
    assert first.origin == "source" and first.status == "source_report"
    assert first.supporting == (evidence,) and first.verification_id is None
    assert (
        await store.publish_manual(owner_scope(), identity(OWNER), command, source_report=True)
        == first
    )
    async with publication_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.scalar(select(func.count()).select_from(BrainClaimRevision)) == 1
        head = await session.get(BrainClaimHead, (COMPANY, first.claim_id))
        assert head is not None and head.current_revision_id == first.claim_revision_id


async def test_conflicting_revision_reuse_and_stale_cas_deny_without_replacing_history(
    publication_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    retriever, evidence = await sources(publication_factory, tmp_path)
    store = BrainClaimStore(publication_factory, retriever)
    command = publication(evidence)
    first = await store.publish_manual(owner_scope(), identity(OWNER), command, source_report=True)
    conflicting = command.model_copy(
        update={"draft": command.draft.model_copy(update={"text": "different claim"})}
    )
    with pytest.raises(BrainConflictError):
        await store.publish_manual(owner_scope(), identity(OWNER), conflicting, source_report=True)
    with pytest.raises(BrainConflictError):
        await store.publish_manual(
            owner_scope(), identity(OWNER), publication(evidence, revision="r2"), source_report=True
        )
    second = await store.publish_manual(
        owner_scope(),
        identity(OWNER),
        publication(evidence, revision="r2", expected_previous_revision_id=first.claim_revision_id),
        source_report=True,
    )
    assert second.claim_revision_id != first.claim_revision_id
    assert (
        await store.publish_manual(owner_scope(), identity(OWNER), command, source_report=True)
        == first
    )


@pytest.mark.parametrize(
    "problem",
    ["none", "viewer", "inactive_work", "wrong_actor", "inactive_owner_work", "inactive_parent"],
)
async def test_model_batch_requires_current_proposal_capability_and_active_actor_work(
    publication_factory: async_sessionmaker[AsyncSession], tmp_path: Path, problem: str
) -> None:
    retriever, evidence = await sources(publication_factory, tmp_path)
    directory = PersistentCompanyDirectory(publication_factory)
    registration = work()
    if problem == "inactive_owner_work":
        registration = registration.model_copy(
            update={"actor_id": OWNER, "allowed_principals": (OWNER,)}
        )
    await directory.register_work(registration, control())
    if problem == "viewer":
        await directory.set_membership(
            MembershipChange(company_id=COMPANY, principal_id=ACTOR, role="viewer"), control()
        )
    if problem in {"inactive_work", "inactive_owner_work", "inactive_parent"}:
        await directory.set_work_active(control(), task_id=work().task_id, active=False)
    scope = actor_scope()
    if problem == "inactive_owner_work":
        scope = scope.model_copy(update={"principal_id": OWNER, "actor_id": OWNER})
    if problem == "inactive_parent":
        # Restore the parent only for authorized child registration, then revoke its ancestry.
        await directory.set_work_active(control(), task_id=TASK, active=True)
        await directory.register_work(work(UUID(int=3300), parent=TASK, amount="0.25"), control())
        await directory.set_work_active(control(), task_id=TASK, active=False)
        scope = scope.model_copy(update={"task_id": UUID(int=3300)})
    if problem == "wrong_actor":
        scope = scope.model_copy(update={"principal_id": OWNER})
    store = BrainClaimStore(publication_factory, retriever)
    batch = ClaimPublicationBatch(
        company_id=COMPANY,
        extraction_version="fixture.extraction.v1",
        claims=(publication(evidence),),
    )
    if problem != "none":
        with pytest.raises(BrainDeniedError):
            await store.propose_batch(scope, identity(scope.principal_id), batch)
    else:
        (proposed,) = await store.propose_batch(scope, identity(ACTOR), batch)
        assert proposed.origin == "model" and proposed.status == "proposed"
        assert proposed.verification_id is None and proposed.receipt_id is None

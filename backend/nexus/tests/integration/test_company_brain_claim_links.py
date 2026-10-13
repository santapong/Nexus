"""Evidence-bound claim conflict/supersession appends history and rejects cycles."""

from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.claim_models import BrainClaimLink, BrainClaimRevision
from nexus.company.brain.claim_store import BrainClaimStore
from nexus.company.brain.publication_contracts import ClaimLinkPublication
from nexus.company.brain.scope_support import BrainConflictError, BrainDeniedError
from nexus.tests.brain_publication_support import publication_factory as publication_factory
from nexus.tests.brain_publication_support import sources
from nexus.tests.integration.test_company_brain_claim_publication import publication
from nexus.tests.integration.test_company_brain_ingestion import owner_scope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER
from nexus.tests.integration.test_company_execution_store import identity


async def test_conflict_and_supersession_retain_original_history_and_reject_cycle(
    publication_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    retriever, evidence = await sources(publication_factory, tmp_path)
    store = BrainClaimStore(publication_factory, retriever)
    command = publication(evidence)
    old = await store.publish_manual(owner_scope(), identity(OWNER), command, source_report=True)
    new = await store.publish_manual(
        owner_scope(),
        identity(OWNER),
        command.model_copy(
            update={
                "draft": command.draft.model_copy(
                    update={"claim_id": UUID(int=3201), "text": "Conflicting source report"}
                )
            }
        ),
        source_report=True,
    )
    conflict = ClaimLinkPublication(
        company_id=COMPANY,
        link_id=UUID(int=3202),
        subject=new,
        object=old,
        predicate="conflicts_with",
        rationale="The exact source reports differ.",
        evidence=(evidence,),
    )
    linked = await store.link(owner_scope(), identity(OWNER), conflict)
    assert await store.link(owner_scope(), identity(OWNER), conflict) == linked
    supersedes = conflict.model_copy(update={"link_id": UUID(int=3203), "predicate": "supersedes"})
    await store.link(owner_scope(), identity(OWNER), supersedes)
    with pytest.raises(BrainConflictError):
        await store.link(
            owner_scope(),
            identity(OWNER),
            supersedes.model_copy(update={"subject": old, "object": new}),
        )
    with pytest.raises(BrainConflictError):
        await store.link(
            owner_scope(),
            identity(OWNER),
            supersedes.model_copy(
                update={"link_id": UUID(int=3204), "subject": old, "object": new}
            ),
        )
    with pytest.raises(BrainDeniedError):
        await store.link(
            owner_scope(),
            identity(OWNER),
            supersedes.model_copy(
                update={
                    "link_id": UUID(int=3205),
                    "subject": new.model_copy(update={"revision": "spliced"}),
                }
            ),
        )
    async with publication_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.scalar(select(func.count()).select_from(BrainClaimLink)) == 2
        stored = await session.get(BrainClaimRevision, (COMPANY, old.claim_revision_id))
        assert stored is not None and stored.status == "source_report"


async def test_supersession_chain_rejects_uncertain_depth_before_publishing_another_link(
    publication_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    retriever, evidence = await sources(publication_factory, tmp_path)
    store = BrainClaimStore(publication_factory, retriever)
    base = publication(evidence)
    records = [
        await store.publish_manual(
            owner_scope(),
            identity(OWNER),
            base.model_copy(
                update={"draft": base.draft.model_copy(update={"claim_id": UUID(int=3700 + index)})}
            ),
            source_report=True,
        )
        for index in range(18)
    ]
    for index in range(1, 17):
        await store.link(
            owner_scope(),
            identity(OWNER),
            ClaimLinkPublication(
                company_id=COMPANY,
                link_id=UUID(int=3800 + index),
                subject=records[index],
                object=records[index - 1],
                predicate="supersedes",
                rationale="Bounded synthetic source-report history",
                evidence=(evidence,),
            ),
        )
    with pytest.raises(BrainDeniedError):
        await store.link(
            owner_scope(),
            identity(OWNER),
            ClaimLinkPublication(
                company_id=COMPANY,
                link_id=UUID(int=3817),
                subject=records[17],
                object=records[16],
                predicate="supersedes",
                rationale="This traversal exceeds the registered depth",
                evidence=(evidence,),
            ),
        )
    async with publication_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.scalar(select(func.count()).select_from(BrainClaimLink)) == 16

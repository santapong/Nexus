"""Closed native entities and typed source-report edges publish through real current access."""

from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.base import SourceTime
from nexus.company.brain.ontology import (
    AuthorityPolicyContent,
    BudgetContent,
    PrincipalContent,
    ProductContent,
    SupportCaseContent,
)
from nexus.company.brain.ontology_store import BrainOntologyStore
from nexus.company.brain.publication_contracts import EntityPublication, RelationshipPublication
from nexus.company.brain.scope_support import BrainConflictError, BrainDeniedError
from nexus.company.brain.sources import EvidenceRef
from nexus.company.directory_models import DirectoryMembership
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.execution.runtime_models import EffectIntent
from nexus.harness.journal_models import CompanyControl, JournalAction, WorkBudget
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


def entity(evidence: EvidenceRef, *, support: bool = False) -> EntityPublication:
    return EntityPublication(
        company_id=COMPANY,
        entity_id=UUID(int=3101 if support else 3100),
        resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
        content=SupportCaseContent(label="Reported support case")
        if support
        else ProductContent(label="Reported product"),
        evidence=(evidence,),
        source_event=SourceTime(precision="day", value="2026-10-13", basis="source"),
        revision="r1",
    )


async def test_closed_entities_and_typed_relationship_preserve_source_report_boundary(
    publication_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    retriever, evidence = await sources(publication_factory, tmp_path)
    store = BrainOntologyStore(publication_factory, retriever)
    product = await store.publish_manual_entity(
        owner_scope(), identity(OWNER), entity(evidence), source_report=True
    )
    support = await store.publish_manual_entity(
        owner_scope(), identity(OWNER), entity(evidence, support=True), source_report=True
    )
    relation = RelationshipPublication(
        company_id=COMPANY,
        relationship_id=UUID(int=3102),
        revision="r1",
        predicate="has_support_case",
        subject=product,
        object=support,
        evidence=(evidence,),
    )
    linked = await store.publish_manual_relationship(
        owner_scope(), identity(OWNER), relation, source_report=True
    )
    assert linked.status == "source_report" and linked.origin == "source"
    assert linked.subject.entity_revision_id == product.entity_revision_id
    assert (
        await store.publish_manual_relationship(
            owner_scope(), identity(OWNER), relation, source_report=True
        )
        == linked
    )
    other = await store.publish_manual_entity(
        owner_scope(),
        identity(OWNER),
        entity(evidence).model_copy(update={"entity_id": UUID(int=3104)}),
        source_report=True,
    )
    with pytest.raises(BrainConflictError):
        await store.publish_manual_relationship(
            owner_scope(),
            identity(OWNER),
            relation.model_copy(update={"subject": other}),
            source_report=True,
        )
    conflicting = relation.model_copy(update={"evidence": ()})
    with pytest.raises((BrainDeniedError, BrainConflictError)):
        await store.publish_manual_relationship(
            owner_scope(), identity(OWNER), conflicting, source_report=True
        )


async def test_native_reference_and_endpoint_revision_splicing_cannot_publish(
    publication_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    retriever, evidence = await sources(publication_factory, tmp_path)
    store = BrainOntologyStore(publication_factory, retriever)
    invalid_principal = entity(evidence).model_copy(
        update={"content": PrincipalContent(label="Not a member", principal_id=UUID(int=9999))}
    )
    with pytest.raises(BrainDeniedError):
        await store.publish_manual_entity(
            owner_scope(), identity(OWNER), invalid_principal, source_report=True
        )
    product = await store.publish_manual_entity(
        owner_scope(), identity(OWNER), entity(evidence), source_report=True
    )
    support = await store.publish_manual_entity(
        owner_scope(), identity(OWNER), entity(evidence, support=True), source_report=True
    )
    with pytest.raises(BrainDeniedError):
        await store.publish_manual_relationship(
            owner_scope(),
            identity(OWNER),
            RelationshipPublication(
                company_id=COMPANY,
                relationship_id=UUID(int=3103),
                revision="r1",
                predicate="has_support_case",
                subject=product.model_copy(update={"revision": "spliced"}),
                object=support,
                evidence=(evidence,),
            ),
            source_report=True,
        )


async def test_model_budget_policy_representations_leave_actual_controls_and_spend_unchanged(
    publication_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    retriever, evidence = await sources(publication_factory, tmp_path)
    await PersistentCompanyDirectory(publication_factory).register_work(work(), control())
    store = BrainOntologyStore(publication_factory, retriever)
    for key, content in (
        (
            UUID(int=3601),
            BudgetContent(label="Proposed budget reference", budget_reference="company-budget"),
        ),
        (
            UUID(int=3602),
            AuthorityPolicyContent(
                label="Proposed policy representation", policy_version="proposed-policy-v2"
            ),
        ),
    ):
        value = await store.propose_entity(
            actor_scope(),
            identity(ACTOR),
            entity(evidence).model_copy(update={"entity_id": key, "content": content}),
        )
        assert value.origin == "model" and value.status == "proposed"
    async with publication_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        controls = await session.get(CompanyControl, COMPANY)
        assert controls is not None and controls.policy_version == "fixture-policy"
        budget = await session.get(WorkBudget, (COMPANY, TASK))
        assert budget is None  # A typed Budget representation cannot mint a spend allowance.
        member = await session.get(DirectoryMembership, (COMPANY, ACTOR))
        assert member is not None and member.role == "member"
        assert await session.scalar(select(func.count()).select_from(JournalAction)) == 0
        assert await session.scalar(select(func.count()).select_from(EffectIntent)) == 0

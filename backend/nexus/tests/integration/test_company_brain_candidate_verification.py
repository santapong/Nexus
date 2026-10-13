"""An actual stored passing verification candidate cannot become independent Brain acceptance."""

from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.ontology import ActionContent, VerificationContent
from nexus.company.brain.ontology_store import BrainOntologyStore
from nexus.company.brain.publication_contracts import RelationshipPublication
from nexus.company.brain.scope_support import BrainDeniedError
from nexus.company.contracts.results import VerificationResult
from nexus.tests.brain_publication_support import actor_scope, sources
from nexus.tests.brain_publication_support import publication_factory as publication_factory
from nexus.tests.integration.test_company_brain_ingestion import owner_scope
from nexus.tests.integration.test_company_brain_ontology_publication import entity
from nexus.tests.integration.test_company_directory import OWNER
from nexus.tests.integration.test_company_execution_store import (
    action,
    identity,
    ready,
    receipt,
    scope,
)


@pytest.mark.parametrize("ambiguous", [False, True])
async def test_passing_candidate_can_be_referenced_but_cannot_publish_verified_by_source_report(
    publication_factory: async_sessionmaker[AsyncSession], tmp_path: Path, ambiguous: bool
) -> None:
    retriever, evidence = await sources(publication_factory, tmp_path)
    execution, effects = await ready(publication_factory)
    approved = await action(publication_factory)
    lease = await execution.claim(scope(), identity(), UUID(int=3500))
    await effects.begin(lease, identity(), approved.action_id)
    # A labelled offline receipt/candidate fixture is not an actual external effect or verifier.
    await effects.record_receipt(lease, identity(), receipt(approved), actual_usd=Decimal(0))
    candidate = VerificationResult(
        company_id=approved.company_id,
        verification_id=UUID(int=3501),
        action_id=approved.action_id,
        verifier_id=OWNER,
        verdict="pass",
        criterion_ids=("fixture-criterion",),
        evidence_ids=(evidence.evidence_id,),
    )
    await effects.record_verification_candidate(lease, identity(), candidate)
    store = BrainOntologyStore(publication_factory, retriever)
    candidate_entity = entity(evidence).model_copy(
        update={
            "entity_id": UUID(int=3503),
            "content": VerificationContent(
                label="Stored verification candidate", verification_id=candidate.verification_id
            ),
        }
    )
    if ambiguous:
        second = await action(publication_factory)
        await effects.begin(lease, identity(), second.action_id)
        await effects.record_receipt(lease, identity(), receipt(second), actual_usd=Decimal(0))
        await effects.record_verification_candidate(
            lease, identity(), candidate.model_copy(update={"action_id": second.action_id})
        )
        with pytest.raises(BrainDeniedError):
            await store.publish_manual_entity(
                owner_scope(), identity(OWNER), candidate_entity, source_report=True
            )
        return
    action_entity = await store.publish_manual_entity(
        owner_scope(),
        identity(OWNER),
        entity(evidence).model_copy(
            update={
                "entity_id": UUID(int=3502),
                "content": ActionContent(label="Reported action", action_id=approved.action_id),
            }
        ),
        source_report=True,
    )
    verification_entity = await store.publish_manual_entity(
        owner_scope(),
        identity(OWNER),
        candidate_entity,
        source_report=True,
    )
    relation = RelationshipPublication(
        company_id=approved.company_id,
        relationship_id=UUID(int=3504),
        revision="r1",
        predicate="verified_by",
        subject=action_entity,
        object=verification_entity,
        evidence=(evidence,),
    )
    with pytest.raises(BrainDeniedError):
        await store.publish_manual_relationship(
            owner_scope(), identity(OWNER), relation, source_report=True
        )
    proposed = await store.propose_relationship(actor_scope(), identity(), relation)
    assert proposed.origin == "model" and proposed.status == "proposed"
    state = await execution.get(scope(), identity())
    assert state.state == "verifying" and state.counters.tool_attempts == 1

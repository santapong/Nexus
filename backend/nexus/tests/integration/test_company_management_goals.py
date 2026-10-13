"""Measured goal publication requires actual current source access and preserves unknown dates."""

from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.brain.base import SourceTime
from nexus.company.brain.blob_store import BlobReader, ProtectedBlobStore
from nexus.company.brain.evidence_models import BrainEvidence
from nexus.company.brain.retrieval import RetrievalLimits
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.brain.sources import ArtifactRevisionRef, EvidenceRef
from nexus.company.directory_contracts import MembershipChange
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management.base import RevisionRef
from nexus.company.management.control_store import ManagementControlStore
from nexus.company.management.goal_store import GoalStore
from nexus.company.management.goals import (
    DueIntent,
    GoalDefinition,
    GoalMetric,
    GoalRevisionRef,
    KnownBaseline,
    UnknownBaseline,
)
from nexus.company.management.governance_models import ManagementGoalHead, ManagementGoalRevision
from nexus.tests.integration.test_company_brain_ingestion import (
    RESOURCE,
    Reader,
    command,
    configured,
    owner_scope,
)
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER, control, prepare
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.management_control_support import GOAL, mandate
from nexus.tests.management_control_support import management_factory as management_factory


def goal(reference: RevisionRef, evidence: EvidenceRef | None = None) -> GoalDefinition:
    return GoalDefinition(
        company_id=COMPANY,
        goal_id=GOAL,
        owner_id=ACTOR,
        title="Produce a cited internal report",
        mandate=reference,
        metrics=(
            GoalMetric(
                company_id=COMPANY,
                metric_id="citation.coverage",
                unit="ratio",
                comparator="ge",
                target=Decimal(1),
                baseline=KnownBaseline(
                    value=Decimal(0),
                    observed_at=SourceTime(
                        precision="day", value="2026-10-13", basis="declared source baseline"
                    ),
                    evidence=(evidence,),
                )
                if evidence
                else UnknownBaseline(reason="No measured baseline"),
            ),
        ),
        due=DueIntent(
            source_time=SourceTime(precision="unknown", value=None, basis="no due date supplied")
        ),
    )


async def source_fixture(
    factory: async_sessionmaker[AsyncSession], root: Path
) -> tuple[PersistentBrainRetriever, EvidenceRef]:
    raw = b"Citation coverage baseline: 0. Report source dated 2026-10-13."
    ingestion = await configured(factory, root, Reader({"r1": raw}))
    await ingestion.ingest(owner_scope(), identity(OWNER), command(raw, "r1"))
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        key = await session.scalar(select(BrainEvidence.evidence_id))
        assert key is not None
    return PersistentBrainRetriever(
        factory,
        ProtectedBlobStore(root, storage_symbol="fixture.blobs.v1"),
        limits=RetrievalLimits(),
    ), EvidenceRef(company_id=COMPANY, evidence_id=key)


async def test_unknown_baseline_due_precision_and_exact_goal_replay_preserve_history(
    management_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    await prepare(management_factory)
    current = await ManagementControlStore(management_factory).publish_mandate(
        control(), identity(OWNER), mandate(), expected_revision_id=None
    )
    reference = RevisionRef.model_validate_json(
        current.model_dump_json(include=set(RevisionRef.model_fields))
    )
    retriever = PersistentBrainRetriever(
        management_factory,
        ProtectedBlobStore(tmp_path, storage_symbol="fixture.blobs.v1"),
        limits=RetrievalLimits(),
    )
    store = GoalStore(management_factory, retriever)
    first = await store.publish(
        control(), identity(OWNER), goal(reference), version="v1", expected_revision_id=None
    )
    assert first.definition.metrics[0].baseline.kind == "unknown"
    assert first.definition.due.actionable_at is None
    second = await store.publish(
        control(),
        identity(OWNER),
        goal(reference),
        version="v2",
        expected_revision_id=first.revision_id,
    )
    assert (
        await store.publish(
            control(), identity(OWNER), goal(reference), version="v1", expected_revision_id=None
        )
        == first
    )
    async with management_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        head = await session.get(ManagementGoalHead, (COMPANY, GOAL))
        assert head is not None and head.current_revision_id == second.revision_id
        assert await session.scalar(select(func.count()).select_from(ManagementGoalRevision)) == 2


@pytest.mark.parametrize(
    "problem", ["none", "source_revoked", "changed_bytes", "grant_during_read", "owner_during_read"]
)
async def test_known_baseline_uses_actual_protected_bytes_and_final_current_permissions(
    management_factory: async_sessionmaker[AsyncSession], tmp_path: Path, problem: str
) -> None:
    retriever, evidence = await source_fixture(management_factory, tmp_path)
    current = await ManagementControlStore(management_factory).publish_mandate(
        control(), identity(OWNER), mandate(), expected_revision_id=None
    )
    reference = RevisionRef.model_validate_json(
        current.model_dump_json(include=set(RevisionRef.model_fields))
    )
    change = ResourceAccessChange(
        company_id=COMPANY,
        resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
        principal_id=OWNER,
        active=False,
        expected_generation=1,
    )
    if problem == "source_revoked":
        await ResourceAccessStore(management_factory).change(owner_scope(), identity(OWNER), change)
    if problem in {"changed_bytes", "grant_during_read", "owner_during_read"}:

        class ChangingReader:
            def __init__(self, original: BlobReader) -> None:
                self.original = original

            async def read(self, artifact: ArtifactRevisionRef) -> bytes:
                raw = await self.original.read(artifact)
                if problem == "changed_bytes":
                    return b"unverified bytes"
                if problem == "owner_during_read":
                    await PersistentCompanyDirectory(management_factory).set_membership(
                        MembershipChange(
                            company_id=COMPANY,
                            principal_id=OWNER,
                            role="owner",
                            membership_active=False,
                        ),
                        control(),
                    )
                    return raw
                await ResourceAccessStore(management_factory).change(
                    owner_scope(), identity(OWNER), change
                )
                return raw

        retriever = PersistentBrainRetriever(
            management_factory, ChangingReader(retriever.blobs), limits=retriever.limits
        )
    store = GoalStore(management_factory, retriever)
    if problem == "none":
        first = await store.publish(
            control(),
            identity(OWNER),
            goal(reference, evidence),
            version="v1",
            expected_revision_id=None,
        )
        assert first.definition.metrics[0].baseline.kind == "known"
    else:
        with pytest.raises(ValueError):
            await store.publish(
                control(),
                identity(OWNER),
                goal(reference, evidence),
                version="v1",
                expected_revision_id=None,
            )
        async with management_factory() as session, session.begin():
            await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
            assert (
                await session.scalar(select(func.count()).select_from(ManagementGoalRevision)) == 0
            )


async def test_goal_reactivation_uses_current_mandate_and_old_activity_replay_keeps_revocation(
    management_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    retriever, evidence = await source_fixture(management_factory, tmp_path)
    controls = ManagementControlStore(management_factory)
    parent = await controls.publish_mandate(
        control(), identity(OWNER), mandate(), expected_revision_id=None
    )
    parent_ref = RevisionRef.model_validate_json(
        parent.model_dump_json(include=set(RevisionRef.model_fields))
    )
    store = GoalStore(management_factory, retriever)
    row = await store.publish(
        control(),
        identity(OWNER),
        goal(parent_ref, evidence),
        version="v1",
        expected_revision_id=None,
    )
    ref = GoalRevisionRef.model_validate_json(
        row.model_dump_json(include=set(GoalRevisionRef.model_fields))
    )
    await store.revoke(
        control().model_copy(update={"operation_id": UUID(int=5300)}), identity(OWNER), ref
    )
    resume_scope = control().model_copy(update={"operation_id": UUID(int=5301)})
    original = await store.reactivate(resume_scope, identity(OWNER), ref)
    await store.revoke(
        control().model_copy(update={"operation_id": UUID(int=5302)}), identity(OWNER), ref
    )
    assert await store.reactivate(resume_scope, identity(OWNER), ref) == original
    async with management_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        head = await session.get(ManagementGoalHead, (COMPANY, GOAL))
        assert head is not None and not head.active
    await controls.revoke_mandate(
        control().model_copy(update={"operation_id": UUID(int=5303)}), identity(OWNER), parent_ref
    )
    with pytest.raises(ValueError):
        await store.reactivate(
            control().model_copy(update={"operation_id": UUID(int=5304)}), identity(OWNER), ref
        )


async def test_goal_replacement_preserves_revoked_activity(
    management_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    retriever, evidence = await source_fixture(management_factory, tmp_path)
    parent = await ManagementControlStore(management_factory).publish_mandate(
        control(), identity(OWNER), mandate(), expected_revision_id=None
    )
    parent_ref = RevisionRef.model_validate_json(
        parent.model_dump_json(include=set(RevisionRef.model_fields))
    )
    store = GoalStore(management_factory, retriever)
    first = await store.publish(
        control(),
        identity(OWNER),
        goal(parent_ref, evidence),
        version="v1",
        expected_revision_id=None,
    )
    ref = GoalRevisionRef.model_validate_json(
        first.model_dump_json(include=set(GoalRevisionRef.model_fields))
    )
    await store.revoke(
        control().model_copy(update={"operation_id": UUID(int=5500)}), identity(OWNER), ref
    )
    second = await store.publish(
        control(),
        identity(OWNER),
        goal(parent_ref, evidence),
        version="v2",
        expected_revision_id=ref.revision_id,
    )
    async with management_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        head = await session.get(ManagementGoalHead, (COMPANY, GOAL))
        assert (
            head is not None and head.current_revision_id == second.revision_id and not head.active
        )

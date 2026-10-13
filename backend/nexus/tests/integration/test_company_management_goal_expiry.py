"""Fresh permission after the final awaited proof gate must precede committed goal publication."""

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.retrieval import CitationHandle
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.brain.scope_support import BrainDeniedError
from nexus.company.management.base import RevisionRef
from nexus.company.management.control_store import ManagementControlStore
from nexus.company.management.goal_store import GoalStore
from nexus.company.management.governance_models import ManagementGoalHead, ManagementGoalRevision
from nexus.harness.journal_models import CompanyControl
from nexus.tests.integration.test_company_brain_ingestion import RESOURCE, owner_scope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_management_goals import goal, source_fixture
from nexus.tests.management_control_support import management_factory as management_factory
from nexus.tests.management_control_support import mandate


class DelayedFinalCheck(PersistentBrainRetriever):
    calls = 0

    async def revalidate_handles(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        signed: VerifiedIdentity,
        handles: tuple[CitationHandle, ...],
        now: datetime,
    ) -> None:
        await super().revalidate_handles(session, control, scope, signed, handles, now)
        self.calls += 1
        if self.calls == 2:
            await session.execute(select(func.pg_sleep(1.3)))


async def test_owner_grant_expiring_after_final_proof_denies_and_rolls_back_goal(
    management_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    retriever, evidence = await source_fixture(management_factory, tmp_path)
    current = await ManagementControlStore(management_factory).publish_mandate(
        control(),
        identity(OWNER),
        mandate(),
        expected_revision_id=None,
    )
    reference = RevisionRef.model_validate_json(
        current.model_dump_json(include=set(RevisionRef.model_fields))
    )
    async with management_factory() as session:
        now = await session.scalar(select(func.clock_timestamp()))
    assert now is not None
    await ResourceAccessStore(management_factory).change(
        owner_scope(),
        identity(OWNER),
        ResourceAccessChange(
            company_id=COMPANY,
            resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
            principal_id=OWNER,
            active=True,
            expires_at=now + timedelta(seconds=1),
            expected_generation=1,
        ),
    )
    checking = DelayedFinalCheck(management_factory, retriever.blobs, limits=retriever.limits)
    with pytest.raises(BrainDeniedError):
        await GoalStore(management_factory, checking).publish(
            control(),
            identity(OWNER),
            goal(reference, evidence),
            version="v1",
            expected_revision_id=None,
        )
    assert checking.calls == 2
    async with management_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.scalar(select(func.count()).select_from(ManagementGoalRevision)) == 0
        assert await session.scalar(select(func.count()).select_from(ManagementGoalHead)) == 0

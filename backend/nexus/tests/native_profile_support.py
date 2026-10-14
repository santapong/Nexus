"""Private normal013 profile fixture uses actual owner report/commitment and native tool plans."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.retrieval import RetrievalLimits
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.management.commitment_store import CommitmentStore
from nexus.company.management.goals import DueIntent
from nexus.company.management.lifecycle import PlanRevisionRef
from nexus.company.management.native_profile_contracts import NativeReportPreparationPolicy
from nexus.company.management.native_profile_store import NativeReportPreparationService
from nexus.company.management.operations import CommitmentDefinition
from nexus.company.management.plans import PlanPayload
from nexus.company.management.scheduling_support import SchedulerIdentities
from nexus.execution.native_report_composition import compose_native_reports
from nexus.execution.native_report_services import NativeReportServices
from nexus.settings import settings
from nexus.tests.generated_artifact_fixture import admitted_generated_plan
from nexus.tests.integration.operating_report_fixture_sources import current_input_source
from nexus.tests.integration.test_company_directory import OWNER, control, migrate
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.management_scheduler_support import FixtureIdentities, FixtureResources


@pytest.fixture
async def profile_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_native_profile"
    admin, app = (
        create_async_engine(url),
        create_async_engine(url.set(username="nexus_company_app")),
    )
    installed = False
    try:
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "upgrade")
        installed = True
        yield async_sessionmaker(app, expire_on_commit=False)
    finally:
        await app.dispose()
        if installed:
            async with admin.begin() as connection:
                await connection.run_sync(migrate, "downgrade")
        await admin.dispose()


@dataclass(frozen=True)
class ProfileScenario:
    preparation: NativeReportPreparationService
    native: NativeReportServices
    payload: PlanPayload
    report_id: UUID
    commitment_id: UUID
    evidence_ids: tuple[UUID, ...]


async def configured_profile(
    factory: async_sessionmaker[AsyncSession],
    root: Path,
    *,
    due: DueIntent | None = None,
    identities: SchedulerIdentities | None = None,
) -> ProfileScenario:
    plans, payload, rules, policies = await admitted_generated_plan(factory, root, production=True)
    native = compose_native_reports(
        factory,
        catalog=plans.catalog,
        blobs=ProtectedBlobStore(root, storage_symbol="fixture.blobs.v1"),
        policies=policies,
        rules=rules,
        identities=identities or FixtureIdentities(),
        resources=FixtureResources(),
        worker_id=uuid4(),
    )
    observed = datetime.now(UTC)
    saved = await native.producer.reports.save_snapshot(
        control(),
        identity(OWNER),
        (await _plan_ref(factory, payload)).plan_revision_id,
        payload.children[0].binding.task_id,
        (),
        period_start=observed - timedelta(days=1),
        period_end=observed,
    )
    from nexus.company.brain.base import SourceTime

    definition = CommitmentDefinition(
        company_id=payload.company_id,
        commitment_id=uuid4(),
        goal=payload.goal,
        plan=saved.selection.plan,
        responsible_id=payload.children[0].binding.actor_id,
        deliverable="Bounded native report with independent mechanical verification",
        due=due
        or DueIntent(
            source_time=SourceTime(
                precision="instant", value=observed.isoformat(), basis="owner fixture"
            ),
            actionable_at=observed,
            actionable_basis="operator_explicit",
        ),
        work=(saved.selection.author, saved.selection.verifier),
    )
    commitment = await CommitmentStore(factory).publish(
        control(), identity(OWNER), definition, version="v1", expected_revision_id=None
    )
    service = NativeReportPreparationService(
        factory,
        native.producer,
        plans.catalog,
        native.artifacts,
        native.publisher.freshness,
        identities or FixtureIdentities(),
        FixtureResources(),
        policy=NativeReportPreparationPolicy(rules=rules),
    )
    retriever = PersistentBrainRetriever(
        factory,
        ProtectedBlobStore(root, storage_symbol="fixture.blobs.v1"),
        limits=RetrievalLimits(),
    )
    _, handles = await current_input_source(factory, retriever)
    return ProfileScenario(
        service,
        native,
        payload,
        saved.report_id,
        commitment.commitment_id,
        tuple(row.evidence_id for row in handles),
    )


async def _plan_ref(
    factory: async_sessionmaker[AsyncSession], payload: PlanPayload
) -> PlanRevisionRef:
    from sqlalchemy import func, select

    from nexus.company.management.plan_store import ManagementPlanStore

    async with factory() as session, session.begin():
        await session.execute(
            select(func.set_config("nexus.company_id", str(payload.company_id), True))
        )
        bound = await ManagementPlanStore.current_binding(
            session, payload.company_id, payload.children[0].binding.task_id
        )
        assert bound is not None
        return bound.plan

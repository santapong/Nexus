"""Real restricted-PG plan fixtures use public control/goal/source admission stores.

The single assigned helper module exceeds 400 lines to keep public native setup,
action observations and the complete derived-source fixture together.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.brain.base import SourceTime
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.claims import DerivationRecord
from nexus.company.brain.ingestion_store import BrainIngestionStore
from nexus.company.brain.retrieval import RetrievalLimits
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.brain.source_models import BrainSourceHead, BrainSourceRevision
from nexus.company.brain.source_registry import SourcePolicy, SourceRegistry, SourceSnapshot
from nexus.company.brain.sources import (
    ArtifactRevisionRef,
    IngestCommand,
    SourceRegistration,
    SourceRevisionRef,
)
from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.work import WorkItem, WorkPlan
from nexus.company.directory_contracts import MembershipChange
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.base import RevisionRef
from nexus.company.management.check_contracts import REPORT_CHECK_CRITERIA, REPORT_CHECK_RECIPE
from nexus.company.management.control_store import ManagementControlStore
from nexus.company.management.goal_store import GoalStore
from nexus.company.management.goals import GoalRevisionRef
from nexus.company.management.governance import CharterRevisionRef
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plan_support import NamedPlanResource, PlanAdmissionCatalog
from nexus.company.management.plans import (
    ChildAllocation,
    PlanPayload,
    ProcedureRoot,
    RunBinding,
    VerificationIntent,
)
from nexus.core.llm.company_registry import EvaluationEvidence, ModelHealth, ModelRegistry
from nexus.execution.runtime_contracts import AttemptQuota
from nexus.harness.canonical import action_hash
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.standing_contracts import ToolPermission
from nexus.settings import settings
from nexus.tests.integration.test_company_brain_ingestion import (
    RESOURCE,
    SOURCE,
    Reader,
    command,
    configured,
    owner_scope,
)
from nexus.tests.integration.test_company_directory import (
    ACTOR,
    COMPANY,
    OWNER,
    WORKSPACE,
    control,
    migrate,
)
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_management_goals import goal
from nexus.tests.management_control_support import GOAL, charter, mandate
from nexus.tests.unit.test_company_model_registry import model

VERIFIER = UUID(int=5100)
DERIVED_RESOURCE = UUID(int=6100)


@pytest.fixture
async def plans_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_management_plans"
    admin, app = (
        create_async_engine(url),
        create_async_engine(url.set(username="nexus_company_app")),
    )
    migrated = False
    try:
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "upgrade")
        migrated = True
        yield async_sessionmaker(app, expire_on_commit=False)
    finally:
        await app.dispose()
        if migrated:
            async with admin.begin() as connection:
                await connection.run_sync(migrate, "downgrade")
        await admin.dispose()


def binding(actor: UUID) -> RunBinding:
    return RunBinding(
        company_id=COMPANY,
        workspace_id=WORKSPACE,
        actor_id=actor,
        task_id=uuid4(),
        trace_id=uuid4(),
        run_id=uuid4(),
        workflow_name="internal.report",
        workflow_version="v1",
        model_profile="routine",
        model_registry_version="fixture-registry-v1",
    )


async def configured_plan(
    factory: async_sessionmaker[AsyncSession],
    root: Path,
) -> tuple[ManagementPlanStore, PlanPayload]:
    """Only public native stores create operative mandate, charter, goal and readable source."""
    # Explicit nested identities keep this setup longer than the normal 50-line function limit.
    raw = b"Bounded internal report input, no customer-readiness assertion."
    ingestion = await configured(factory, root, Reader({"r1": raw}))
    directory = PersistentCompanyDirectory(factory)
    await directory.set_membership(
        MembershipChange(company_id=COMPANY, principal_id=VERIFIER, role="member"), control()
    )
    await ingestion.ingest(owner_scope(), identity(OWNER), command(raw, "r1"))
    await ResourceAccessStore(factory).change(
        owner_scope(),
        identity(OWNER),
        ResourceAccessChange(
            company_id=COMPANY,
            resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
            principal_id=VERIFIER,
            active=True,
            expected_generation=1,
        ),
    )
    controls = ManagementControlStore(factory)
    admitted = await controls.publish_mandate(
        control(), identity(OWNER), mandate(), expected_revision_id=None
    )
    mref = RevisionRef.model_validate_json(
        admitted.model_dump_json(include=set(RevisionRef.model_fields))
    )
    cdata = charter(verifier=VERIFIER).model_copy(
        update={"allowed_tools": ("fake.internal.read.v1",)}
    )
    admitted_charter = await controls.publish_charter(
        control(), identity(OWNER), cdata, mandate=mref, expected_revision_id=None
    )
    cref = CharterRevisionRef.model_validate_json(
        admitted_charter.model_dump_json(include=set(CharterRevisionRef.model_fields))
    )
    retriever = PersistentBrainRetriever(
        factory,
        ProtectedBlobStore(root, storage_symbol="fixture.blobs.v1"),
        limits=RetrievalLimits(),
    )
    admitted_goal = await GoalStore(factory, retriever).publish(
        control(), identity(OWNER), goal(mref), version="v1", expected_revision_id=None
    )
    gref = GoalRevisionRef.model_validate_json(
        admitted_goal.model_dump_json(include=set(GoalRevisionRef.model_fields))
    )
    now = datetime.now(UTC)
    registered = model(
        provider="test",
        api_family="test",
        price=None,
        health=ModelHealth(
            status="healthy",
            checked_at=now - timedelta(minutes=1),
            expires_at=now + timedelta(hours=1),
        ),
        evaluations=(
            EvaluationEvidence(
                profile="routine",
                suite_version="offline-mechanical-v1",
                artifact_reference="fixture-only",
                score=Decimal(1),
                conformance_passed=True,
                evaluated_at=now - timedelta(minutes=1),
                expires_at=now + timedelta(hours=1),
            ),
        ),
    )
    catalog = PlanAdmissionCatalog(
        company_id=COMPANY,
        tools=(
            ToolPermission(
                tool="fake.internal.read.v1", tool_version="v1", resource="company.report"
            ),
        ),
        resources=(
            NamedPlanResource(
                symbol="company.report",
                resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
            ),
        ),
        models=ModelRegistry(
            company_id=COMPANY,
            revision="fixture-registry-v1",
            pricebook_version="fixture-prices",
            models=(registered,),
        ),
        admitted_profiles=frozenset({"routine"}),
        check_recipes=frozenset({REPORT_CHECK_RECIPE}),
    )
    author, verifier, parent = binding(ACTOR), binding(VERIFIER), binding(OWNER)
    children = tuple(
        ChildAllocation(
            company_id=COMPANY,
            binding=row,
            charter=cref,
            allocation_usd=Decimal("0.2"),
            quota=AttemptQuota(
                model_requests=1, tool_attempts=1, rework_rounds=0, plan_revisions=0
            ),
        )
        for row in (author, verifier)
    )
    data = PlanPayload(
        company_id=COMPANY,
        plan=WorkPlan(
            company_id=COMPANY,
            plan_id=uuid4(),
            goal_id=GOAL,
            revision=1,
            items=tuple(
                WorkItem(
                    company_id=COMPANY,
                    task_id=row.binding.task_id,
                    trace_id=row.binding.trace_id,
                    goal_id=GOAL,
                    department="research",
                    title="Read/check internal report",
                    acceptance=REPORT_CHECK_CRITERIA,
                    budget_usd=row.allocation_usd,
                )
                for row in children
            ),
        ),
        mandate=mref,
        goal=gref,
        charters=(cref,),
        children=children,
        procedure=ProcedureRoot(
            company_id=COMPANY,
            procedure_id=uuid4(),
            goal_id=GOAL,
            binding=parent,
            allocation_usd=Decimal(1),
            quota=AttemptQuota(),
        ),
        verification=(
            VerificationIntent(
                company_id=COMPANY,
                author_task_id=author.task_id,
                verifier_task_id=verifier.task_id,
                check_recipe=REPORT_CHECK_RECIPE,
            ),
        ),
    )
    return ManagementPlanStore(factory, catalog), data


async def authorized_action(
    factory: async_sessionmaker[AsyncSession],
    bound: RunBinding,
    *,
    tool: str = "fake.internal.read.v1",
    version: str = "v1",
    resource: str = "company.report",
) -> ActionProposal:
    """Persist actual exact owner approval/hold; no model or tool is invoked."""
    scope = LedgerScope(
        company_id=COMPANY,
        principal_id=bound.actor_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
    )
    data = ActionProposal(
        company_id=COMPANY,
        action_id=uuid4(),
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        actor_id=bound.actor_id,
        revision=1,
        tool=tool,
        tool_version=version,
        resource=resource,
        parameters={"operation": "read"},
        policy_version="fixture-policy",
        price_version="fixture-prices",
        estimated_cost_usd=Decimal("0.030000"),
    )
    journal = CompanyJournal(factory)
    await journal.submit(data, scope)
    await journal.approve_registered(
        scope.model_copy(update={"principal_id": OWNER}),
        data.action_id,
        action_hash(data),
        datetime.now(UTC),
        identity=identity(OWNER),
    )
    await journal.authorize_registered(
        scope, data.action_id, datetime.now(UTC), (), identity=identity(bound.actor_id)
    )
    return data


async def derived_output(
    factory: async_sessionmaker[AsyncSession], root: Path
) -> ArtifactRevisionRef:
    """Persist a derived output with its real input provenance through public ingestion."""
    # This nested source-reader fixture exceeds 50 lines to retain exact provenance identities.
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        head = await session.get(BrainSourceHead, (COMPANY, SOURCE))
        assert head is not None
        row = await session.get(BrainSourceRevision, (COMPANY, head.current_revision_id))
        assert row is not None
        original = SourceRevisionRef(
            company_id=COMPANY,
            source_id=SOURCE,
            source_revision_id=row.source_revision_id,
            revision=row.revision,
        )
    raw = b"Actual bounded derived output with retained source contributors."
    artifact = ArtifactRevisionRef(
        company_id=COMPANY,
        artifact_id=uuid4(),
        artifact_revision_id=uuid4(),
        revision="derived-v1",
        sha256=hashlib.sha256(raw).hexdigest(),
        byte_length=len(raw),
    )
    source_id = uuid4()
    derivation = DerivationRecord(
        company_id=COMPANY,
        derivation_id=uuid4(),
        artifact=artifact,
        recipe_version="fixture-derived-v1",
        kind="summary",
        contributors=(original,),
        recorded_at=datetime.now(UTC),
    )

    class DerivedReader:
        async def read(self, registration: SourceRegistration, revision: str) -> SourceSnapshot:
            return SourceSnapshot(
                company_id=COMPANY,
                source_id=source_id,
                source_symbol="fixture.derived-plan.v1",
                external_key="derived-plan",
                revision=revision,
                raw_bytes=raw,
                source_event=SourceTime(
                    precision="unknown", value=None, basis="offline fixture-derived output"
                ),
                derivation=derivation,
            )

    policy = derived_policy()
    store = BrainIngestionStore(
        factory,
        SourceRegistry((policy,), DerivedReader()),
        ProtectedBlobStore(root, storage_symbol="fixture.blobs.v1"),
    )
    await store.register(
        owner_scope(),
        identity(OWNER),
        SourceRegistration(
            company_id=COMPANY,
            source_id=source_id,
            resource=ResourceRef(company_id=COMPANY, resource_id=DERIVED_RESOURCE),
            source_symbol="fixture.derived-plan.v1",
            external_key="derived-plan",
        ),
        readers=(OWNER, ACTOR, VERIFIER),
    )
    await store.ingest(
        owner_scope(),
        identity(OWNER),
        IngestCommand(
            company_id=COMPANY, source_id=source_id, revision=artifact.revision, artifact=artifact
        ),
    )
    return artifact


def derived_policy() -> SourcePolicy:
    """The actual fixture's operator-supplied NoTTL policy, never inferred from nullable SQL."""
    return SourcePolicy(
        source_symbol="fixture.derived-plan.v1",
        authority_profile="fixture-derived-v1",
        data_classification="internal",
        origin_kind="derived",
        media_type="text/plain",
        parser_version="utf8-identity-v1",
        chunker_version="utf8-sections-v1",
        search_config="simple",
        freshness_seconds=None,
        allowed_external_keys=frozenset({"derived-plan"}),
    )


def registered_freshness(factory: async_sessionmaker[AsyncSession]) -> RegisteredSourceFreshness:
    """Configure the same source policies used for original and derived public ingestion."""
    from nexus.tests.integration.management_acceptance_source_fixture import Policies

    policies = Policies()
    policy = derived_policy()
    policies.values[policy.source_symbol] = policy
    return RegisteredSourceFreshness(factory, policies)

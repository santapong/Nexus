"""New empty-model owner sender through actual public company/source/governance stores."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.evidence_models import BrainEvidence
from nexus.company.brain.retrieval import RetrievalLimits
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.brain.sources import EvidenceRef
from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.work import WorkItem, WorkPlan
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.artifact_target_store import ArtifactTargetStore
from nexus.company.management.base import RevisionRef
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.control_store import ManagementControlStore
from nexus.company.management.goal_store import GoalStore
from nexus.company.management.goals import GoalRevisionRef
from nexus.company.management.governance import CharterRevisionRef
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plan_support import NamedPlanResource, PlanAdmissionCatalog
from nexus.company.management.plans import ChildAllocation, PlanPayload, ProcedureRoot, RunBinding
from nexus.company.notifications.native_profile_contracts import NativeNotificationProfile
from nexus.core.llm.company_registry import ModelRegistry
from nexus.execution.effect_store import EffectStore
from nexus.execution.runtime_contracts import AttemptQuota
from nexus.execution.runtime_store import ExecutionStore
from nexus.harness.canonical import action_hash
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.standing_contracts import ToolPermission
from nexus.settings import settings
from nexus.tests.integration.management_acceptance_source_fixture import Policies
from nexus.tests.integration.test_company_brain_ingestion import (
    RESOURCE,
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
from nexus.tests.management_control_support import charter, mandate

TOOL, SYMBOL = "company.owner-notification.send.v1", "owner.notifications"


@pytest.fixture
async def notification_native_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Own exactly the newly assigned database and normal migration lineage."""
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_notification_native_profiles"
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


@dataclass(frozen=True)
class NotificationNativeScenario:
    """Publicly registered source/governance composition, without a send client or draft."""

    catalog: PlanAdmissionCatalog
    payload: PlanPayload
    runtime: ExecutionStore
    effects: EffectStore
    artifacts: BoundedArtifactReader
    freshness: RegisteredSourceFreshness

    @property
    def sender(self) -> RunBinding:
        """Declared native sender metadata; current allowance still requires database checks."""
        return self.payload.children[0].binding

    @property
    def scope(self) -> LedgerScope:
        """Retain the actual child company/actor/task/trace through journal/runtime calls."""
        bound = self.sender
        return LedgerScope(
            company_id=COMPANY,
            principal_id=bound.actor_id,
            task_id=bound.task_id,
            trace_id=bound.trace_id,
        )


async def notification_source(
    factory: async_sessionmaker[AsyncSession], root: Path
) -> tuple[PersistentBrainRetriever, EvidenceRef]:
    """Assert the actual public parser receipt before resolving protected evidence."""
    raw = b"Citation coverage baseline: 0. Synthetic owner-notification admission source."
    ingestion = await configured(factory, root, Reader({"r1": raw}))
    receipt = await ingestion.ingest(owner_scope(), identity(OWNER), command(raw, "r1"))
    assert receipt.status == "accepted" and receipt.reason_code is None, receipt.model_dump_json()
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        evidence_id = await session.scalar(select(BrainEvidence.evidence_id))
    assert evidence_id is not None
    return (
        PersistentBrainRetriever(
            factory,
            ProtectedBlobStore(root, storage_symbol="fixture.blobs.v1"),
            limits=RetrievalLimits(),
        ),
        EvidenceRef(company_id=COMPANY, evidence_id=evidence_id),
    )


async def notification_native_scenario(
    factory: async_sessionmaker[AsyncSession],
    root: Path,
    *,
    actor: UUID = OWNER,
    register: bool = True,
) -> NotificationNativeScenario:
    """Public synthetic setup only; no model registry health, draft, credential or transport."""
    # Keep the complete >50-line public fixture visible; it creates no fake operative rows.
    retriever, evidence = await notification_source(factory, root)
    controls = ManagementControlStore(factory)
    published_mandate = await controls.publish_mandate(
        control(), identity(OWNER), mandate(), expected_revision_id=None
    )
    mref = RevisionRef.model_validate_json(
        published_mandate.model_dump_json(include=set(RevisionRef.model_fields))
    )
    target = ResourceRef(company_id=COMPANY, resource_id=uuid4())
    await ArtifactTargetStore(factory).provision(
        owner_scope(), identity(OWNER), target, readers=(OWNER, ACTOR)
    )
    published_charter = await controls.publish_charter(
        control(),
        identity(OWNER),
        charter(verifier=ACTOR).model_copy(
            update={
                "department_id": uuid4(),
                "name": "notifications",
                "allowed_tools": (TOOL,),
                "resource_scopes": ("company.source", SYMBOL),
                "responsibilities": ("Bounded owner notification admission fixture",),
                "deliverables": ("Exact native intent; no delivery claim",),
            }
        ),
        mandate=mref,
        expected_revision_id=None,
    )
    cref = CharterRevisionRef.model_validate_json(
        published_charter.model_dump_json(include=set(CharterRevisionRef.model_fields))
    )
    published_goal = await GoalStore(factory, retriever).publish(
        control(),
        identity(OWNER),
        goal(mref, evidence).model_copy(
            update={"owner_id": OWNER, "title": "Synthetic native owner notification admission"}
        ),
        version="native-notification-v1",
        expected_revision_id=None,
    )
    gref = GoalRevisionRef.model_validate_json(
        published_goal.model_dump_json(include=set(GoalRevisionRef.model_fields))
    )
    registry = ModelRegistry(
        company_id=COMPANY,
        revision="notification-native-fixture-v1",
        pricebook_version="fixture-prices",
    )
    profile = NativeNotificationProfile(
        company_id=COMPANY,
        execution_profile="notification.native.v1",
        workflow_name="internal.owner-notification",
        registry_revision=registry.revision,
        registry_sha256=canonical_sha256(registry),
        target_symbol=SYMBOL,
        target_resource=target,
    )
    catalog = PlanAdmissionCatalog(
        company_id=COMPANY,
        models=registry,
        admitted_profiles=frozenset(),
        check_recipes=frozenset(),
        tools=(ToolPermission(tool=TOOL, tool_version="v1", resource=SYMBOL),),
        resources=(
            NamedPlanResource(
                symbol="company.source",
                resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
            ),
            NamedPlanResource(symbol=SYMBOL, resource=target),
        ),
        notification_profiles=(profile,),
    )

    def binding(principal: UUID) -> RunBinding:
        return RunBinding(
            company_id=COMPANY,
            workspace_id=WORKSPACE,
            actor_id=principal,
            task_id=uuid4(),
            trace_id=uuid4(),
            run_id=uuid4(),
            workflow_name=profile.workflow_name,
            workflow_version="v1",
            model_profile=profile.execution_profile,
            model_registry_version=registry.revision,
        )

    sender, parent = binding(actor), binding(OWNER)
    quota = AttemptQuota(model_requests=0, tool_attempts=1, rework_rounds=0, plan_revisions=0)
    item = WorkItem(
        company_id=COMPANY,
        task_id=sender.task_id,
        trace_id=sender.trace_id,
        goal_id=gref.goal_id,
        department="notifications",
        title="Exact native sender admission only",
        acceptance=("provider-submission-evidence",),
        budget_usd=Decimal("0.1"),
    )
    payload = PlanPayload(
        company_id=COMPANY,
        mandate=mref,
        goal=gref,
        charters=(cref,),
        children=(
            ChildAllocation(
                company_id=COMPANY,
                binding=sender,
                charter=cref,
                allocation_usd=item.budget_usd,
                quota=quota,
            ),
        ),
        procedure=ProcedureRoot(
            company_id=COMPANY,
            procedure_id=uuid4(),
            goal_id=gref.goal_id,
            binding=parent,
            allocation_usd=Decimal("1"),
            quota=quota,
        ),
        plan=WorkPlan(
            company_id=COMPANY, plan_id=uuid4(), goal_id=gref.goal_id, revision=1, items=(item,)
        ),
    )
    artifacts = BoundedArtifactReader(
        factory, ProtectedBlobStore(root, storage_symbol="fixture.blobs.v1")
    )
    freshness = RegisteredSourceFreshness(factory, Policies())
    plans = ManagementPlanStore(factory, catalog, source_freshness=freshness)
    if register:
        proposed = await plans.propose(
            control(), identity(OWNER), payload, expected_current_revision_id=None
        )
        await plans.approve_and_register(
            control(),
            identity(OWNER),
            proposed.plan_revision_id,
            proposed.sha256,
            expected_current_revision_id=proposed.plan_revision_id,
        )
    return NotificationNativeScenario(
        catalog,
        payload,
        ExecutionStore(
            factory,
            management_catalog=catalog,
            management_artifacts=artifacts,
            management_freshness=freshness,
        ),
        EffectStore(
            factory,
            management_catalog=catalog,
            management_artifacts=artifacts,
            management_freshness=freshness,
        ),
        artifacts,
        freshness,
    )


async def notification_action(
    factory: async_sessionmaker[AsyncSession],
    case: NotificationNativeScenario,
    *,
    tool: str = TOOL,
    approve: bool = True,
) -> ActionProposal:
    """Submit actual exact native approval/hold; generic admission performs no send."""
    bound = case.sender
    proposal = ActionProposal(
        company_id=COMPANY,
        action_id=uuid4(),
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        actor_id=bound.actor_id,
        revision=1,
        tool=tool,
        tool_version="v1",
        resource=SYMBOL,
        parameters={"operation": "notification-admission-fixture-only"},
        policy_version="fixture-policy",
        price_version="fixture-prices",
        estimated_cost_usd=Decimal(".03"),
    )
    journal = CompanyJournal(factory)
    await journal.submit(proposal, case.scope)
    if approve:
        await journal.approve_registered(
            case.scope.model_copy(update={"principal_id": OWNER}),
            proposal.action_id,
            action_hash(proposal),
            datetime.now(UTC),
            identity=identity(OWNER),
        )
        await journal.authorize_registered(
            case.scope, proposal.action_id, datetime.now(UTC), (), identity=identity(bound.actor_id)
        )
    return proposal

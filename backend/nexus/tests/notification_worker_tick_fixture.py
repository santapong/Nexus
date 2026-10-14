"""Separate native engineering decision and owner sender; no provider or action approval."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.brain.sources import EvidenceRef
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.artifact_target_store import ArtifactTargetStore
from nexus.company.management.base import RevisionRef
from nexus.company.management.control_store import ManagementControlStore
from nexus.company.management.goal_store import GoalStore
from nexus.company.management.goals import GoalRevisionRef
from nexus.company.management.governance import CharterRevisionRef
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.company.management.plans import (
    PlanPayload,
)
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import LedgerScope
from nexus.settings import settings
from nexus.tests.integration.test_company_brain_ingestion import owner_scope
from nexus.tests.integration.test_company_directory import (
    ACTOR,
    COMPANY,
    OWNER,
    control,
    migrate,
)
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_management_goals import goal
from nexus.tests.management_control_support import charter, mandate
from nexus.tests.notification_native_profile_fixture import notification_source
from nexus.tests.notification_worker_tick_declarations import (
    BUILDER_TOOL,
    NOTIFY_TOOL,
    SOURCE_SYMBOL,
    TARGET_SYMBOL,
    native_payload,
    tick_catalog,
)


@pytest.fixture
async def worker_tick_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """No use until Root reviews this source and explicitly releases the assigned empty DB."""
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_notification_worker_tick"
    admin = create_async_engine(url)
    app = create_async_engine(url.set(username="nexus_company_app"))
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
                await connection.execute(text("TRUNCATE company_brain_events CASCADE"))
                await connection.run_sync(migrate, "downgrade")
        await admin.dispose()


@dataclass(frozen=True)
class WorkerTickNativeCase:
    catalog: PlanAdmissionCatalog
    notification: PlanPayload
    source: PlanPayload
    source_action: ActionProposal
    source_scope: LedgerScope
    plans: ManagementPlanStore


async def public_charter(
    factory: async_sessionmaker[AsyncSession],
    mref: RevisionRef,
    *,
    notification: bool,
) -> CharterRevisionRef:
    declared = charter(verifier=ACTOR if notification else OWNER).model_copy(
        update={
            "department_id": uuid4(),
            "name": "notifications" if notification else "engineering",
            "allowed_tools": (NOTIFY_TOOL,) if notification else (BUILDER_TOOL,),
            "resource_scopes": (SOURCE_SYMBOL, TARGET_SYMBOL) if notification else (SOURCE_SYMBOL,),
            "responsibilities": ("Synthetic native decision read/preparation fixture",),
            "deliverables": ("Actual pending evidence only; no business completion",),
        }
    )
    published = await ManagementControlStore(factory).publish_charter(
        control(),
        identity(OWNER),
        declared,
        mandate=mref,
        expected_revision_id=None,
    )
    return CharterRevisionRef.model_validate_json(
        published.model_dump_json(include=set(CharterRevisionRef.model_fields))
    )


async def source_pending(
    factory: async_sessionmaker[AsyncSession],
    source: PlanPayload,
) -> tuple[ActionProposal, LedgerScope]:
    bound = source.children[0].binding
    scope = LedgerScope(
        company_id=COMPANY,
        principal_id=bound.actor_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
    )
    action = ActionProposal(
        company_id=COMPANY,
        action_id=uuid4(),
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        actor_id=bound.actor_id,
        revision=1,
        tool=BUILDER_TOOL,
        tool_version="v1",
        resource=SOURCE_SYMBOL,
        parameters={"operation": "synthetic-pending-decision-only"},
        policy_version="fixture-policy",
        price_version="fixture-prices",
        estimated_cost_usd=Decimal(".01"),
    )
    await CompanyJournal(factory).submit(action, scope)
    return action, scope


async def worker_tick_native_case(
    factory: async_sessionmaker[AsyncSession],
    root: Path,
) -> WorkerTickNativeCase:
    retriever, evidence = await notification_source(factory, root)
    goal_ids = (uuid4(), uuid4())
    admitted = await ManagementControlStore(factory).publish_mandate(
        control(),
        identity(OWNER),
        mandate().model_copy(update={"goals": goal_ids}),
        expected_revision_id=None,
    )
    mref = RevisionRef.model_validate_json(
        admitted.model_dump_json(include=set(RevisionRef.model_fields))
    )
    target = ResourceRef(company_id=COMPANY, resource_id=uuid4())
    await ArtifactTargetStore(factory).provision(
        owner_scope(), identity(OWNER), target, readers=(OWNER, ACTOR)
    )
    catalog = tick_catalog(target)
    payloads = await public_payloads(factory, retriever, evidence, mref, goal_ids)
    plans = ManagementPlanStore(factory, catalog)
    for payload in payloads:
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
    action, scope = await source_pending(factory, payloads[1])
    assert action.task_id != payloads[0].children[0].binding.task_id and action.tool != NOTIFY_TOOL
    assert payloads[0].goal.goal_id != payloads[1].goal.goal_id and catalog.models.models == ()
    return WorkerTickNativeCase(catalog, payloads[0], payloads[1], action, scope, plans)


async def public_payloads(
    factory: async_sessionmaker[AsyncSession],
    retriever: PersistentBrainRetriever,
    evidence: EvidenceRef,
    mref: RevisionRef,
    goal_ids: tuple[UUID, UUID],
) -> tuple[PlanPayload, PlanPayload]:
    payloads = []
    for number, notification in enumerate((True, False)):
        cref = await public_charter(factory, mref, notification=notification)
        published = await GoalStore(factory, retriever).publish(
            control(),
            identity(OWNER),
            goal(mref, evidence).model_copy(
                update={
                    "goal_id": goal_ids[number],
                    "owner_id": OWNER,
                    "title": "Synthetic sender review"
                    if notification
                    else "Synthetic engineering decision",
                }
            ),
            version="tick-native-v1",
            expected_revision_id=None,
        )
        gref = GoalRevisionRef.model_validate_json(
            published.model_dump_json(include=set(GoalRevisionRef.model_fields))
        )
        payloads.append(native_payload(mref, gref, cref, notification=notification))
    return payloads[0], payloads[1]

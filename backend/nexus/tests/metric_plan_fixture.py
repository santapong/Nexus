"""Actual owner metric declaration/plan revision before any report effect; fixture only."""

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.retrieval import RetrievalLimits
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.management.generated_artifact_contracts import (
    GeneratedArtifactRule,
)
from nexus.company.management.goal_store import GoalStore
from nexus.company.management.goals import GoalDefinition, GoalRevisionRef
from nexus.company.management.governance_models import ManagementGoalRevision
from nexus.company.management.lifecycle import PlanRevision
from nexus.company.management.metric_contracts import NATIVE_REPORT_COUNT
from nexus.company.management.plan_models import ManagementPlanHead
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plans import PlanPayload
from nexus.company.management.transactions import management_owner_transaction
from nexus.tests.generated_artifact_fixture import admitted_generated_plan
from nexus.tests.integration.management_acceptance_source_fixture import Policies
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity


async def declared_metric_plan(
    factory: async_sessionmaker[AsyncSession],
    root: Path,
    *,
    recipe: str | None = NATIVE_REPORT_COUNT,
    unit: str = "count",
) -> tuple[
    ManagementPlanStore,
    PlanPayload,
    tuple[GeneratedArtifactRule, ...],
    Policies,
    PersistentBrainRetriever,
    ProtectedBlobStore,
    PlanRevision,
]:
    plans, payload, rules, policies = await admitted_generated_plan(factory, root, production=True)
    blobs = ProtectedBlobStore(root, storage_symbol="fixture.blobs.v1")
    retriever = PersistentBrainRetriever(factory, blobs, limits=RetrievalLimits())
    async with management_owner_transaction(factory, control(), identity(OWNER)) as (session, _, _):
        row = await session.get(ManagementGoalRevision, (COMPANY, payload.goal.revision_id))
        head = await session.get(ManagementPlanHead, (COMPANY, payload.plan.plan_id))
        assert row is not None and head is not None
        definition = GoalDefinition.model_validate_json(row.payload_json)
        current = head.current_revision_id
    data = definition.model_copy(
        update={
            "metrics": tuple(
                item.model_copy(update={"observation_recipe": recipe, "unit": unit})
                for item in definition.metrics
            )
        }
    )
    goal = await GoalStore(factory, retriever).publish(
        control(),
        identity(OWNER),
        data,
        version="metric-v2",
        expected_revision_id=payload.goal.revision_id,
    )
    ref = GoalRevisionRef.model_validate_json(
        goal.model_dump_json(include=set(GoalRevisionRef.model_fields))
    )
    payload = payload.model_copy(
        update={"goal": ref, "plan": payload.plan.model_copy(update={"revision": 2})}
    )
    proposed = await plans.propose(
        control(), identity(OWNER), payload, expected_current_revision_id=current
    )
    approved = await plans.approve_and_register(
        control(),
        identity(OWNER),
        proposed.plan_revision_id,
        proposed.sha256,
        expected_current_revision_id=current,
    )
    return plans, payload, rules, policies, retriever, blobs, approved

"""Restricted normal015 public setup for a new synthetic zero-model engineering plan."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.retrieval import RetrievalLimits
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.control_store import ManagementControlStore
from nexus.company.management.goal_store import GoalStore
from nexus.company.management.goals import GoalRevisionRef
from nexus.company.management.governance import CharterRevisionRef
from nexus.company.management.native_execution_profiles import (
    NATIVE_CRITERIA,
    NativeExecutionProfile,
)
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plans import PlanPayload
from nexus.core.llm.company_registry import ModelRegistry
from nexus.execution.runtime_contracts import AttemptQuota
from nexus.harness.standing_contracts import ToolPermission
from nexus.settings import settings
from nexus.tests.integration.test_company_directory import OWNER, control, migrate
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_management_goals import goal
from nexus.tests.management_control_support import charter
from nexus.tests.management_plan_support import VERIFIER, configured_plan


@pytest.fixture
async def native_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Own only the new disposable database; never use retained builder or other worker DBs."""
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_native_profiles"
    admin = create_async_engine(url)
    app = create_async_engine(url.set(username="nexus_company_app"))
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
                await connection.execute(text("TRUNCATE public.company_brain_events CASCADE"))
                await connection.run_sync(migrate, "downgrade")
        await admin.dispose()


async def native_plan(
    factory: async_sessionmaker[AsyncSession], root: Path
) -> tuple[ManagementPlanStore, PlanPayload]:
    """Replace only unregistered fixture declarations through public current owner stores."""
    # Keep this >50-line fixture construction adjacent: it issues no process or model request.
    original, data = await configured_plan(factory, root)
    controls = ManagementControlStore(factory)
    published = await controls.publish_charter(
        control(),
        identity(OWNER),
        charter("v2", verifier=VERIFIER).model_copy(
            update={
                "allowed_tools": ("company.builder.run.v1",),
                "responsibilities": ("Verify a synthetic mechanical change",),
            }
        ),
        mandate=data.mandate,
        expected_revision_id=data.charters[0].revision_id,
    )
    cref = CharterRevisionRef.model_validate_json(
        published.model_dump_json(include=set(CharterRevisionRef.model_fields))
    )
    retriever = PersistentBrainRetriever(
        factory,
        ProtectedBlobStore(root, storage_symbol="fixture.blobs.v1"),
        limits=RetrievalLimits(),
    )
    published_goal = await GoalStore(factory, retriever).publish(
        control(),
        identity(OWNER),
        goal(data.mandate).model_copy(
            update={
                "title": "Verify synthetic mechanical fixture; business readiness unproven",
            }
        ),
        version="v2",
        expected_revision_id=data.goal.revision_id,
    )
    gref = GoalRevisionRef.model_validate_json(
        published_goal.model_dump_json(include=set(GoalRevisionRef.model_fields))
    )
    registry = ModelRegistry(
        company_id=data.company_id,
        revision=original.catalog.models.revision,
        pricebook_version=original.catalog.models.pricebook_version,
    )
    permission = ToolPermission(
        tool="company.builder.run.v1", tool_version="v1", resource="company.report"
    )
    profiles = (
        NativeExecutionProfile(
            company_id=data.company_id,
            execution_profile="engineering.native.v1",
            workflow_name="engineering.change",
            registry_revision=registry.revision,
            registry_sha256=canonical_sha256(registry),
            tools=(permission,),
        ),
        NativeExecutionProfile(
            company_id=data.company_id,
            execution_profile="verification.native.v1",
            workflow_name="engineering.verify",
            registry_revision=registry.revision,
            registry_sha256=canonical_sha256(registry),
            tools=(permission,),
        ),
    )
    children = tuple(
        child.model_copy(
            update={
                "charter": cref,
                "quota": AttemptQuota(
                    model_requests=0, tool_attempts=1, rework_rounds=0, plan_revisions=0
                ),
                "binding": child.binding.model_copy(
                    update={
                        "workflow_name": profile.workflow_name,
                        "workflow_version": profile.workflow_version,
                        "model_profile": profile.execution_profile,
                        "model_registry_version": registry.revision,
                    }
                ),
            }
        )
        for child, profile in zip(data.children, profiles, strict=True)
    )
    updated = data.model_copy(
        update={
            "goal": gref,
            "charters": (cref,),
            "children": children,
            "procedure": data.procedure.model_copy(
                update={
                    "quota": AttemptQuota(model_requests=0),
                    "binding": data.procedure.binding.model_copy(
                        update={
                            "workflow_name": "engineering.change",
                            "workflow_version": "v1",
                            "model_profile": "engineering.native.v1",
                            "model_registry_version": registry.revision,
                        }
                    ),
                }
            ),
            "plan": data.plan.model_copy(
                update={
                    "items": tuple(
                        item.model_copy(update={"acceptance": NATIVE_CRITERIA})
                        for item in data.plan.items
                    )
                }
            ),
            "verification": (
                data.verification[0].model_copy(
                    update={
                        "check_recipe": "native-engineering-change-v1",
                    }
                ),
            ),
        }
    )
    catalog = original.catalog.model_copy(
        update={
            "models": registry,
            "tools": (permission,),
            "admitted_profiles": frozenset(),
            "check_recipes": frozenset({"native-engineering-change-v1"}),
            "native_profiles": profiles,
        }
    )
    return ManagementPlanStore(factory, catalog), PlanPayload.model_validate_json(
        updated.model_dump_json()
    )

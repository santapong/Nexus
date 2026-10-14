"""Public owner-approved native sender setup; synthetic sources/registry, no runtime imports."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.management.artifact_target_store import ArtifactTargetStore
from nexus.company.management.control_store import ManagementControlStore
from nexus.company.management.governance import CharterRevisionRef
from nexus.company.management.lifecycle import PlanRevision
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plan_support import NamedPlanResource, PlanAdmissionCatalog
from nexus.company.management.plans import ChildAllocation, PlanPayload
from nexus.company.notifications.proposals import NOTIFICATION_TOOL
from nexus.execution.runtime_contracts import AttemptQuota
from nexus.harness.standing_contracts import ToolPermission
from nexus.tests.integration.test_company_brain_ingestion import owner_scope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.management_control_support import charter
from nexus.tests.management_plan_support import VERIFIER, binding


async def sender_plan(
    factory: async_sessionmaker[AsyncSession],
    payload: PlanPayload,
    previous: PlanRevision,
    catalog: PlanAdmissionCatalog,
    plans: ManagementPlanStore,
) -> tuple[ManagementPlanStore, PlanPayload, PlanRevision, ResourceRef]:
    """Fixture public provision/charter/propose/approve only; no production task minting."""
    target = ResourceRef(company_id=COMPANY, resource_id=uuid4())
    await ArtifactTargetStore(factory).provision(
        owner_scope(), identity(OWNER), target, readers=(OWNER, VERIFIER)
    )
    admitted = PlanAdmissionCatalog.model_validate_json(
        catalog.model_copy(
            update={
                "tools": (
                    *catalog.tools,
                    ToolPermission(
                        tool=NOTIFICATION_TOOL, tool_version="v1", resource="owner.notifications"
                    ),
                ),
                "resources": (
                    *catalog.resources,
                    NamedPlanResource(symbol="owner.notifications", resource=target),
                ),
            }
        ).model_dump_json()
    )
    definition = charter("notification.v1", verifier=VERIFIER).model_copy(
        update={
            "department_id": uuid4(),
            "name": "notifications",
            "allowed_tools": (NOTIFICATION_TOOL,),
            "resource_scopes": tuple(row.symbol for row in admitted.resources),
        }
    )
    recorded = await ManagementControlStore(factory).publish_charter(
        control(), identity(OWNER), definition, mandate=payload.mandate, expected_revision_id=None
    )
    reference = CharterRevisionRef.model_validate_json(
        recorded.model_dump_json(include=set(CharterRevisionRef.model_fields))
    )
    sender = binding(OWNER).model_copy(update={"workflow_name": "internal.owner-notification"})
    child = ChildAllocation(
        company_id=COMPANY,
        binding=sender,
        charter=reference,
        allocation_usd=Decimal(".1"),
        quota=AttemptQuota(model_requests=0, tool_attempts=1, rework_rounds=0, plan_revisions=0),
    )
    from nexus.company.contracts.work import WorkItem

    item = WorkItem(
        company_id=COMPANY,
        task_id=sender.task_id,
        trace_id=sender.trace_id,
        goal_id=payload.goal.goal_id,
        department="notifications",
        title="Synthetic UAT: exact owner notification submission",
        acceptance=("provider-submission-evidence",),
        budget_usd=child.allocation_usd,
    )
    data = PlanPayload.model_validate_json(
        payload.model_copy(
            update={
                "plan": payload.plan.model_copy(
                    update={
                        "revision": payload.plan.revision + 1,
                        "items": (*payload.plan.items, item),
                    }
                ),
                "charters": (*payload.charters, reference),
                "children": (*payload.children, child),
            }
        ).model_dump_json()
    )
    current_plans = ManagementPlanStore(factory, admitted, source_freshness=plans.source_freshness)
    proposed = await current_plans.propose(
        control(), identity(OWNER), data, expected_current_revision_id=previous.plan_revision_id
    )
    approved = await current_plans.approve_and_register(
        control(),
        identity(OWNER),
        proposed.plan_revision_id,
        proposed.sha256,
        expected_current_revision_id=previous.plan_revision_id,
    )
    return current_plans, data, approved, target

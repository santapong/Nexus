"""Separate native engineering decision and owner sender; no provider or action approval."""

from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.contracts.work import WorkItem, WorkPlan
from nexus.company.management.base import RevisionRef
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.goals import GoalRevisionRef
from nexus.company.management.governance import CharterRevisionRef
from nexus.company.management.native_execution_profiles import (
    NATIVE_CRITERIA,
    NativeExecutionProfile,
)
from nexus.company.management.plan_support import NamedPlanResource, PlanAdmissionCatalog
from nexus.company.management.plans import (
    ChildAllocation,
    PlanPayload,
    ProcedureRoot,
    RunBinding,
    VerificationIntent,
)
from nexus.company.notifications.native_profile_contracts import NativeNotificationProfile
from nexus.core.llm.company_registry import ModelRegistry
from nexus.execution.runtime_contracts import AttemptQuota
from nexus.harness.standing_contracts import ToolPermission
from nexus.tests.integration.test_company_brain_ingestion import RESOURCE
from nexus.tests.integration.test_company_directory import (
    ACTOR,
    COMPANY,
    OWNER,
    WORKSPACE,
)

NOTIFY_TOOL = "company.owner-notification.send.v1"
BUILDER_TOOL = "company.builder.run.v1"
SOURCE_SYMBOL = "company.source"
TARGET_SYMBOL = "owner.notifications"


def tick_catalog(target: ResourceRef) -> PlanAdmissionCatalog:
    registry = ModelRegistry(
        company_id=COMPANY, revision="tick-native-v1", pricebook_version="fixture-prices"
    )
    builder = ToolPermission(tool=BUILDER_TOOL, tool_version="v1", resource=SOURCE_SYMBOL)
    return PlanAdmissionCatalog(
        company_id=COMPANY,
        models=registry,
        admitted_profiles=frozenset(),
        check_recipes=frozenset({"native-engineering-change-v1"}),
        native_profiles=native_profiles(registry, builder),
        notification_profiles=(
            NativeNotificationProfile(
                company_id=COMPANY,
                execution_profile="notification.native.v1",
                workflow_name="internal.owner-notification",
                registry_revision=registry.revision,
                registry_sha256=canonical_sha256(registry),
                target_symbol=TARGET_SYMBOL,
                target_resource=target,
            ),
        ),
        tools=(
            builder,
            ToolPermission(tool=NOTIFY_TOOL, tool_version="v1", resource=TARGET_SYMBOL),
        ),
        resources=(
            NamedPlanResource(
                symbol=SOURCE_SYMBOL, resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE)
            ),
            NamedPlanResource(symbol=TARGET_SYMBOL, resource=target),
        ),
    )


def native_binding(actor: UUID, profile: str, workflow: str) -> RunBinding:
    return RunBinding(
        company_id=COMPANY,
        workspace_id=WORKSPACE,
        actor_id=actor,
        task_id=uuid4(),
        trace_id=uuid4(),
        run_id=uuid4(),
        workflow_name=workflow,
        workflow_version="v1",
        model_profile=profile,
        model_registry_version="tick-native-v1",
    )


def native_child(bound: RunBinding, cref: CharterRevisionRef) -> ChildAllocation:
    return ChildAllocation(
        company_id=COMPANY,
        binding=bound,
        charter=cref,
        allocation_usd=Decimal(".1"),
        quota=AttemptQuota(model_requests=0, tool_attempts=1, rework_rounds=0, plan_revisions=0),
    )


def native_item(bound: RunBinding, gref: GoalRevisionRef, *, notification: bool) -> WorkItem:
    return WorkItem(
        company_id=COMPANY,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        goal_id=gref.goal_id,
        department="notifications" if notification else "engineering",
        title="Synthetic pending notification"
        if notification
        else "Synthetic native engineering decision",
        acceptance=("provider-submission-evidence",) if notification else NATIVE_CRITERIA,
        budget_usd=Decimal(".1"),
    )


def native_payload(
    mref: RevisionRef,
    gref: GoalRevisionRef,
    cref: CharterRevisionRef,
    *,
    notification: bool,
) -> PlanPayload:
    children: tuple[ChildAllocation, ...]
    if notification:
        profile, workflow = "notification.native.v1", "internal.owner-notification"
        children = (native_child(native_binding(OWNER, profile, workflow), cref),)
    else:
        profile, workflow = "engineering.native.v1", "engineering.change"
        children = (
            native_child(native_binding(ACTOR, profile, workflow), cref),
            native_child(
                native_binding(OWNER, "verification.native.v1", "engineering.verify"), cref
            ),
        )
    return PlanPayload(
        company_id=COMPANY,
        mandate=mref,
        goal=gref,
        charters=(cref,),
        children=children,
        procedure=native_procedure(gref, profile, workflow, len(children)),
        plan=WorkPlan(
            company_id=COMPANY,
            plan_id=uuid4(),
            goal_id=gref.goal_id,
            revision=1,
            items=tuple(
                native_item(row.binding, gref, notification=notification) for row in children
            ),
        ),
        verification=native_edge(children) if not notification else (),
    )


def native_procedure(
    gref: GoalRevisionRef, profile: str, workflow: str, count: int
) -> ProcedureRoot:
    return ProcedureRoot(
        company_id=COMPANY,
        procedure_id=uuid4(),
        goal_id=gref.goal_id,
        binding=native_binding(OWNER, profile, workflow),
        allocation_usd=Decimal(".3"),
        quota=AttemptQuota(
            model_requests=0, tool_attempts=count, rework_rounds=0, plan_revisions=0
        ),
    )


def native_edge(children: tuple[ChildAllocation, ...]) -> tuple[VerificationIntent, ...]:
    return (
        VerificationIntent(
            company_id=COMPANY,
            author_task_id=children[0].binding.task_id,
            verifier_task_id=children[1].binding.task_id,
            check_recipe="native-engineering-change-v1",
        ),
    )


def native_profiles(
    registry: ModelRegistry, builder: ToolPermission
) -> tuple[NativeExecutionProfile, ...]:
    identities: tuple[
        tuple[
            Literal["engineering.native.v1", "verification.native.v1"],
            Literal["engineering.change", "engineering.verify"],
        ],
        ...,
    ] = (
        ("engineering.native.v1", "engineering.change"),
        ("verification.native.v1", "engineering.verify"),
    )
    return tuple(
        NativeExecutionProfile(
            company_id=COMPANY,
            execution_profile=profile,
            workflow_name=workflow,
            registry_revision=registry.revision,
            registry_sha256=canonical_sha256(registry),
            tools=(builder,),
        )
        for profile, workflow in identities
    )

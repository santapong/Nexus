"""New Nexus-shaped synthetic descriptions; no StockFlow data or execution qualification."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal, cast
from uuid import UUID, uuid5

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.contracts.work import WorkItem
from nexus.company.management.base import RevisionRef
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.check_contracts import REPORT_CHECK_CRITERIA, REPORT_CHECK_RECIPE
from nexus.company.management.goals import GoalRevisionRef
from nexus.company.management.governance import CharterRevisionRef
from nexus.company.management.lifecycle import PlanRevision
from nexus.company.management.native_execution_profiles import (
    NATIVE_CRITERIA,
    NativeExecutionProfile,
)
from nexus.company.management.nexus_cycle_admission import (
    NEXUS_ROLES,
    NexusCycleAdmission,
    NexusCycleSlot,
)
from nexus.company.management.plan_catalog import NamedPlanResource, PlanAdmissionCatalog
from nexus.company.management.planning_origin_contracts import PlanningOriginRef
from nexus.company.management.plans import ChildAllocation, ProcedureRoot, RunBinding
from nexus.company.notifications.native_profile_contracts import NativeNotificationProfile
from nexus.core.llm.company_pricing import PriceCard
from nexus.core.llm.company_registry import (
    EvaluationEvidence,
    ModelHealth,
    ModelRegistration,
    ModelRegistry,
)
from nexus.execution.runtime_contracts import AttemptQuota
from nexus.harness.standing_contracts import ToolPermission

COMPANY = UUID("b6794879-e4ce-5a64-aa4b-93b3d1858b33")
NOW = datetime(2026, 10, 16, 12, tzinfo=UTC)


def key(label: str) -> UUID:
    return uuid5(COMPANY, "nexus-cycle-component-v1:" + label)


def case() -> tuple[NexusCycleAdmission, PlanAdmissionCatalog]:
    now = datetime.now(UTC)
    # Supplied eligibility metadata for pure boundaries, never actual model qualification.
    model = ModelRegistration(
        registry_id="nexus-planner",
        provider="openai",
        model_id="gpt-5.4-mini-2026-03-17",
        endpoint_id="fixture.nexus",
        api_family="openai_responses",
        enabled=True,
        capabilities=frozenset({"text", "reasoning", "structured_output"}),
        allowed_data=frozenset({"public", "internal"}),
        context_window=400000,
        max_output_tokens=512,
        health=ModelHealth(
            status="healthy",
            checked_at=now - timedelta(minutes=1),
            expires_at=now + timedelta(seconds=30),
        ),
        evaluations=tuple(
            EvaluationEvidence(
                profile=profile,
                suite_version="synthetic-nexus-component",
                artifact_reference="fixture:NOT-LIVE-QUALITY",
                score=Decimal(1),
                conformance_passed=True,
                evaluated_at=now - timedelta(minutes=1),
                expires_at=now + timedelta(minutes=5),
            )
            for profile in ("reasoning", "routine", "verification")
        ),
        price=PriceCard(
            version="p1",
            as_of=now.date(),
            valid_from=now - timedelta(minutes=1),
            valid_until=now + timedelta(hours=1),
            source_reference="fixture:NOT-LIVE-PRICE",
            input_per_million=Decimal(1),
            output_per_million=Decimal(1),
            reasoning_semantics="included_in_output",
        ),
    )
    registry = ModelRegistry(
        company_id=COMPANY,
        revision="nexus-cycle-catalog-v1",
        pricebook_version="p1",
        models=(model,),
    )
    digest = canonical_sha256(registry)
    goal = GoalRevisionRef(
        company_id=COMPANY,
        goal_id=key("goal"),
        revision_id=key("goal-r1"),
        version="v1",
        sha256="a" * 64,
    )
    mandate = RevisionRef(
        company_id=COMPANY, revision_id=key("mandate"), version="v1", sha256="b" * 64
    )
    abi = (
        ("company.planning.v1", "reasoning", "model.request.v1", "model:nexus-planner"),
        ("engineering.change", "engineering.native.v1", "company.builder.run.v1", "nexus.builder"),
        ("engineering.verify", "verification.native.v1", "company.builder.run.v1", "nexus.builder"),
        ("internal.report", "routine", "company.report.write.v1", "nexus.report"),
        ("internal.report", "verification", "company.report.check.v1", "nexus.report-check"),
        (
            "internal.owner-notification",
            "notification.native.v1",
            "company.owner-notification.send.v1",
            "nexus.notice",
        ),
    )

    def binding(label: str, actor: UUID, workflow: str, profile: str) -> RunBinding:
        return RunBinding(
            company_id=COMPANY,
            workspace_id=key("workspace"),
            actor_id=actor,
            task_id=key(label + "-task"),
            trace_id=key(label + "-trace"),
            run_id=key(label + "-run"),
            workflow_name=workflow,
            workflow_version="v1",
            model_profile=profile,
            model_registry_version=registry.revision,
        )

    root = ProcedureRoot(
        company_id=COMPANY,
        procedure_id=key("procedure"),
        goal_id=goal.goal_id,
        binding=binding("root", key("owner"), "nexus.goal-cycle.v1", "reasoning"),
        allocation_usd=Decimal("1"),
        quota=AttemptQuota(model_requests=1, tool_attempts=5, rework_rounds=0, plan_revisions=1),
    )
    slots = []
    for index, (role, (workflow, profile, tool, resource)) in enumerate(
        zip(NEXUS_ROLES, abi, strict=True)
    ):
        bound = binding(
            role, key("owner") if index == 5 else key(role + "-actor"), workflow, profile
        )
        charter = CharterRevisionRef(
            company_id=COMPANY,
            department_id=key(role + "-department"),
            revision_id=key(role + "-charter"),
            version="v1",
            sha256="c" * 64,
        )
        quota = AttemptQuota(
            model_requests=int(index == 0),
            tool_attempts=int(index != 0),
            rework_rounds=0,
            plan_revisions=0,
        )
        child = ChildAllocation(
            company_id=COMPANY,
            binding=bound,
            charter=charter,
            allocation_usd=Decimal(".1"),
            quota=quota,
        )
        criteria = (
            NATIVE_CRITERIA
            if index in (1, 2)
            else REPORT_CHECK_CRITERIA
            if index in (3, 4)
            else ("nexus.bounded-role.v1",)
        )
        deps = (
            (key("engineering-task"),)
            if index == 3
            else (key("report-task"),)
            if index == 5
            else ()
        )
        item = WorkItem(
            company_id=COMPANY,
            task_id=bound.task_id,
            trace_id=bound.trace_id,
            goal_id=goal.goal_id,
            department=role,
            title="Nexus " + role,
            acceptance=criteria,
            budget_usd=child.allocation_usd,
            depends_on=deps,
        )
        slots.append(
            NexusCycleSlot(
                role=role,
                child=child,
                work=item,
                tool=ToolPermission(tool=tool, tool_version="v1", resource=resource),
            )
        )
    admission = NexusCycleAdmission(
        company_id=COMPANY,
        goal=goal,
        mandate=mandate,
        plan_id=key("plan"),
        registry_revision=registry.revision,
        registry_sha256=digest,
        procedure=root,
        slots=tuple(slots),
    )
    resources = tuple(
        NamedPlanResource(
            symbol=symbol, resource=ResourceRef(company_id=COMPANY, resource_id=key(symbol))
        )
        for symbol in dict.fromkeys(slot.tool.resource for slot in slots)
    )
    native = tuple(
        NativeExecutionProfile(
            company_id=COMPANY,
            execution_profile=cast(
                Literal["engineering.native.v1", "verification.native.v1"], name
            ),
            workflow_name=cast(Literal["engineering.change", "engineering.verify"], workflow),
            registry_revision=registry.revision,
            registry_sha256=digest,
            tools=(slots[index].tool,),
        )
        for index, name, workflow in (
            (1, "engineering.native.v1", "engineering.change"),
            (2, "verification.native.v1", "engineering.verify"),
        )
    )
    notification = NativeNotificationProfile(
        company_id=COMPANY,
        execution_profile="notification.native.v1",
        workflow_name="internal.owner-notification",
        registry_revision=registry.revision,
        registry_sha256=digest,
        target_symbol="nexus.notice",
        target_resource=resources[-1].resource,
    )
    catalog = PlanAdmissionCatalog(
        company_id=COMPANY,
        models=registry,
        admitted_profiles=frozenset({"reasoning", "routine", "verification"}),
        check_recipes=frozenset({"native-engineering-change-v1", REPORT_CHECK_RECIPE}),
        tools=tuple(dict.fromkeys(slot.tool for slot in slots)),
        resources=resources,
        native_profiles=native,
        notification_profiles=(notification,),
        nexus_cycle_admission=admission,
    )
    return admission, catalog


def base(admission: NexusCycleAdmission) -> PlanRevision:
    payload = admission.payload("planning")
    digest = canonical_sha256(payload)
    return PlanRevision(
        company_id=COMPANY,
        plan_id=admission.plan_id,
        plan_revision_id=uuid5(admission.plan_id, f"plan:1:{digest}"),
        revision=1,
        sha256=digest,
        payload=payload,
        proposed_by=admission.procedure.binding.actor_id,
        recorded_at=NOW,
    )


def origin(admission: NexusCycleAdmission) -> PlanningOriginRef:
    return PlanningOriginRef(
        company_id=COMPANY,
        goal=admission.goal,
        source_plan_id=admission.plan_id,
        source_plan_revision_id=base(admission).plan_revision_id,
        task_id=admission.slots[0].work.task_id,
        action_id=key("planning-action"),
        request_id=key("planning-request"),
        receipt_id=key("planning-receipt"),
        artifact_id=key("planning-artifact"),
        artifact_sha256="d" * 64,
        request_sha256="e" * 64,
        context_manifest_sha256="f" * 64,
        content_sha256="a" * 64,
        mapping_revision="nexus-mapping-v1",
        mapping_sha256="b" * 64,
    )

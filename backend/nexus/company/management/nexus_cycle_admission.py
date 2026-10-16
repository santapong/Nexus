"""Closed Nexus planning/native layout descriptions; no execution or model allowance."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from nexus.company.contracts.work import WorkItem, WorkPlan
from nexus.company.management.base import (
    ManagementContract,
    Name,
    RevisionRef,
    ValueContract,
    require_company,
)
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.check_contracts import REPORT_CHECK_CRITERIA, REPORT_CHECK_RECIPE
from nexus.company.management.goals import GoalRevisionRef
from nexus.company.management.native_execution_profiles import (
    NATIVE_CRITERIA,
    native_execution_profile,
)
from nexus.company.management.planning_origin_contracts import PlanningOriginRef
from nexus.company.management.plans import (
    ChildAllocation,
    PlanPayload,
    ProcedureRoot,
    VerificationIntent,
)
from nexus.company.notifications.native_profile_checks import native_notification_profile
from nexus.execution.runtime_contracts import AttemptQuota
from nexus.harness.standing_contracts import ToolPermission

if TYPE_CHECKING:
    from nexus.company.management.plan_catalog import PlanAdmissionCatalog

NexusRole = Literal[
    "planner", "engineering", "engineering_check", "report", "report_check", "sender"
]
NEXUS_ROLES: tuple[NexusRole, ...] = (
    "planner",
    "engineering",
    "engineering_check",
    "report",
    "report_check",
    "sender",
)
NexusStage = Literal["planning", "execution"]
_ROLE_ABI = (
    ("company.planning.v1", "reasoning", "model.request.v1"),
    ("engineering.change", "engineering.native.v1", "company.builder.run.v1"),
    ("engineering.verify", "verification.native.v1", "company.builder.run.v1"),
    ("internal.report", "routine", "company.report.write.v1"),
    ("internal.report", "verification", "company.report.check.v1"),
    ("internal.owner-notification", "notification.native.v1", "company.owner-notification.send.v1"),
)


def exact_quota(value: AttemptQuota) -> None:
    AttemptQuota.model_validate({name: getattr(value, name) for name in AttemptQuota.model_fields})


class NexusCycleSlot(ValueContract):
    role: NexusRole
    child: ChildAllocation
    work: WorkItem
    tool: ToolPermission

    @model_validator(mode="after")
    def exact_work(self) -> Self:
        require_company(self.child.company_id, self.child.binding, self.child.charter, self.work)
        exact_quota(self.child.quota)
        if (self.child.binding.task_id, self.child.binding.trace_id, self.child.allocation_usd) != (
            self.work.task_id,
            self.work.trace_id,
            self.work.budget_usd,
        ):
            raise ValueError("Nexus role work and allocation differ")
        return self


class NexusCycleAdmission(ManagementContract):
    """Trusted finite two-head configuration, not a registered or accepted occurrence."""

    goal: GoalRevisionRef
    mandate: RevisionRef
    plan_id: UUID
    registry_revision: Name
    registry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    procedure: ProcedureRoot
    slots: tuple[NexusCycleSlot, ...] = Field(min_length=6, max_length=6)

    @model_validator(mode="after")
    def closed_layout(self) -> Self:
        require_company(
            self.company_id,
            self.goal,
            self.mandate,
            self.procedure,
            *(slot.child for slot in self.slots),
            *(slot.work for slot in self.slots),
        )
        exact_quota(self.procedure.quota)
        if tuple(slot.role for slot in self.slots) != NEXUS_ROLES:
            raise ValueError("Nexus roles must be complete and canonically ordered")
        quota = self.procedure.quota
        if self.procedure.goal_id != self.goal.goal_id or (
            quota.model_requests < 1 or quota.tool_attempts < 5 or quota.plan_revisions < 1
        ):
            raise ValueError("Nexus root cannot cover its predeclared lifetime slices")
        root = self.procedure.binding
        if (
            root.model_profile != "reasoning"
            or root.model_registry_version != self.registry_revision
        ):
            raise ValueError("Nexus nonexecuting root profile differs")
        for name in ("task_id", "trace_id", "run_id"):
            values = (
                getattr(root, name),
                *(getattr(slot.child.binding, name) for slot in self.slots),
            )
            if len(set(values)) != 7:
                raise ValueError("Nexus family identities must be distinct")
        for index, slot in enumerate(self.slots):
            bound = slot.child.binding
            workflow, profile, tool = _ROLE_ABI[index]
            expected = AttemptQuota(
                model_requests=int(index == 0),
                tool_attempts=int(index != 0),
                rework_rounds=0,
                plan_revisions=0,
            )
            dependencies = (
                (self.slots[1].work.task_id,)
                if index == 3
                else ((self.slots[3].work.task_id,) if index == 5 else ())
            )
            if (
                (
                    bound.workflow_name,
                    bound.workflow_version,
                    bound.model_profile,
                    bound.model_registry_version,
                    slot.tool.tool,
                    slot.tool.tool_version,
                )
                != (workflow, "v1", profile, self.registry_revision, tool, "v1")
                or slot.child.quota != expected
                or slot.work.depends_on != dependencies
            ):
                raise ValueError("Nexus role ABI/quota/dependency differs")
            if bound.workspace_id != root.workspace_id or slot.work.goal_id != self.goal.goal_id:
                raise ValueError("Nexus role escapes its workspace or goal")
            if index in (1, 2) and slot.work.acceptance != NATIVE_CRITERIA:
                raise ValueError("Nexus engineering requires the seven native criteria")
            if index in (3, 4) and slot.work.acceptance != REPORT_CHECK_CRITERIA:
                raise ValueError("Nexus report requires the six native criteria")
        if (
            self.slots[1].child.binding.actor_id == self.slots[2].child.binding.actor_id
            or (self.slots[3].child.binding.actor_id == self.slots[4].child.binding.actor_id)
            or self.slots[5].child.binding.actor_id != root.actor_id
        ):
            raise ValueError("Nexus verifier independence or owner sender differs")
        if sum(slot.child.allocation_usd for slot in self.slots) > self.procedure.allocation_usd:
            raise ValueError("Nexus role slices exceed the permanent root")
        return self

    def payload(self, stage: NexusStage, *, origin: PlanningOriginRef | None = None) -> PlanPayload:
        """Construct descriptions; owner/native validation and registration remain mandatory."""
        if stage not in {"planning", "execution"}:
            raise ValueError("Nexus stage is unsupported")
        slots = self.slots[:1] if stage == "planning" else self.slots
        edges = (
            ()
            if stage == "planning"
            else (
                VerificationIntent(
                    company_id=self.company_id,
                    author_task_id=self.slots[1].work.task_id,
                    verifier_task_id=self.slots[2].work.task_id,
                    check_recipe="native-engineering-change-v1",
                ),
                VerificationIntent(
                    company_id=self.company_id,
                    author_task_id=self.slots[3].work.task_id,
                    verifier_task_id=self.slots[4].work.task_id,
                    check_recipe=REPORT_CHECK_RECIPE,
                ),
            )
        )
        return PlanPayload(
            company_id=self.company_id,
            goal=self.goal,
            mandate=self.mandate,
            procedure=self.procedure,
            charters=tuple(dict.fromkeys(slot.child.charter for slot in slots)),
            children=tuple(slot.child for slot in slots),
            verification=edges,
            planning_origin=origin,
            plan=WorkPlan(
                company_id=self.company_id,
                plan_id=self.plan_id,
                goal_id=self.goal.goal_id,
                revision=1 if stage == "planning" else 2,
                items=tuple(slot.work for slot in slots),
            ),
        )


def validate_nexus_catalog(
    admission: NexusCycleAdmission | None, catalog: PlanAdmissionCatalog
) -> NexusCycleAdmission | None:
    if admission is None:
        return None
    exact_quota(admission.procedure.quota)
    for slot in admission.slots:
        exact_quota(slot.child.quota)
    checked = NexusCycleAdmission.model_validate(admission.model_dump(warnings=False))
    if (
        catalog.nexus_cycle_admission != checked
        or catalog.cycle_admission is not None
        or (
            checked.company_id,
            checked.registry_revision,
            checked.registry_sha256,
        )
        != (catalog.company_id, catalog.models.revision, canonical_sha256(catalog.models))
    ):
        raise ValueError("Nexus catalog is crossed or also configures StockFlow")
    tools = {tool.tool: tool for tool in catalog.tools}
    resources = {row.symbol for row in catalog.resources}
    for slot in checked.slots:
        if tools.get(slot.tool.tool) != slot.tool or slot.tool.resource not in resources:
            raise ValueError("Nexus role lacks its exact catalog tool/resource")
        if slot.role not in {"engineering", "engineering_check", "sender"} and (
            slot.child.binding.model_profile not in catalog.admitted_profiles
        ):
            raise ValueError("Nexus ordinary profile is not admitted")
    for slot in checked.slots[1:3]:
        native = native_execution_profile(catalog, slot.child)
        if native is None or native.tools != (slot.tool,):
            raise ValueError("Nexus engineering profile differs")
    sender = native_notification_profile(catalog, checked.slots[5].child)
    if sender is None or sender.target_symbol != checked.slots[5].tool.resource:
        raise ValueError("Nexus sender profile differs")
    if not {"native-engineering-change-v1", REPORT_CHECK_RECIPE} <= catalog.check_recipes:
        raise ValueError("Nexus verifier recipes are unavailable")
    return checked


def select_nexus_plan(
    admission: NexusCycleAdmission | None, catalog: PlanAdmissionCatalog, payload: PlanPayload
) -> NexusStage | None:
    checked = validate_nexus_catalog(admission, catalog)
    if checked is None:
        return None
    stage: NexusStage = "planning" if payload.plan.revision == 1 else "execution"
    if (
        payload.plan.revision not in (1, 2)
        or payload.strategy_selection is not None
        or ((payload.planning_origin is None) != (stage == "planning"))
    ):
        raise ValueError("Nexus needs its exact bootstrap or protected planning transition")
    original = PlanPayload.model_validate(payload.model_dump(warnings=False))
    expected = checked.payload(stage, origin=original.planning_origin)
    # New role titles are model-authored metadata, never their authority/criteria/edges.
    normalized = original.model_copy(
        update={
            "plan": original.plan.model_copy(
                update={
                    "items": tuple(
                        item.model_copy(update={"title": slot.work.title})
                        for item, slot in zip(
                            original.plan.items,
                            checked.slots[:1] if stage == "planning" else checked.slots,
                            strict=True,
                        )
                    )
                }
            )
        }
    )
    if normalized != expected or original.plan.items[0] != checked.slots[0].work:
        raise ValueError("Nexus payload differs from its complete permanent layout")
    return stage

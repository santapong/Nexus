"""Explicit server slots turn protected planning content into an owner-reviewable proposal."""

from __future__ import annotations

from uuid import UUID

from pydantic import Field, model_validator

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.contracts.work import WorkItem, WorkPlan
from nexus.company.management.base import Name, Symbol, ValueContract
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.goals import GoalRevisionRef
from nexus.company.management.lifecycle import PlanRevision
from nexus.company.management.nexus_coding_admission import NexusCodingAdmission, NexusCodingSlot
from nexus.company.management.nexus_coding_catalog import NexusAdmission
from nexus.company.management.nexus_cycle_admission import NexusCycleAdmission, NexusCycleSlot
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.planning_content import PlanningContent, TaskKey
from nexus.company.management.planning_native_facts import read_end
from nexus.company.management.planning_origin_contracts import PlanningOriginRef
from nexus.company.management.planning_source_reader import PlanningSourceReader
from nexus.company.management.plans import ChildAllocation, PlanPayload
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity


class PlanningTaskSlot(ValueContract):
    key: TaskKey
    allocation: ChildAllocation
    department: Name
    required_dependencies: tuple[UUID, ...] = Field(default=(), max_length=100)


class PlanningProposalTemplate(ValueContract):
    """Immutable server authority; never inferred from model words or HTTP content."""

    base_plan: PlanRevision
    revision: Symbol
    slots: tuple[PlanningTaskSlot, ...] = Field(min_length=1, max_length=16)

    nexus_admission: NexusCycleAdmission | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    nexus_coding_admission: NexusCodingAdmission | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @property
    def configured_admission(self) -> NexusAdmission | None:
        """One immutable mapper profile, never a model-selected role policy."""
        if self.nexus_admission is not None and self.nexus_coding_admission is not None:
            raise ValueError("Planning mapper admission profiles are mutually exclusive")
        return (
            self.nexus_coding_admission
            if self.nexus_coding_admission is not None
            else self.nexus_admission
        )

    @model_validator(mode="after")
    def fixed_model_slots(self) -> PlanningProposalTemplate:
        base = self.base_plan.payload
        if (
            len(base.children) != 1
            or len(base.plan.items) != 1
            or base.verification
            or base.planning_origin is not None
            or base.strategy_selection is not None
        ):
            raise ValueError("Planning bridge requires its exact one-child bootstrap plan")
        keys = {slot.key for slot in self.slots}
        tasks = {slot.allocation.binding.task_id for slot in self.slots}
        original = {item.task_id for item in base.plan.items}
        if len(keys) != len(self.slots) or len(tasks) != len(self.slots) or tasks & original:
            raise ValueError("Server planning slots require unique keys and new fixed identities")
        profile = self.configured_admission
        if profile is not None:
            admission: NexusAdmission = (
                NexusCodingAdmission.model_validate(profile.model_dump(warnings=False))
                if isinstance(profile, NexusCodingAdmission)
                else NexusCycleAdmission.model_validate(profile.model_dump(warnings=False))
            )
            expected_slots: tuple[NexusCodingSlot | NexusCycleSlot, ...] = admission.slots[1:]
            if (
                base != admission.payload("planning")
                or tuple(slot.key for slot in self.slots)
                != (tuple(slot.role for slot in admission.slots[1:]))
                or any(
                    (slot.allocation, slot.department, slot.required_dependencies)
                    != (expected.child, expected.work.department, expected.work.depends_on)
                    for slot, expected in zip(self.slots, expected_slots, strict=True)
                )
            ):
                raise ValueError("Nexus mapping differs from its exact configured roles")
            return self
        for slot in self.slots:
            child = slot.allocation
            if (
                child.company_id != base.company_id
                or child.binding.workspace_id != base.procedure.binding.workspace_id
                or child.binding.model_profile
                not in {"routine", "reasoning", "engineering", "verification"}
                or child.quota.model_requests < 1
                or any(
                    getattr(child.quota, field)
                    for field in ("tool_attempts", "rework_rounds", "plan_revisions")
                )
                or len(set(slot.required_dependencies)) != len(slot.required_dependencies)
                or not set(slot.required_dependencies) <= tasks | original
            ):
                raise ValueError(
                    "Planning slots are exact model-only declarations with known dependencies"
                )
        charters = {row.revision_id: row for row in base.charters}
        for slot in self.slots:
            existing = charters.get(slot.allocation.charter.revision_id)
            if existing is not None and existing != slot.allocation.charter:
                raise ValueError("A server slot cannot rebind an existing charter revision")
            charters[slot.allocation.charter.revision_id] = slot.allocation.charter
        return self


def map_content(
    content: PlanningContent, origin: PlanningOriginRef, template: PlanningProposalTemplate
) -> PlanPayload:
    """Preserve the permanent root/base work; model dependencies only add ordering."""
    content = PlanningContent.model_validate_json(content.model_dump_json())
    base = template.base_plan.payload
    if (
        origin.company_id != base.company_id
        or origin.goal != base.goal
        or (origin.source_plan_id, origin.source_plan_revision_id)
        != (template.base_plan.plan_id, template.base_plan.plan_revision_id)
        or origin.content_sha256 != canonical_sha256(content)
        or (origin.mapping_revision, origin.mapping_sha256)
        != (template.revision, canonical_sha256(template))
    ):
        raise ValueError("Planning origin differs from content or fixed server mapping")
    slots = {slot.key: slot for slot in template.slots}
    if {task.key for task in content.tasks} != slots.keys():
        raise ValueError("Planning task keys do not match exact server slots")
    if template.configured_admission is not None:
        admission = template.configured_admission
        keys = {slot.work.task_id: slot.role for slot in admission.slots[1:]}
        content_by_key = {task.key: task for task in content.tasks}
        for slot in admission.slots[1:]:
            if not set(content_by_key[slot.role].depends_on) <= {
                keys[task] for task in slot.work.depends_on
            }:
                raise ValueError("Model ordering cannot change Nexus acceptance/trigger gates")
        expected = admission.payload("execution", origin=origin)
        return expected.model_copy(
            update={
                "plan": expected.plan.model_copy(
                    update={
                        "items": (
                            base.plan.items[0],
                            *(
                                slot.work.model_copy(
                                    update={"title": content_by_key[slot.role].title}
                                )
                                for slot in admission.slots[1:]
                            ),
                        )
                    }
                )
            }
        )
    items = tuple(
        WorkItem(
            company_id=base.company_id,
            goal_id=base.goal.goal_id,
            task_id=slots[task.key].allocation.binding.task_id,
            trace_id=slots[task.key].allocation.binding.trace_id,
            department=slots[task.key].department,
            title=task.title,
            acceptance=task.acceptance,
            depends_on=tuple(
                sorted(
                    set(slots[task.key].required_dependencies)
                    | {slots[key].allocation.binding.task_id for key in task.depends_on}
                )
            ),
            budget_usd=slots[task.key].allocation.allocation_usd,
        )
        for task in content.tasks
    )
    charters = {row.revision_id: row for row in base.charters}
    charters.update(
        {slot.allocation.charter.revision_id: slot.allocation.charter for slot in template.slots}
    )
    return PlanPayload(
        company_id=base.company_id,
        goal=base.goal,
        mandate=base.mandate,
        procedure=base.procedure,
        children=(*base.children, *(slot.allocation for slot in template.slots)),
        charters=tuple(charters.values()),
        verification=base.verification,
        planning_origin=origin,
        coding_admission_sha256=base.coding_admission_sha256,
        plan=WorkPlan(
            company_id=base.company_id,
            plan_id=base.plan.plan_id,
            goal_id=base.goal.goal_id,
            revision=template.base_plan.revision + 1,
            items=(*base.plan.items, *items),
        ),
    )


class PlanningProposalBridge:
    def __init__(self, plans: ManagementPlanStore, reader: PlanningSourceReader) -> None:
        if (
            type(reader) is not PlanningSourceReader
            or plans.planning_reader is not reader
            or plans.factory is not reader.factory
        ):
            raise ValueError("Planning proposal requires the actual configured PlanStore reader")
        self.plans, self.reader = plans, reader

    async def propose(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        action_id: UUID,
        *,
        expected_goal: GoalRevisionRef,
        expected_current_revision_id: UUID,
        end_us: int,
        credential: AuthenticatedWorkerIdentity | None = None,
    ) -> PlanRevision:
        end_us = read_end(end_us)
        source = await self.reader.load(
            scope,
            identity,
            action_id,
            expected_goal=expected_goal,
            expected_current_revision_id=expected_current_revision_id,
            end_us=end_us,
        )
        payload = map_content(source.content, source.origin, self.reader.template)
        return await self.plans.propose(
            scope,
            identity,
            payload,
            expected_current_revision_id=expected_current_revision_id,
            end_us=end_us,
            credential=credential,
        )

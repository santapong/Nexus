"""Closed full-company coding descriptions, never current registration or effect authority."""

from __future__ import annotations

from typing import Literal, Self
from uuid import UUID, uuid5

from pydantic import Field, model_validator

from nexus.company.contracts.work import WorkItem, WorkPlan
from nexus.company.management.base import (
    SHA256,
    ManagementContract,
    Name,
    RevisionRef,
    ValueContract,
    require_company,
)
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.check_contracts import REPORT_CHECK_CRITERIA, REPORT_CHECK_RECIPE
from nexus.company.management.goals import GoalRevisionRef
from nexus.company.management.native_execution_profiles import NATIVE_CRITERIA
from nexus.company.management.planning_origin_contracts import PlanningOriginRef
from nexus.company.management.plans import (
    ChildAllocation,
    PlanPayload,
    ProcedureRoot,
    VerificationIntent,
)
from nexus.execution.runtime_contracts import AttemptQuota
from nexus.harness.standing_contracts import ToolPermission

NexusCodingRole = Literal[
    "planner",
    "coder",
    "strategy",
    "presentation",
    "support",
    "engineering",
    "engineering_check",
    "report",
    "report_check",
    "sender",
]
NEXUS_CODING_ROLES: tuple[NexusCodingRole, ...] = (
    "planner",
    "coder",
    "strategy",
    "presentation",
    "support",
    "engineering",
    "engineering_check",
    "report",
    "report_check",
    "sender",
)
CodingStage = Literal["planning", "execution"]
_ABI = (
    ("company.planning.v1", "reasoning", "model.request.v1"),
    ("company.coding.v1", "engineering", "model.request.v1"),
    ("company.strategy.v1", "reasoning", "model.request.v1"),
    ("company.presentation.v1", "routine", "model.request.v1"),
    ("company.support.v1", "routine", "model.request.v1"),
    ("engineering.change", "engineering.native.v1", "company.builder.run.v1"),
    ("engineering.verify", "verification.native.v1", "company.builder.run.v1"),
    ("internal.report", "routine", "company.report.write.v1"),
    ("internal.report", "verification", "company.report.check.v1"),
    ("internal.owner-notification", "notification.native.v1", "company.owner-notification.send.v1"),
)


def _quota(value: AttemptQuota) -> None:
    AttemptQuota.model_validate({name: getattr(value, name) for name in AttemptQuota.model_fields})


class NexusCodingSlot(ValueContract):
    """One immutable described role slice; no model or native permission is produced."""

    role: NexusCodingRole
    child: ChildAllocation
    work: WorkItem
    tool: ToolPermission

    @model_validator(mode="after")
    def exact_work(self) -> Self:
        """Require the original raw quota and exact same-company work/child declarations."""
        _quota(self.child.quota)
        require_company(self.child.company_id, self.child.binding, self.child.charter, self.work)
        if (self.child.binding.task_id, self.child.binding.trace_id, self.child.allocation_usd) != (
            self.work.task_id,
            self.work.trace_id,
            self.work.budget_usd,
        ):
            raise ValueError("Coding role work and allocation differ")
        return self


def _slot(value: NexusCodingAdmission, index: int, slot: NexusCodingSlot) -> None:
    binding, root = slot.child.binding, value.procedure.binding
    workflow, profile, tool = _ABI[index]
    expected = AttemptQuota(
        model_requests=int(index < 5),
        tool_attempts=int(index >= 5),
        rework_rounds=0,
        plan_revisions=0,
    )
    dependencies = (
        (value.slots[5].work.task_id,)
        if index == 7
        else (value.slots[7].work.task_id,)
        if index == 9
        else ()
    )
    if (
        (
            binding.workflow_name,
            binding.workflow_version,
            binding.model_profile,
            binding.model_registry_version,
            slot.tool.tool,
            slot.tool.tool_version,
        )
        != (workflow, "v1", profile, value.registry_revision, tool, "v1")
        or slot.child.quota != expected
        or slot.work.depends_on != dependencies
        or binding.workspace_id != root.workspace_id
        or slot.work.goal_id != value.goal.goal_id
        or len(slot.work.acceptance) > 32
        or len(set(slot.work.acceptance)) != len(slot.work.acceptance)
        or (
            index < 5
            and (not slot.tool.resource.startswith("model:") or not slot.tool.resource[6:])
        )
        or (index in (5, 6) and slot.work.acceptance != NATIVE_CRITERIA)
        or (index in (7, 8) and slot.work.acceptance != REPORT_CHECK_CRITERIA)
    ):
        raise ValueError("Coding role ABI/quota/dependency/criteria or scope differs")


def _partition(value: NexusCodingAdmission) -> None:
    root, quota = value.procedure.binding, value.procedure.quota
    if (
        value.slots[1].child.binding.actor_id == root.actor_id
        or value.slots[6].child.binding.actor_id
        in {
            value.slots[1].child.binding.actor_id,
            value.slots[5].child.binding.actor_id,
        }
        or value.slots[7].child.binding.actor_id == value.slots[8].child.binding.actor_id
        or value.slots[9].child.binding.actor_id != root.actor_id
        or sum(slot.child.allocation_usd for slot in value.slots) > value.procedure.allocation_usd
        or any(
            sum(getattr(slot.child.quota, name) for slot in value.slots) > getattr(quota, name)
            for name in AttemptQuota.model_fields
        )
    ):
        raise ValueError("Coding verifier/actor or permanent USD/quota partition differs")


class NexusCodingAdmission(ManagementContract):
    """A new ten-role family, not a reinterpretation of an existing consumed root.

    Accepted dependencies remain only report→E and sender→report. A model candidate
    is not Management-accepted work: manufacturing C/S/P/U accepted dependencies
    would deadlock native work. Before activation, concrete effect/source gates
    must require the actual C receipt and protected authorized patch and current
    Strategy/presentation/support input provenance. This description supplies none.
    Actual admission must verify a new eligible Goal/procedure under the native
    lock; a pure template cannot prove that a database root is unconsumed.
    Extra charged work needs a separately predeclared supported configuration;
    unused root headroom cannot enlarge these immutable one-shot child slices.
    """

    kind: Literal["nexus.coding-cycle.v1"]
    goal: GoalRevisionRef
    mandate: RevisionRef
    plan_id: UUID
    registry_revision: Name
    registry_sha256: SHA256
    procedure: ProcedureRoot
    slots: tuple[NexusCodingSlot, ...] = Field(min_length=10, max_length=10)

    @model_validator(mode="after")
    def closed_layout(self) -> Self:
        """Require the whole declared family before any r1/r2 description can be built."""
        require_company(
            self.company_id,
            self.goal,
            self.mandate,
            self.procedure,
            *(slot.child for slot in self.slots),
            *(slot.work for slot in self.slots),
        )
        _quota(self.procedure.quota)
        root, quota = self.procedure.binding, self.procedure.quota
        if (
            tuple(slot.role for slot in self.slots) != NEXUS_CODING_ROLES
            or self.procedure.goal_id != self.goal.goal_id
            or (
                root.workflow_name,
                root.workflow_version,
                root.model_profile,
                root.model_registry_version,
            )
            != ("nexus.coding-cycle.v1", "v1", "reasoning", self.registry_revision)
            or quota.model_requests < 5
            or quota.tool_attempts < 5
            or quota.plan_revisions < 1
        ):
            raise ValueError("Coding needs the complete fixed family and permanent root allowance")
        for name in ("task_id", "trace_id", "run_id"):
            if (
                len(
                    {
                        getattr(root, name),
                        *(getattr(slot.child.binding, name) for slot in self.slots),
                    }
                )
                != 11
            ):
                raise ValueError("Coding family identities must be distinct")
        for index, slot in enumerate(self.slots):
            _quota(slot.child.quota)
            NexusCodingSlot.model_validate(slot.model_dump())
            _slot(self, index, slot)
        _partition(self)
        return self

    def payload(
        self, stage: CodingStage, *, origin: PlanningOriginRef | None = None
    ) -> PlanPayload:
        """Build descriptions of r1 or same-root r2; decoding never approves or registers them."""
        value = _checked(self)
        if stage not in {"planning", "execution"} or ((origin is None) != (stage == "planning")):
            raise ValueError("Coding needs its exact bootstrap or planning-origin transition")
        if origin is not None:
            _origin(value, origin)
        slots = value.slots[:1] if stage == "planning" else value.slots
        return PlanPayload(
            company_id=value.company_id,
            goal=value.goal,
            mandate=value.mandate,
            procedure=value.procedure,
            charters=tuple(dict.fromkeys(slot.child.charter for slot in slots)),
            children=tuple(slot.child for slot in slots),
            planning_origin=origin,
            coding_admission_sha256=canonical_sha256(value),
            verification=()
            if stage == "planning"
            else tuple(
                VerificationIntent(
                    company_id=value.company_id,
                    author_task_id=value.slots[author].work.task_id,
                    verifier_task_id=value.slots[verifier].work.task_id,
                    check_recipe=recipe,
                )
                for author, verifier, recipe in (
                    (5, 6, "native-engineering-change-v1"),
                    (7, 8, REPORT_CHECK_RECIPE),
                )
            ),
            plan=WorkPlan(
                company_id=value.company_id,
                plan_id=value.plan_id,
                goal_id=value.goal.goal_id,
                revision=1 if stage == "planning" else 2,
                items=tuple(slot.work for slot in slots),
            ),
        )


def _checked(value: NexusCodingAdmission) -> NexusCodingAdmission:
    _quota(value.procedure.quota)
    for slot in value.slots:
        _quota(slot.child.quota)
    return NexusCodingAdmission.model_validate(value.model_dump())


def _origin(value: NexusCodingAdmission, origin: PlanningOriginRef) -> None:
    initial = value.payload("planning")
    expected = uuid5(value.plan_id, "plan:1:" + canonical_sha256(initial))
    if (
        origin.company_id,
        origin.goal,
        origin.source_plan_id,
        origin.source_plan_revision_id,
        origin.task_id,
    ) != (
        value.company_id,
        value.goal,
        value.plan_id,
        expected,
        value.slots[0].work.task_id,
    ):
        raise ValueError("Coding origin escapes its exact bootstrap/goal/planner description")


def select_nexus_coding_plan(value: NexusCodingAdmission, payload: PlanPayload) -> CodingStage:
    """Compare only the immutable template; native receipt/current authority remain unproven."""
    value = _checked(value)
    payload = PlanPayload.model_validate(payload.model_dump())
    if payload.plan.revision not in (1, 2) or payload.strategy_selection is not None:
        raise ValueError("Coding accepts only its two exact configured heads")
    stage: CodingStage = "planning" if payload.plan.revision == 1 else "execution"
    expected = value.payload(stage, origin=payload.planning_origin)
    normalized = payload.model_copy(
        update={
            "plan": payload.plan.model_copy(
                update={
                    "items": tuple(
                        row.model_copy(update={"title": slot.work.title})
                        for row, slot in zip(
                            payload.plan.items,
                            value.slots[:1] if stage == "planning" else value.slots,
                            strict=True,
                        )
                    )
                }
            )
        }
    )
    if normalized != expected or payload.plan.items[0] != expected.plan.items[0]:
        raise ValueError("Coding plan differs from its complete permanent template")
    return stage

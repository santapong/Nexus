"""Actual stored bootstrap/approval and current-owner/source reads for a configured Nexus goal."""

from dataclasses import dataclass, field
from datetime import timedelta
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope
from nexus.company.brain.access_support import require_resources
from nexus.company.brain.native_fact_inputs import source_references
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.control_support import current_charter, current_mandate, db_clock
from nexus.company.management.goal_store import GoalStore
from nexus.company.management.lifecycle import PlanRevision
from nexus.company.management.nexus_coding_admission import NexusCodingAdmission
from nexus.company.management.owner_view_sources import owner_brain_scope, source_disclosure
from nexus.company.management.plan_models import (
    ManagementOwnerDecision,
    ManagementPlanHead,
    ManagementPlanRevision,
    ManagementProcedure,
)
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.planning_native_facts import clock_us, require_time
from nexus.company.management.planning_proposal_bridge import (
    PlanningProposalTemplate,
    PlanningTaskSlot,
)
from nexus.company.management.planning_source_reader import PlanningSourceReader
from nexus.company.management.plans import RunBinding
from nexus.company.management.revision_store import plan_record
from nexus.company.management.transactions import ManagementDeniedError
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.planning_application_config import PlanningApplicationConfig
from nexus.execution.planning_services import PlanningServices
from nexus.execution.runtime_contracts import AttemptQuota
from nexus.harness.journal_models import CompanyControl


async def owner_locked(
    services: PlanningServices,
    config: PlanningApplicationConfig,
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    owner: AuthenticatedWorkerIdentity,
    end_us: int,
) -> int:
    """Current genuine owner, configured native goal/governance and complete static READ."""
    require_time(end_us)
    owner.require_time(await db_clock(session))
    admission = config.admission
    if (
        not session.in_transaction()
        or (
            scope.company_id,
            scope.principal_id,
            owner.identity.principal_id,
            owner.identity.workspace_id,
        )
        != (
            admission.company_id,
            control.owner_id,
            control.owner_id,
            admission.procedure.binding.workspace_id,
        )
        or control.owner_id != admission.procedure.binding.actor_id
        or (control.policy_version, control.price_version)
        != (config.policy_version, config.catalog.models.pricebook_version)
    ):
        raise ManagementDeniedError("Planning needs its genuine current configured owner/policy")
    goal = await GoalStore._current(session, scope, config.goal)
    mandate = await current_mandate(session, scope, admission.mandate)
    if goal.definition.owner_id != control.owner_id or goal.definition.mandate != admission.mandate:
        raise ManagementDeniedError("Planning current native goal/mandate differs")
    for slot in admission.slots:
        charter = await current_charter(session, scope, slot.child.charter)
        if charter.mandate != admission.mandate:
            raise ManagementDeniedError("Planning configured charter mandate differs")
    if mandate.mandate.goals and config.goal.goal_id not in mandate.mandate.goals:
        raise ManagementDeniedError("Planning goal is outside its current mandate")
    brain = owner_brain_scope(scope, owner.identity)
    ids = tuple(sorted({row.resource.resource_id for row in config.catalog.resources}))
    refs = await source_references(session, brain, ids)
    disclosure = await source_disclosure(
        session,
        control,
        scope,
        owner.identity,
        services.prepared.sources,
        refs,
    )
    if disclosure is None:
        raise ManagementDeniedError("Planning owner source READ is unavailable")
    grants = await require_resources(session, brain, ids, await db_clock(session))
    windows = [owner.expires_at, *(row.expires_at for row in grants if row.expires_at is not None)]
    if disclosure.valid_until is not None:
        windows.append(disclosure.valid_until)
    before = clock_us()
    now = await db_clock(session)
    end_us = min(
        (end_us, *(before + (value - now) // timedelta(microseconds=1) for value in windows))
    )
    owner.require_time(now)
    require_time(end_us)
    return end_us


async def stored_plans(
    session: AsyncSession,
    config: PlanningApplicationConfig,
) -> tuple[PlanRevision | None, PlanRevision | None, ManagementPlanHead | None]:
    """At most the two exact configured revisions; returned models come only from native rows."""
    rows = tuple(
        (
            await session.scalars(
                select(ManagementPlanRevision)
                .where(
                    ManagementPlanRevision.company_id == config.admission.company_id,
                    ManagementPlanRevision.plan_id == config.admission.plan_id,
                )
                .order_by(ManagementPlanRevision.revision)
                .limit(3)
            )
        ).all()
    )
    if len(rows) > 2:
        raise ManagementDeniedError("Configured planning has unexpected native revisions")
    values = tuple(plan_record(row) for row in rows)
    base = next((row for row in values if row.revision == 1), None)
    target = next((row for row in values if row.revision == 2), None)
    for value in values:
        if value.plan_revision_id != uuid5(value.plan_id, f"plan:{value.revision}:{value.sha256}"):
            raise ManagementDeniedError("Planning stored revision identity differs")
    if base is not None and base.payload != config.admission.payload("planning"):
        raise ManagementDeniedError("Stored planning bootstrap differs from exact admission")
    if target is not None and (
        base is None
        or target.payload.planning_origin is None
        or target.payload.planning_origin.source_plan_revision_id != base.plan_revision_id
        or target.payload.goal != config.goal
    ):
        raise ManagementDeniedError("Stored planning target lacks its exact bootstrap origin")
    head = await session.get(
        ManagementPlanHead, (config.admission.company_id, config.admission.plan_id)
    )
    if head is not None and (
        head.goal_id != config.goal.goal_id
        or head.current_revision_id not in {row.plan_revision_id for row in values}
    ):
        raise ManagementDeniedError("Configured planning current head is unavailable")
    return base, target, head


@dataclass(frozen=True, slots=True)
class PlanningBundle:
    """One actual approved r1 creates one immutable reader/store pair for this operation."""

    base: PlanRevision
    target: PlanRevision | None
    head_revision_id: UUID
    reader: PlanningSourceReader
    plans: ManagementPlanStore
    _original: tuple[object, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_original", self._pins())

    def _pins(self) -> tuple[object, ...]:
        return (
            self.reader,
            self.plans,
            self.plans.factory,
            self.plans.planning_reader,
            self.reader.template,
            canonical_sha256(self.reader.template),
            canonical_sha256(self.plans.catalog),
        )

    def require_composition(self) -> None:
        value = self._pins()
        if (
            any(a is not b for a, b in zip(value[:5], self._original[:5], strict=True))
            or value[5:] != self._original[5:]
            or self.plans.planning_reader is not self.reader
        ):
            raise ManagementDeniedError("Original planning reader-bound store changed")
        self.reader._composition()


async def approved_bundle(
    session: AsyncSession,
    control: CompanyControl,
    config: PlanningApplicationConfig,
    services: PlanningServices,
) -> PlanningBundle:
    """Load native r1 approval/root/current binding, never a posted or remembered base DTO."""
    base, target, head = await stored_plans(session, config)
    if base is None or head is None or head.state != "approved":
        raise ManagementDeniedError("Planning requires its actual approved bootstrap")
    decisions = tuple(
        (
            await session.scalars(
                select(ManagementOwnerDecision)
                .where(
                    ManagementOwnerDecision.company_id == control.company_id,
                    ManagementOwnerDecision.plan_revision_id == base.plan_revision_id,
                    ManagementOwnerDecision.kind == "approve",
                    ManagementOwnerDecision.owner_id == control.owner_id,
                )
                .limit(2)
            )
        ).all()
    )
    if len(decisions) != 1 or decisions[0].payload_sha256 != base.sha256:
        raise ManagementDeniedError("Stored bootstrap lacks exact genuine owner approval")
    current = base if head.current_revision_id == base.plan_revision_id else target
    decision = await session.get(ManagementOwnerDecision, (control.company_id, head.decision_id))
    if (
        current is None
        or decision is None
        or (
            decision.kind,
            decision.owner_id,
            decision.plan_revision_id,
            decision.payload_sha256,
        )
        != ("approve", control.owner_id, current.plan_revision_id, current.sha256)
    ):
        raise ManagementDeniedError("Current planning head lacks exact native approval")
    admission, slot = config.admission, config.admission.slots[0]
    native = await ManagementPlanStore.current_binding(
        session, control.company_id, slot.work.task_id
    )
    if (
        native is None
        or native.child != slot.child
        or native.work != slot.work
        or native.plan.plan_id != admission.plan_id
        or native.plan.plan_revision_id != head.current_revision_id
        or native.procedure_id != admission.procedure.procedure_id
    ):
        raise ManagementDeniedError(
            "Current planning child differs from permanent native registration"
        )
    procedure = await session.get(
        ManagementProcedure, (control.company_id, admission.procedure.procedure_id)
    )
    root = admission.procedure
    if procedure is None or (
        procedure.goal_id,
        procedure.parent_task_id,
        procedure.parent_run_id,
        procedure.allocation_usd,
        AttemptQuota.model_validate_json(procedure.quota_json),
        RunBinding.model_validate_json(procedure.binding_json),
    ) != (
        config.goal.goal_id,
        root.binding.task_id,
        root.binding.run_id,
        root.allocation_usd,
        root.quota,
        root.binding,
    ):
        raise ManagementDeniedError("Planning permanent root/slices cannot be replaced")
    template = PlanningProposalTemplate(
        base_plan=base,
        revision=config.mapping_revision,
        nexus_admission=admission if not isinstance(admission, NexusCodingAdmission) else None,
        nexus_coding_admission=admission if isinstance(admission, NexusCodingAdmission) else None,
        slots=tuple(
            PlanningTaskSlot(
                key=slot.role,
                allocation=slot.child,
                department=slot.work.department,
                required_dependencies=slot.work.depends_on,
            )
            for slot in admission.slots[1:]
        ),
    )
    reader = PlanningSourceReader(
        services.factory,
        services.evidence,
        services.contexts._retriever,
        services.prepared.sources,
        template,
    )
    plans = ManagementPlanStore(
        services.factory,
        services.management.catalog,
        source_freshness=services.management.freshness,
        planning_reader=reader,
    )
    return PlanningBundle(base, target, head.current_revision_id, reader, plans)

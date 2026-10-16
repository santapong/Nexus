"""Fresh native plan admission from configured catalogs; never an effect permission."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.access_models import BrainResource, BrainResourceAccess
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.source_models import (
    BrainArtifactRevision,
    BrainSource,
    BrainSourceHead,
    BrainSourceRevision,
)
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.work import WorkItem
from nexus.company.directory_models import DirectoryMembership
from nexus.company.management.base import (
    SHA256,
    ManagementContract,
)
from nexus.company.management.control_support import (
    current_charter,
    current_mandate,
    db_clock,
    require_member,
)
from nexus.company.management.cycle_catalog_checks import validate_cycle_catalog
from nexus.company.management.goal_store import GoalStore
from nexus.company.management.governance import CharterRevision
from nexus.company.management.governance_models import ManagementGoalHead
from nexus.company.management.lifecycle import PlanRevisionRef
from nexus.company.management.model_profile_checks import validate_model_profile
from nexus.company.management.native_execution_profiles import (
    require_native_action,
    require_native_plan,
)
from nexus.company.management.plan_catalog import NamedPlanResource as NamedPlanResource
from nexus.company.management.plan_catalog import PlanAdmissionCatalog as PlanAdmissionCatalog
from nexus.company.management.plans import ChildAllocation, PlanPayload
from nexus.company.management.transactions import ManagementDeniedError
from nexus.company.notifications.native_profile_checks import (
    require_notification_action,
    require_notification_plan,
)
from nexus.execution.runtime_contracts import AttemptKind
from nexus.harness.journal_models import CompanyControl


class PlanSourceFreshness(Protocol):
    """Configured source-policy qualification, not a decoded caller permission."""

    async def revalidate_references(
        self,
        session: AsyncSession,
        scope: BrainReadScope,
        references: tuple[ArtifactRevisionRef, ...],
        now: datetime,
    ) -> None: ...


class CurrentPlanBinding(ManagementContract):
    """A descriptive managed-child binding; current permission still needs fresh checks."""

    plan: PlanRevisionRef
    child: ChildAllocation
    work: WorkItem
    work_sha256: SHA256
    procedure_id: UUID


async def _actor(session: AsyncSession, control: CompanyControl, actor_id: UUID) -> None:
    await require_member(session, control, actor_id)
    member = await session.get(DirectoryMembership, (control.company_id, actor_id))
    if member is None or member.role == "viewer":
        raise ManagementDeniedError("Plan actor cannot be a read-only member")


async def _resource(
    session: AsyncSession,
    company_id: UUID,
    reference: ResourceRef,
    principals: set[UUID],
    now: datetime,
    read_scope: BrainReadScope,
    freshness: PlanSourceFreshness | None,
) -> None:
    resource = await session.get(BrainResource, (company_id, reference.resource_id))
    if resource is None or not resource.active:
        raise ManagementDeniedError("Configured plan resource is unavailable")
    for principal in principals:
        grant = await session.get(
            BrainResourceAccess, (company_id, reference.resource_id, principal)
        )
        if grant is None or not grant.active or (grant.expires_at and grant.expires_at <= now):
            raise ManagementDeniedError("Plan actor/verifier resource access is unavailable")
    if resource.kind == "source":
        source = await session.scalar(
            select(BrainSource).where(
                BrainSource.company_id == company_id,
                BrainSource.resource_id == resource.resource_id,
            )
        )
        head = (
            await session.get(BrainSourceHead, (company_id, source.source_id)) if source else None
        )
        if (
            head is None
            or head.availability != "available"
            or (head.fresh_until and head.fresh_until <= now)
        ):
            raise ManagementDeniedError("Plan source is unavailable or stale")
        if head.fresh_until is None:
            if freshness is None:
                raise ManagementDeniedError(
                    "NoTTL plan source needs its registered freshness policy"
                )
            revision = await session.get(
                BrainSourceRevision, (company_id, head.current_revision_id)
            )
            artifact = (
                await session.get(
                    BrainArtifactRevision, (company_id, revision.artifact_revision_id)
                )
                if revision
                else None
            )
            if artifact is None:
                raise ManagementDeniedError("NoTTL source artifact is unavailable")
            artifact_ref = ArtifactRevisionRef(
                company_id=company_id,
                artifact_id=artifact.artifact_id,
                artifact_revision_id=artifact.artifact_revision_id,
                revision=artifact.revision,
                sha256=artifact.sha256,
                byte_length=artifact.byte_length,
            )
            await freshness.revalidate_references(
                session, read_scope, (artifact_ref,), await db_clock(session)
            )


def validate_plan_profile(
    catalog: PlanAdmissionCatalog, child: ChildAllocation, now: datetime
) -> None:
    """Pure current-clock registry/profile eligibility, never action or execution permission."""
    validate_model_profile(catalog, child, now)


async def _child(
    session: AsyncSession,
    control: CompanyControl,
    catalog: PlanAdmissionCatalog,
    child: ChildAllocation,
    item: WorkItem,
    charter: CharterRevision,
    now: datetime,
    read_scope: BrainReadScope,
    freshness: PlanSourceFreshness | None,
) -> None:
    await _actor(session, control, child.binding.actor_id)
    await _actor(session, control, charter.charter.verifier_id)
    if item.department != charter.charter.name:
        raise ManagementDeniedError("Work department differs from its exact current charter")
    validate_model_profile(catalog, child, now)
    tools = {row.tool: row for row in catalog.tools}
    resources = {row.symbol: row.resource for row in catalog.resources}
    if (
        not set(charter.charter.allowed_tools) <= tools.keys()
        or not set(charter.charter.resource_scopes) <= resources.keys()
    ):
        raise ManagementDeniedError("Charter contains unknown tool or resource eligibility")
    if any(
        tools[name].resource not in charter.charter.resource_scopes
        for name in charter.charter.allowed_tools
    ):
        raise ManagementDeniedError("Configured tool resource escapes the charter scope")
    for name in charter.charter.resource_scopes:
        await _resource(
            session,
            control.company_id,
            resources[name],
            {child.binding.actor_id, charter.charter.verifier_id},
            now,
            read_scope,
            freshness,
        )


async def validate_plan(
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    payload: PlanPayload,
    catalog: PlanAdmissionCatalog,
    freshness: PlanSourceFreshness | None = None,
) -> dict[UUID, CharterRevision]:
    """Re-read exact current owner-approved heads/members/grants in the same company mutex."""
    # This >50-line traversal keeps the complete approved DAG and final TTL check in one flow.
    if payload.company_id != scope.company_id or catalog.company_id != scope.company_id:
        raise ManagementDeniedError("Plan admission company is unavailable")
    require_native_plan(catalog, payload)
    require_notification_plan(catalog, payload)
    mandate = await current_mandate(session, scope, payload.mandate)
    if (
        mandate.mandate.owner_id != control.owner_id
        or catalog.models.pricebook_version != control.price_version
    ):
        raise ManagementDeniedError("Plan owner or configured catalog pricebook is not current")
    goal = await GoalStore._current(session, scope, payload.goal)
    await require_member(session, control, goal.definition.owner_id)
    head = await session.get(ManagementGoalHead, (scope.company_id, payload.goal.goal_id))
    if head is None or not head.active or goal.definition.mandate != payload.mandate:
        raise ManagementDeniedError("Plan goal is inactive or binds another mandate")
    if mandate.mandate.goals and payload.goal.goal_id not in mandate.mandate.goals:
        raise ManagementDeniedError("Plan goal is outside its mandate")
    if (
        payload.procedure.binding.workspace_id != identity.workspace_id
        or payload.procedure.allocation_usd > mandate.mandate.work_cap_usd
    ):
        raise ManagementDeniedError("Procedure workspace or owner-admitted budget differs")
    await _actor(session, control, payload.procedure.binding.actor_id)
    charters = {
        ref.revision_id: await current_charter(session, scope, ref) for ref in payload.charters
    }
    if any(row.mandate != payload.mandate for row in charters.values()):
        raise ManagementDeniedError("Plan charter binds another mandate")
    items = {row.task_id: row for row in payload.plan.items}
    children = {row.binding.task_id: row for row in payload.children}
    read_scope = BrainReadScope(
        company_id=scope.company_id,
        workspace_id=identity.workspace_id,
        principal_id=identity.principal_id,
        operation_id=scope.operation_id,
        trace_id=scope.trace_id,
    )
    for child in payload.children:
        await _child(
            session,
            control,
            catalog,
            child,
            items[child.binding.task_id],
            charters[child.charter.revision_id],
            await db_clock(session),
            read_scope,
            freshness,
        )
    for edge in payload.verification:
        author, verifier = children[edge.author_task_id], children[edge.verifier_task_id]
        if (
            edge.check_recipe not in catalog.check_recipes
            or verifier.binding.actor_id != charters[author.charter.revision_id].charter.verifier_id
        ):
            raise ManagementDeniedError("Verification recipe or actual charter verifier differs")
    await _final_expiry_check(session, payload, catalog, charters)
    return charters


async def _final_expiry_check(
    session: AsyncSession,
    payload: PlanPayload,
    catalog: PlanAdmissionCatalog,
    charters: dict[UUID, CharterRevision],
) -> None:
    resources = {
        value.resource.resource_id
        for value in catalog.resources
        if any(value.symbol in row.charter.resource_scopes for row in charters.values())
    }
    actors = {row.binding.actor_id for row in payload.children} | {
        row.charter.verifier_id for row in charters.values()
    }
    grant_expiry = await session.scalar(
        select(func.min(BrainResourceAccess.expires_at)).where(
            BrainResourceAccess.company_id == payload.company_id,
            BrainResourceAccess.resource_id.in_(resources),
            BrainResourceAccess.principal_id.in_(actors),
        )
    )
    source_expiry = await session.scalar(
        select(func.min(BrainSourceHead.fresh_until))
        .join(
            BrainSource,
            (BrainSource.company_id == BrainSourceHead.company_id)
            & (BrainSource.source_id == BrainSourceHead.source_id),
        )
        .where(BrainSource.company_id == payload.company_id, BrainSource.resource_id.in_(resources))
    )
    now = await db_clock(session)
    if any(value is not None and value <= now for value in (grant_expiry, source_expiry)):
        raise ManagementDeniedError("Plan resource eligibility expired during admission")
    for child in payload.children:
        validate_model_profile(catalog, child, now)


def validate_plan_action(
    catalog: PlanAdmissionCatalog,
    child: ChildAllocation,
    charter: CharterRevision,
    proposal: ActionProposal,
    kind: AttemptKind,
    now: datetime,
) -> None:
    """Current charter/server tuples narrow actual effects alongside exact M1 approval."""
    # Keep the >50-line native/model/tool narrowing together so none skips the exact ABI.
    cycle = validate_cycle_catalog(catalog.cycle_admission, catalog)
    require_native_action(catalog, child, proposal, kind)
    require_notification_action(catalog, child, proposal, kind)
    if proposal.tool == "model.request.v1":
        if (
            kind != "model_requests"
            or proposal.tool_version != "v1"
            or not proposal.resource.startswith("model:")
        ):
            raise ManagementDeniedError(
                "Managed model request ABI differs from the governed gateway"
            )
        model_id = proposal.resource.removeprefix("model:")
        selected = next((row for row in catalog.models.models if row.registry_id == model_id), None)
        if selected is None:
            raise ManagementDeniedError("Managed model request names an unregistered model")
        validate_model_profile(
            catalog.model_copy(
                update={
                    "models": catalog.models.model_copy(update={"models": (selected,)}),
                    "model_observations": tuple(
                        row for row in catalog.model_observations if row.registry_id == model_id
                    ),
                    # The original native tuple was checked above; this view selects a model.
                    "native_profiles": (),
                    "notification_profiles": (),
                    "cycle_admission": None,
                    "nexus_cycle_admission": None,
                }
            ),
            child,
            now,
        )
        return
    if kind != "tool_attempts":
        raise ManagementDeniedError("Managed tools require their tool-attempt budget")
    if cycle is not None:
        selected_slot = next((slot for slot in cycle.slots if slot.child == child), None)
        if selected_slot is None or (proposal.tool, proposal.tool_version, proposal.resource) != (
            selected_slot.tool.tool,
            selected_slot.tool.tool_version,
            selected_slot.tool.resource,
        ):
            raise ManagementDeniedError("Cycle effect differs from its exact declared role tuple")
    if catalog.nexus_cycle_admission is not None:
        slot = next(
            (slot for slot in catalog.nexus_cycle_admission.slots if slot.child == child), None
        )
        if slot is None or (proposal.tool, proposal.tool_version, proposal.resource) != (
            slot.tool.tool,
            slot.tool.tool_version,
            slot.tool.resource,
        ):
            raise ManagementDeniedError("Nexus effect differs from its exact configured role")
    permission = next(
        (
            row
            for row in catalog.tools
            if (row.tool, row.tool_version, row.resource)
            == (proposal.tool, proposal.tool_version, proposal.resource)
        ),
        None,
    )
    if (
        permission is None
        or proposal.tool not in charter.charter.allowed_tools
        or proposal.resource not in charter.charter.resource_scopes
    ):
        raise ManagementDeniedError("Actual managed tool/version/resource escapes its charter")

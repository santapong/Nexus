"""Actual current managed sender/draft qualification; all facts remain descriptive."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.base import BrainReadScope
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.control_support import current_charter
from nexus.company.management.lifecycle import PlanRevisionRef
from nexus.company.management.native_profile_admission import control_scope, ledger_scope
from nexus.company.management.plan_models import ManagementPlanRevision
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plan_support import CurrentPlanBinding, PlanAdmissionCatalog
from nexus.company.management.plans import PlanPayload
from nexus.company.management.revision_store import plan_record
from nexus.company.notifications.contracts import NotificationDraft
from nexus.company.notifications.draft_store import NotificationDraftStore, require_draft_time
from nexus.company.notifications.managed_contracts import NotificationPreparationPolicy
from nexus.company.notifications.managed_sources import profile_deadlines, protection_deadlines
from nexus.company.notifications.native_facts import NotificationUnavailableError
from nexus.company.notifications.proposals import NotificationProposal
from nexus.company.notifications.status_support import current_owner_message
from nexus.execution.management_checks import require_management_execution
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import db_now, require_runtime_scope
from nexus.harness.journal_models import CompanyControl


def notification_action_id(plan: PlanRevisionRef, task_id: UUID, draft_id: UUID) -> UUID:
    return uuid5(plan.plan_revision_id, f"managed-owner-notification.v1:{task_id}:{draft_id}")


@dataclass(frozen=True)
class ManagedNotificationAdmission:
    binding: CurrentPlanBinding
    draft: NotificationDraft
    payload: PlanPayload
    deadlines: tuple[datetime, ...]

    def require_time(self, catalog: PlanAdmissionCatalog, now: datetime) -> None:
        require_draft_time(self.draft, now)
        profile_deadlines(self.payload, catalog, now)
        if any(value <= now for value in self.deadlines):
            raise NotificationUnavailableError("Managed notification qualification expired")


async def current_sender(
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    work: ExecutionWork,
    policy: NotificationPreparationPolicy,
) -> CurrentPlanBinding:
    if (
        not policy.enabled
        or identity.principal_id != control.owner_id
        or work.actor_id != control.owner_id
        or work.company_id != policy.target.company_id
        or (work.workflow_name, work.workflow_version)
        != (policy.workflow_name, policy.workflow_version)
    ):
        raise NotificationUnavailableError("Current owner managed sender is unavailable")
    binding = await ManagementPlanStore.current_binding(session, scope.company_id, work.task_id)
    if binding is None:
        raise NotificationUnavailableError("Managed notification needs an approved native child")
    await require_runtime_scope(
        session,
        control,
        ledger_scope(binding.child.binding),
        identity,
        allow_inactive=False,
        owner_read=False,
    )
    return binding


async def managed_admission(
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    work: ExecutionWork,
    draft_id: UUID,
    action: ActionProposal,
    drafts: NotificationDraftStore,
    catalog: PlanAdmissionCatalog,
    artifacts: BoundedArtifactReader,
    freshness: RegisteredSourceFreshness,
    policy: NotificationPreparationPolicy,
) -> ManagedNotificationAdmission:
    binding = await current_sender(session, control, scope, identity, work, policy)
    draft = await current_owner_message(
        session, control, control_scope(scope), identity, drafts, draft_id
    )
    await _exact_action(session, scope, binding, draft, action, catalog, policy)
    await require_management_execution(
        session, control, work, identity, catalog, artifacts, freshness, action, "tool_attempts"
    )
    row = await session.get(
        ManagementPlanRevision, (scope.company_id, binding.plan.plan_revision_id)
    )
    if row is None:
        raise NotificationUnavailableError("Managed notification native plan is unavailable")
    payload = plan_record(row).payload
    deadlines = await protection_deadlines(session, scope, payload, catalog, freshness, draft)
    deadlines += profile_deadlines(payload, catalog, await db_now(session))
    result = ManagedNotificationAdmission(binding, draft, payload, deadlines)
    result.require_time(catalog, await db_now(session))
    return result


async def _exact_action(
    session: AsyncSession,
    scope: BrainReadScope,
    binding: CurrentPlanBinding,
    draft: NotificationDraft,
    action: ActionProposal,
    catalog: PlanAdmissionCatalog,
    policy: NotificationPreparationPolicy,
) -> None:
    NotificationProposal(
        company_id=scope.company_id,
        draft_id=draft.draft_id,
        payload_sha256=draft.payload_sha256,
        recipient_policy_sha256=draft.recipient_policy.sha256,
        action=action,
    )
    if (
        action.action_id
        != notification_action_id(binding.plan, binding.child.binding.task_id, draft.draft_id)
        or action.tool_version != "v1"
        or action.resource != policy.resource_symbol
        or action.estimated_cost_usd != policy.estimated_cost_usd
    ):
        raise NotificationUnavailableError("Managed notification proposal pins differ")
    charter = await current_charter(session, control_scope(scope), binding.child.charter)
    resources = {row.symbol: row.resource for row in catalog.resources}
    if (
        resources.get(policy.resource_symbol) != policy.target
        or not set(charter.charter.resource_scopes) <= resources.keys()
        or not set(draft.provenance.required_resource_ids)
        <= {resources[name].resource_id for name in charter.charter.resource_scopes}
    ):
        raise NotificationUnavailableError("Managed sender charter does not cover the full draft")

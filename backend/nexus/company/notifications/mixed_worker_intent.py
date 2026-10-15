"""Concrete mixed sender config/action closure; native admission and slot gates still execute."""

import json
from dataclasses import replace
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.cycle_catalog_checks import validate_cycle_catalog
from nexus.company.management.plan_catalog import PlanAdmissionCatalog
from nexus.company.notifications.draft_store import NotificationDraftStore
from nexus.company.notifications.managed_admission import notification_action_id
from nexus.company.notifications.native_facts import NotificationUnavailableError
from nexus.company.notifications.proposals import NOTIFICATION_TOOL, NotificationDispatchParameters
from nexus.company.notifications.worker_guard import NotificationOperationGuard
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.company.notifications.worker_intent import CredentialNotificationIntentCheck
from nexus.company.notifications.worker_services import NotificationWorkerServices
from nexus.execution.intent_checks import BeforeIntentCheck
from nexus.execution.runtime_contracts import ExecutionDeniedError, ExecutionLease
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import db_now
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CompanyControl, JournalAction


def require_mixed_notification_intent_check(
    catalog: PlanAdmissionCatalog | None,
    work: ExecutionWork,
    lease: ExecutionLease,
    identity: VerifiedIdentity,
    action: JournalAction,
    before_intent: BeforeIntentCheck | None,
) -> None:
    """Shape/binding only; the native awaited checks and final clock remain mandatory."""
    if catalog is None or catalog.cycle_admission is None:
        return
    admission = validate_cycle_catalog(catalog.cycle_admission, catalog)
    assert admission is not None
    slot = admission.slots[-1]
    if (
        work.task_id != slot.child.binding.task_id
        and work.model_profile != "notification.native.v1"
    ):
        return
    from nexus.company.notifications.managed_effects import ManagedNotificationIntent
    from nexus.company.notifications.managed_preparation import ManagedNotificationPreparation

    denied = "Fresh mixed sender intent requires its exact native checks"
    if (
        type(before_intent) is not ManagedNotificationIntent
        or type(before_intent.frozen) is not MixedCredentialNotificationIntentCheck
    ):
        raise ExecutionDeniedError(denied)
    check, preparation = before_intent.frozen, before_intent.preparation
    try:
        check._require_composition()
        bound = slot.child.binding
        proposal = ActionProposal.model_validate_json(action.proposal_json)
        pins = NotificationDispatchParameters.model_validate_json(
            json.dumps(proposal.parameters, allow_nan=False)
        )
        if (
            type(preparation) is not ManagedNotificationPreparation
            or check.lease != lease
            or check.identity != identity
            or check.witness.identity != identity
            or check.operation_guard.witness is not check.witness
            or check.action_id != action.id
            or pins.draft_id != check.draft_id
            or action.proposal_hash != action_hash(proposal)
            or (proposal.tool, proposal.tool_version, proposal.resource)
            != (NOTIFICATION_TOOL, "v1", slot.tool.resource)
            or (
                proposal.company_id,
                proposal.action_id,
                proposal.task_id,
                proposal.trace_id,
                proposal.actor_id,
            )
            != (work.company_id, action.id, work.task_id, work.trace_id, work.actor_id)
            or (
                work.company_id,
                work.task_id,
                work.trace_id,
                work.run_id,
                work.actor_id,
                work.workspace_id,
            )
            != (
                bound.company_id,
                bound.task_id,
                bound.trace_id,
                bound.run_id,
                bound.actor_id,
                bound.workspace_id,
            )
            or (
                lease.company_id,
                lease.task_id,
                lease.trace_id,
                lease.run_id,
                lease.actor_id,
                lease.workspace_id,
            )
            != (
                bound.company_id,
                bound.task_id,
                bound.trace_id,
                bound.run_id,
                bound.actor_id,
                bound.workspace_id,
            )
            or any(
                type(v) is not int or v != 0
                for v in (
                    work.model_requests_limit,
                    work.model_requests_used,
                    work.model_requests_delegated,
                )
            )
            or canonical_sha256(check.reads.facts.catalog) != canonical_sha256(catalog)
            or preparation.factory is not check.reads.factory
            or preparation.drafts is not check.drafts
            or preparation.artifacts is not check.reads.facts.artifacts
            or preparation.freshness is not check.reads.facts.freshness
            or preparation.policy != check.reads.preparation.policy
            or canonical_sha256(preparation.catalog) != canonical_sha256(catalog)
        ):
            raise ExecutionDeniedError(denied)
    except ValueError as exc:
        raise ExecutionDeniedError(denied) from exc


class MixedCredentialNotificationIntentCheck(CredentialNotificationIntentCheck):
    """One operation's exact witness/config/action; neither a DTO nor a reusable permission."""

    def __init__(
        self,
        lease: ExecutionLease,
        witness: AuthenticatedWorkerIdentity,
        draft_id: UUID,
        drafts: NotificationDraftStore,
        target: ResourceRef,
        resource_symbol: str,
        *,
        action_id: UUID,
        operation_guard: NotificationOperationGuard,
        reads: NotificationWorkerServices,
    ) -> None:
        if (
            type(operation_guard) is not NotificationOperationGuard
            or type(reads) is not NotificationWorkerServices
        ):
            raise NotificationUnavailableError(
                "Mixed notification concrete operation is unavailable"
            )
        self.operation_guard, self.reads, self.action_id = operation_guard, reads, action_id
        self._factory = reads.factory
        self._catalog_sha256 = canonical_sha256(reads.facts.catalog)
        super().__init__(lease, witness, draft_id, drafts, target, resource_symbol)
        self._require_composition()

    def _require_composition(self) -> None:
        replace(self.reads)  # Existing pure dependency checks; no token, SQL or file read.
        catalog = self.reads.facts.catalog
        configured = validate_cycle_catalog(catalog.cycle_admission, catalog)
        if configured is None:
            raise NotificationUnavailableError("Mixed notification complete cycle is unavailable")
        registered = self.operation_guard.registration
        bound = configured.slots[-1].child.binding
        resources = {row.symbol: row.resource for row in catalog.resources}
        if (
            self.operation_guard.witness is not self.witness
            or self.operation_guard.reader is not self.reads.registrations
            or self.reads.factory is not self._factory
            or self.drafts is not self.reads.drafts
            or self.drafts.factory is not self._factory
            or self.reads.facts.artifacts.factory is not self._factory
            or self.reads.facts.freshness._factory is not self._factory
            or canonical_sha256(catalog) != self._catalog_sha256
            or registered.sender != bound
            or registered.plan.plan_id != configured.plan_id
            or registered.plan.revision != 2
            or self.target != self.reads.preparation.policy.target
            or self.resource_symbol != self.reads.preparation.policy.resource_symbol
            or resources.get(configured.slots[-1].tool.resource) != self.target
            or configured.slots[-1].tool.resource != self.resource_symbol
            or self.action_id
            != notification_action_id(registered.plan, bound.task_id, self.draft_id)
            or (
                self.lease.company_id,
                self.lease.task_id,
                self.lease.trace_id,
                self.lease.run_id,
                self.lease.actor_id,
                self.lease.workspace_id,
                self.lease.workflow_version,
            )
            != (
                bound.company_id,
                bound.task_id,
                bound.trace_id,
                bound.run_id,
                bound.actor_id,
                bound.workspace_id,
                bound.workflow_version,
            )
        ):
            raise NotificationUnavailableError("Mixed notification exact composition differs")
        self.operation_guard.require_identity(self.identity)
        self.operation_guard.require_company(self.lease.company_id)
        self.reads.require_registration(self.operation_guard.snapshot)

    def require_current(self, now: datetime) -> None:
        """Synchronous complete composition/config/credential closure after the last await."""
        self._require_composition()
        self.operation_guard.require_time(now)
        self.witness.require_time(now)

    async def validate(
        self,
        session: AsyncSession,
        control: CompanyControl,
        work: ExecutionWork,
        action: JournalAction,
        now: datetime,
    ) -> None:
        self.require_current(now)
        if (
            (action.id, action.company_id, action.task_id, action.trace_id)
            != (self.action_id, self.lease.company_id, self.lease.task_id, self.lease.trace_id)
            or control.owner_id != self.identity.principal_id
            or (
                work.company_id,
                work.task_id,
                work.trace_id,
                work.run_id,
                work.actor_id,
                work.workspace_id,
            )
            != (
                self.lease.company_id,
                self.lease.task_id,
                self.lease.trace_id,
                self.lease.run_id,
                self.lease.actor_id,
                self.lease.workspace_id,
            )
        ):
            raise NotificationUnavailableError("Mixed notification actual sender/action differs")
        await super().validate(session, control, work, action, now)
        self.require_current(await db_now(session))

    def validate_time(self, now: datetime) -> None:
        self.require_current(now)
        super().validate_time(now)

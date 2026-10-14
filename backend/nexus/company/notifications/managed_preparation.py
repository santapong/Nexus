"""Prepare exact pending actions for existing approved owner children; no grants or execution."""

from __future__ import annotations

import asyncio
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.base import BrainReadScope
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.lifecycle import PlanRevisionRef
from nexus.company.management.native_profile_admission import ledger_scope
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.company.management.transactions import management_owner_transaction
from nexus.company.notifications.contracts import NotificationDraft
from nexus.company.notifications.draft_store import NotificationDraftStore, owner_scope
from nexus.company.notifications.managed_admission import (
    ManagedNotificationAdmission,
    current_sender,
    managed_admission,
    notification_action_id,
)
from nexus.company.notifications.managed_contracts import (
    NativeNotificationSelection,
    NotificationPreparationPolicy,
    PreparedNotification,
)
from nexus.company.notifications.native_facts import NotificationUnavailableError
from nexus.company.notifications.proposals import NOTIFICATION_TOOL, NotificationDispatchParameters
from nexus.company.notifications.status_support import current_owner_message
from nexus.company.notifications.worker_guard import NotificationOperationGuard
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_contracts import ActionRecord
from nexus.harness.journal_models import CompanyControl
from nexus.harness.journal_submission import submit_pending_locked


class ManagedNotificationPreparation:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        drafts: NotificationDraftStore,
        catalog: PlanAdmissionCatalog,
        artifacts: BoundedArtifactReader,
        freshness: RegisteredSourceFreshness,
        *,
        policy: NotificationPreparationPolicy,
        operation_guard: NotificationOperationGuard | None = None,
    ) -> None:
        if operation_guard is not None and not isinstance(
            operation_guard, NotificationOperationGuard
        ):
            raise ValueError("Native notification operation guard is unavailable")
        self.operation_guard = operation_guard
        self.factory, self.drafts, self.artifacts, self.freshness = (
            factory,
            drafts,
            artifacts,
            freshness,
        )
        self.catalog = PlanAdmissionCatalog.model_validate_json(catalog.model_dump_json())
        self.policy = NotificationPreparationPolicy.model_validate_json(policy.model_dump_json())
        if self.policy.target.company_id != self.catalog.company_id:
            raise ValueError("Managed notification target differs from configured company")

    async def prepare(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        selection: NativeNotificationSelection,
    ) -> PreparedNotification:
        if self.operation_guard is not None:
            self.operation_guard.require_identity(identity)
            self.operation_guard.require_company(scope.company_id)
            self.operation_guard.require_company(selection.company_id)
            self.operation_guard.require_company(self.catalog.company_id)
        selection = NativeNotificationSelection.model_validate_json(selection.model_dump_json())
        if (
            selection.company_id != scope.company_id
            or selection.company_id != self.catalog.company_id
        ):
            raise NotificationUnavailableError("Managed notification selection is unavailable")
        async with (
            asyncio.timeout(30),
            management_owner_transaction(self.factory, scope, identity) as (session, control, _),
        ):
            work = await session.get(ExecutionWork, (scope.company_id, selection.sender_task_id))
            if work is None:
                raise NotificationUnavailableError("Managed notification sender is unavailable")
            brain = owner_scope(scope, identity)
            bound = await current_sender(session, control, brain, identity, work, self.policy)
            if bound.plan != selection.plan:
                raise NotificationUnavailableError("Managed notification selects another plan")
            draft = await current_owner_message(
                session, control, scope, identity, self.drafts, selection.draft_id
            )
            action = self._proposal(
                bound.plan, work, draft, control.policy_version, control.price_version
            )
            first = await self.admit(
                session, control, brain, identity, work, draft.draft_id, action
            )
            record = await submit_pending_locked(
                session, control, action, ledger_scope(bound.child.binding)
            )
            final = await self.admit(
                session, control, brain, identity, work, draft.draft_id, action
            )
            now = await db_now(session)
            self.drafts.recipients.require_current(draft.recipient_policy, now)
            first.require_time(self.catalog, now)
            final.require_time(self.catalog, now)
            if self.operation_guard is not None:
                self.operation_guard.require_time(now)
            return self._result(selection, final, work, record)

    @staticmethod
    def _result(
        selection: NativeNotificationSelection,
        admitted: ManagedNotificationAdmission,
        work: ExecutionWork,
        record: ActionRecord,
    ) -> PreparedNotification:
        return PreparedNotification(
            company_id=work.company_id,
            selection=selection,
            sender=admitted.binding.child.binding,
            registration_sha256=work.registration_hash,
            action=record,
            payload_sha256=admitted.draft.payload_sha256,
            recipient_policy_sha256=admitted.draft.recipient_policy.sha256,
        )

    async def admit(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        work: ExecutionWork,
        draft_id: UUID,
        action: ActionProposal,
    ) -> ManagedNotificationAdmission:
        return await managed_admission(
            session,
            control,
            scope,
            identity,
            work,
            draft_id,
            action,
            self.drafts,
            self.catalog,
            self.artifacts,
            self.freshness,
            self.policy,
        )

    def _proposal(
        self,
        plan: PlanRevisionRef,
        work: ExecutionWork,
        draft: NotificationDraft,
        policy_version: str,
        price_version: str,
    ) -> ActionProposal:
        return ActionProposal(
            company_id=work.company_id,
            action_id=notification_action_id(plan, work.task_id, draft.draft_id),
            task_id=work.task_id,
            trace_id=work.trace_id,
            actor_id=work.actor_id,
            revision=1,
            tool=NOTIFICATION_TOOL,
            tool_version="v1",
            resource=self.policy.resource_symbol,
            parameters=NotificationDispatchParameters(
                draft_id=draft.draft_id,
                payload_sha256=draft.payload_sha256,
                recipient_policy_sha256=draft.recipient_policy.sha256,
            ).model_dump(mode="json"),
            policy_version=policy_version,
            price_version=price_version,
            estimated_cost_usd=self.policy.estimated_cost_usd,
        )

"""Actual M1 specialization composes frozen slot checks with current managed qualification."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.contracts.actions import ActionProposal, ResourceRevision
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.company.notifications.dispatch_support import dispatch_scope
from nexus.company.notifications.draft_store import NotificationDraftStore
from nexus.company.notifications.intent_check import NotificationIntentCheck
from nexus.company.notifications.managed_admission import ManagedNotificationAdmission
from nexus.company.notifications.managed_contracts import NotificationPreparationPolicy
from nexus.company.notifications.managed_preparation import ManagedNotificationPreparation
from nexus.company.notifications.native_facts import NotificationUnavailableError
from nexus.execution.effect_store import EffectStore
from nexus.execution.intent_checks import BeforeIntentCheck
from nexus.execution.receipt_events import ReceiptEventPublisher
from nexus.execution.runtime_contracts import AttemptKind, EffectStart, ExecutionLease
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.journal_models import CompanyControl, JournalAction


class ManagedNotificationEffectStore(EffectStore):
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        drafts: NotificationDraftStore,
        catalog: PlanAdmissionCatalog,
        artifacts: BoundedArtifactReader,
        freshness: RegisteredSourceFreshness,
        *,
        policy: NotificationPreparationPolicy,
        receipt_events: ReceiptEventPublisher | None = None,
    ) -> None:
        self.preparation = ManagedNotificationPreparation(
            factory, drafts, catalog, artifacts, freshness, policy=policy
        )
        super().__init__(
            factory,
            management_catalog=self.preparation.catalog,
            management_artifacts=artifacts,
            management_freshness=freshness,
            receipt_events=receipt_events,
        )

    async def begin(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        action_id: UUID,
        *,
        resources: tuple[ResourceRevision, ...] = (),
        kind: AttemptKind = "tool_attempts",
        before_intent: BeforeIntentCheck | None = None,
    ) -> EffectStart:
        if not isinstance(before_intent, NotificationIntentCheck) or kind != "tool_attempts":
            raise NotificationUnavailableError("Managed notification needs its native slot check")
        return await super().begin(
            lease,
            identity,
            action_id,
            resources=resources,
            kind=kind,
            before_intent=ManagedNotificationIntent(before_intent, self.preparation),
        )


class ManagedNotificationIntent:
    def __init__(
        self, frozen: NotificationIntentCheck, preparation: ManagedNotificationPreparation
    ) -> None:
        self.frozen, self.preparation = frozen, preparation
        self.admission: ManagedNotificationAdmission | None = None

    async def validate(
        self,
        session: AsyncSession,
        control: CompanyControl,
        work: ExecutionWork,
        action: JournalAction,
        now: datetime,
    ) -> None:
        await self.frozen.validate(session, control, work, action, now)
        current = await self.preparation.admit(
            session,
            control,
            dispatch_scope(self.frozen.lease, self.frozen.identity, action.id),
            self.frozen.identity,
            work,
            self.frozen.draft_id,
            ActionProposal.model_validate_json(action.proposal_json),
        )
        self.admission = current
        self.frozen.deadlines += current.deadlines

    def validate_time(self, now: datetime) -> None:
        self.frozen.validate_time(now)
        if self.admission is None:
            raise NotificationUnavailableError("Managed notification admission is unavailable")
        self.admission.require_time(self.preparation.catalog, now)

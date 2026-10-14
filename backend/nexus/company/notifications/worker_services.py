"""Pure process composition and actual sender qualification; never effects or new allowance."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.access_models import BrainResourceAccess
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.events import OutboxEvent
from nexus.company.brain.native_fact_contracts import DecisionState, DigestSelector
from nexus.company.brain.native_fact_emitter import NativeFactEmitter
from nexus.company.brain.native_fact_reader import NativeFactReader
from nexus.company.brain.native_fact_services import NativeFactServices
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.operating_report_resources import report_resources
from nexus.company.management.plan_models import ManagementPlanRevision
from nexus.company.management.plan_support import CurrentPlanBinding
from nexus.company.management.plans import PlanPayload
from nexus.company.management.revision_store import plan_record
from nexus.company.notifications.draft_store import owner_scope
from nexus.company.notifications.managed_admission import (
    ManagedNotificationAdmission,
    current_sender,
)
from nexus.company.notifications.managed_contracts import (
    NativeNotificationSelection,
    PreparedNotification,
)
from nexus.company.notifications.managed_preparation import ManagedNotificationPreparation
from nexus.company.notifications.managed_sources import plan_resources, profile_deadlines
from nexus.company.notifications.native_facts import NativeNotificationFact
from nexus.company.notifications.proposals import NOTIFICATION_TOOL
from nexus.company.notifications.qualified_adapter import QualifiedNotificationFactAdapter
from nexus.company.notifications.qualified_consumer import QualifiedNotificationConsumer
from nexus.company.notifications.qualified_facts import QualifiedNotificationFact
from nexus.company.notifications.qualified_store import QualifiedNotificationDraftStore
from nexus.company.notifications.worker_config import (
    FileNotificationWorkerRegistration,
    WorkerConfigurationError,
    WorkerRegistrationSnapshot,
)
from nexus.company.notifications.worker_guard import NotificationOperationGuard
from nexus.company.notifications.worker_identity import NotificationWorkerIdentities
from nexus.execution.management_checks import require_management_execution
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import CompanyControl, JournalAction

_UNAVAILABLE = "Notification worker services are unavailable"


@dataclass(frozen=True, slots=True)
class GuardedNotificationServices:
    emitter: NativeFactEmitter
    consumer: QualifiedNotificationConsumer
    preparation: "WorkerNotificationPreparation"
    drafts: QualifiedNotificationDraftStore


class WorkerNotificationFactAdapter(QualifiedNotificationFactAdapter):
    """Qualify first, then refuse recursive decision inputs without acknowledgment."""

    def __init__(
        self, original: QualifiedNotificationFactAdapter, guard: NotificationOperationGuard
    ) -> None:
        super().__init__(original.legacy, original.reader)
        self.guard = guard

    async def load(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        event: OutboxEvent,
    ) -> NativeNotificationFact:
        value = await super().load(session, control, scope, identity, event)
        if isinstance(value, QualifiedNotificationFact) and isinstance(
            value.native_state, DecisionState
        ):
            state = value.native_state
            if state.work.task_id == self.guard.registration.sender.task_id or (
                state.action.proposal.tool == NOTIFICATION_TOOL
            ):
                raise WorkerConfigurationError(_UNAVAILABLE)
        return value


class WorkerNotificationPreparation(ManagedNotificationPreparation):
    """Single operation observer; expose a new action ID after inherited final commit."""

    _started: bool = False
    _observed: bool = False
    _candidate_created_id: UUID | None = None
    _committed_created_id: UUID | None = None

    @property
    def created_action_id(self) -> UUID | None:
        return self._committed_created_id

    async def prepare(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        selection: NativeNotificationSelection,
    ) -> PreparedNotification:
        if self._started:
            raise WorkerConfigurationError(_UNAVAILABLE)
        self._started = True
        result = await super().prepare(scope, identity, selection)
        self._committed_created_id = self._candidate_created_id
        return result

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
        result = await super().admit(session, control, scope, identity, work, draft_id, action)
        from nexus.company.notifications.worker_consumer import WorkerSenderFinalGuard

        if not isinstance(self.operation_guard, WorkerSenderFinalGuard):
            raise WorkerConfigurationError(_UNAVAILABLE)
        self.operation_guard.capture(
            WorkerSenderAdmission(result.binding, result.payload, work, result.deadlines)
        )
        if not self._observed:
            self._observed = True
            if await session.get(JournalAction, action.action_id) is None:
                self._candidate_created_id = action.action_id
        return result


@dataclass(frozen=True, slots=True)
class WorkerSenderAdmission:
    """Captured native binding/windows only; actual locked permission remains separately checked."""

    binding: CurrentPlanBinding
    payload: PlanPayload
    work: ExecutionWork
    deadlines: tuple[datetime, ...]

    def require_time(self, services: "NotificationWorkerServices", now: datetime) -> None:
        profile_deadlines(self.payload, services.facts.catalog, now)
        if any(value <= now for value in self.deadlines):
            raise WorkerConfigurationError(_UNAVAILABLE)


@dataclass(frozen=True, slots=True)
class NotificationWorkerServices:
    factory: async_sessionmaker[AsyncSession]
    identities: NotificationWorkerIdentities
    registrations: FileNotificationWorkerRegistration
    facts: NativeFactServices
    drafts: QualifiedNotificationDraftStore
    preparation: ManagedNotificationPreparation

    def __post_init__(self) -> None:
        if (
            not isinstance(self.identities, NotificationWorkerIdentities)
            or not isinstance(self.registrations, FileNotificationWorkerRegistration)
            or not isinstance(self.facts, NativeFactServices)
            or not isinstance(self.drafts, QualifiedNotificationDraftStore)
            or not isinstance(self.preparation, ManagedNotificationPreparation)
            or self.drafts.factory is not self.factory
            or self.preparation.factory is not self.factory
            or self.preparation.drafts is not self.drafts
            or self.preparation.operation_guard is not None
            or self.drafts.loader.reader.services is not self.facts
            or self.preparation.catalog != self.facts.catalog
            or self.drafts.loader.catalog != self.facts.catalog
            or self.preparation.artifacts is not self.facts.artifacts
            or self.preparation.freshness is not self.facts.freshness
            or self.drafts.loader.artifacts is not self.facts.artifacts
            or self.drafts.loader.freshness is not self.facts.freshness
        ):
            raise WorkerConfigurationError(_UNAVAILABLE)

    def require_registration(self, snapshot: WorkerRegistrationSnapshot) -> None:
        if not isinstance(snapshot, WorkerRegistrationSnapshot):
            raise WorkerConfigurationError(_UNAVAILABLE)
        value = snapshot.value.registration
        if (
            value.company_id != self.facts.catalog.company_id
            or value.sender.model_registry_version != self.facts.catalog.models.revision
            or value.catalog_sha256 != canonical_sha256(self.facts.catalog)
            or value.notification_policy_sha256 != canonical_sha256(self.drafts.policy)
            or value.preparation_policy_sha256 != canonical_sha256(self.preparation.policy)
        ):
            raise WorkerConfigurationError(_UNAVAILABLE)
        digests = {row.schedule: row for row in self.facts.digests}
        for subject in value.subjects:
            if isinstance(subject.selector, DigestSelector):
                digest = digests.get(subject.selector.schedule)
                if digest is None or digest.policy != self.drafts.policy:
                    raise WorkerConfigurationError(_UNAVAILABLE)
                expected = digest.resource
            else:
                expected = self.facts.resource
            if subject.resource != expected:
                raise WorkerConfigurationError(_UNAVAILABLE)

    def guarded(self, guard: NotificationOperationGuard) -> GuardedNotificationServices:
        from nexus.company.notifications.worker_consumer import (
            WorkerNotificationConsumer,
            WorkerSenderFinalGuard,
        )

        if not isinstance(guard, NotificationOperationGuard):
            raise WorkerConfigurationError(_UNAVAILABLE)
        self.require_registration(guard.snapshot)
        guard.require_company(self.facts.catalog.company_id)
        guard.reader.require_current(guard.snapshot)
        if guard.reader is not self.registrations:
            raise WorkerConfigurationError(_UNAVAILABLE)
        value = guard.registration
        reader = NativeFactReader(self.facts)
        drafts = QualifiedNotificationDraftStore(
            self.factory,
            WorkerNotificationFactAdapter(self.drafts.loader, guard),
            self.drafts.recipients,
            policy=self.drafts.policy,
        )
        return GuardedNotificationServices(
            NativeFactEmitter(self.factory, reader, operation_guard=guard),
            WorkerNotificationConsumer(
                drafts,
                consumer=value.consumer,
                recipe_version=value.recipe_version,
                operation_guard=guard,
                services=self,
            ),
            WorkerNotificationPreparation(
                self.factory,
                drafts,
                self.facts.catalog,
                self.facts.artifacts,
                self.facts.freshness,
                policy=self.preparation.policy,
                operation_guard=WorkerSenderFinalGuard(guard, self),
            ),
            drafts,
        )

    async def require_sender_locked(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: CompanyControlScope,
        guard: NotificationOperationGuard,
    ) -> WorkerSenderAdmission:
        self.require_registration(guard.snapshot)
        guard.require_company(scope.company_id)
        guard.require_company(control.company_id)
        identity = guard.witness.identity
        if scope.principal_id != identity.principal_id or control.owner_id != identity.principal_id:
            raise WorkerConfigurationError(_UNAVAILABLE)
        work = await session.get(
            ExecutionWork, (scope.company_id, guard.registration.sender.task_id)
        )
        if work is None:
            raise WorkerConfigurationError(_UNAVAILABLE)
        bound = await current_sender(
            session, control, owner_scope(scope, identity), identity, work, self.preparation.policy
        )
        if (
            bound.child.binding != guard.registration.sender
            or bound.plan != guard.registration.plan
        ):
            raise WorkerConfigurationError(_UNAVAILABLE)
        await require_management_execution(
            session,
            control,
            work,
            identity,
            self.facts.catalog,
            self.facts.artifacts,
            self.facts.freshness,
        )
        row = await session.get(
            ManagementPlanRevision, (scope.company_id, bound.plan.plan_revision_id)
        )
        if row is None:
            raise WorkerConfigurationError(_UNAVAILABLE)
        payload = plan_record(row).payload
        deadlines = await self._sender_deadlines(session, scope, guard, payload)
        result = WorkerSenderAdmission(bound, payload, work, deadlines)
        final = await db_now(session)
        result.require_time(self, final)
        guard.require_time(final)
        return result

    async def _sender_deadlines(
        self,
        session: AsyncSession,
        scope: CompanyControlScope,
        guard: NotificationOperationGuard,
        payload: PlanPayload,
    ) -> tuple[datetime, ...]:
        brain = owner_scope(scope, guard.witness.identity)
        resources, actors = await plan_resources(session, brain, payload, self.facts.catalog)
        _, _, heads = await report_resources(session, brain, resources, ())
        expiry = await session.scalar(
            select(func.min(BrainResourceAccess.expires_at)).where(
                BrainResourceAccess.company_id == scope.company_id,
                BrainResourceAccess.resource_id.in_(resources),
                BrainResourceAccess.principal_id.in_(actors),
            )
        )
        deadlines = tuple(row.fresh_until for row in heads if row.fresh_until is not None)
        return deadlines + ((expiry,) if expiry is not None else ())

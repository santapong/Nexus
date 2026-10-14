"""Additive native kind adapter; committed old failed/accepted loader remains unchanged."""

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.events import OutboxEvent
from nexus.company.brain.native_fact_contracts import (
    BlockedState,
    CompanyCapState,
    DecisionState,
    DigestState,
    NativeFactProjection,
    WorkCapState,
)
from nexus.company.brain.native_fact_reader import NativeFactReader
from nexus.company.brain.native_fact_wake import event_selector
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.operating_report_resources import report_resources
from nexus.company.notifications.contracts import (
    NativeDigestBinding,
    NativeNotificationSignal,
    NotificationProvenance,
)
from nexus.company.notifications.native_facts import (
    NativeNotificationFact,
    NotificationUnavailableError,
)
from nexus.company.notifications.native_loader import NativeNotificationFactLoader
from nexus.company.notifications.qualified_facts import (
    ObsoleteNotificationFactError,
    QualifiedNotificationFact,
)
from nexus.harness.journal_models import CompanyControl

NATIVE_NOTIFICATION_KINDS = frozenset(
    {"decision_required", "work_blocked", "cap_exhausted", "digest_due"}
)


class QualifiedNotificationFactAdapter(NativeNotificationFactLoader):
    def __init__(self, legacy: NativeNotificationFactLoader, reader: NativeFactReader) -> None:
        if legacy.catalog != reader.services.catalog:
            raise ValueError("Qualified notification services require the exact native catalog")
        super().__init__(legacy.catalog, legacy.artifacts, legacy.freshness)
        self.legacy, self.reader = legacy, reader

    async def load(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        event: OutboxEvent,
    ) -> NativeNotificationFact:
        if event.kind in {"receipt_recorded", "verification_recorded"}:
            return await self.legacy.load(session, control, scope, identity, event)
        if event.kind not in NATIVE_NOTIFICATION_KINDS:
            raise NotificationUnavailableError("Native notification event is unsupported")
        if event_selector(event, self.reader.services) is None:
            raise NotificationUnavailableError("Native notification configuration is unavailable")
        frame = await self.reader.load_event_locked(session, control, scope, identity, event)
        if frame is None:
            raise ObsoleteNotificationFactError("Native notification wake is obsolete")
        resources, _, heads = await report_resources(
            session, scope, frame.required_resource_ids, frame.artifacts
        )
        provenance = NotificationProvenance(
            company_id=scope.company_id,
            required_resource_ids=resources,
            artifacts=frame.artifacts,
            source_heads=heads,
            protection_deadlines=frame.protection_deadlines,
            native_snapshot_sha256=frame.state_sha256,
        )
        signal = _signal(event, frame)
        return QualifiedNotificationFact(
            company_id=scope.company_id,
            signal=signal,
            work_title=_title(frame),
            provenance=provenance,
            native_state=frame.state,
        )


def _signal(event: OutboxEvent, frame: NativeFactProjection) -> NativeNotificationSignal:
    state = frame.state
    digest = None
    day = None
    if isinstance(state, DecisionState):
        subject, kind = state.action.proposal.action_id, "decision_required"
    elif isinstance(state, BlockedState):
        subject, kind = state.work.task_id, "blocked"
    elif isinstance(state, WorkCapState):
        subject, kind = state.work.task_id, "cap_exhausted"
    elif isinstance(state, CompanyCapState):
        subject, kind, day = state.company_id, "cap_exhausted", state.budget_day
    elif isinstance(state, DigestState):
        subject, kind = state.saved.report_id, "digest_due"
        digest = NativeDigestBinding(
            company_id=state.company_id,
            report_id=state.saved.report_id,
            report_snapshot_sha256=canonical_sha256(state.saved),
            registration_sha256=canonical_sha256(state.registration),
            policy_sha256=canonical_sha256(state.registration.policy),
            kind=state.registration.kind,
            due_bucket=state.due_bucket,
            scheduled_for=state.scheduled_for,
        )
    else:
        raise NotificationUnavailableError("Native notification state is unsupported")
    return NativeNotificationSignal.model_validate(
        {
            "company_id": event.company_id,
            "event_ids": (event.event_id,),
            "subject_id": subject,
            "kind": kind,
            "state_sha256": frame.state_sha256,
            "source_event": frame.source_event,
            "observed_at": event.recorded_at,
            "budget_day": day,
            "digest": digest,
        }
    )


def _title(frame: NativeFactProjection) -> str:
    state = frame.state
    if isinstance(state, DecisionState):
        return "Native action awaiting owner decision"
    if isinstance(state, BlockedState):
        return "Native work blocked"
    if isinstance(state, WorkCapState):
        return "Native work allowance exhausted"
    if isinstance(state, CompanyCapState):
        return "Native company daily allowance exhausted"
    if isinstance(state, DigestState):
        return "Native operating report"
    raise NotificationUnavailableError("Native notification state is unsupported")

"""Actual old-profile receipt/acceptance facts; new notification kinds await normal015."""

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.base import BrainReadScope, SourceTime
from nexus.company.brain.event_models import BrainEvent
from nexus.company.brain.event_store import event_record
from nexus.company.brain.events import OutboxEvent
from nexus.company.brain.scope_support import require_brain_scope
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.acceptance import WorkAcceptance
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.acceptance_support import receipt_artifacts
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.company.notifications.contracts import (
    CurrentWorkAcceptance,
    NativeNotificationSignal,
    NotificationProvenance,
)
from nexus.company.notifications.native_facts import (
    NativeNotificationFact,
    NotificationUnavailableError,
)
from nexus.company.notifications.native_provenance import native_provenance
from nexus.execution.management_checks import current_accepted_work
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.harness.journal_models import CompanyControl


def require_native(value: bool) -> None:
    if not value:
        raise NotificationUnavailableError("Native notification facts are unavailable")


async def native_receipt(
    session: AsyncSession, event: OutboxEvent
) -> tuple[EffectIntent, ExecutionWork, ActionReceipt]:
    require_native(event.action_id is not None)
    intent = await session.get(EffectIntent, (event.company_id, event.action_id))
    require_native(intent is not None and intent.receipt_json is not None)
    assert intent is not None and intent.receipt_json is not None
    work = await session.get(ExecutionWork, (event.company_id, intent.task_id))
    require_native(work is not None)
    assert work is not None
    receipt = ActionReceipt.model_validate_json(intent.receipt_json)
    require_native(
        (
            receipt.company_id,
            receipt.action_id,
            receipt.task_id,
            receipt.trace_id,
            receipt.proposal_hash,
        )
        == (work.company_id, intent.action_id, work.task_id, work.trace_id, intent.proposal_hash)
        and (intent.task_id, intent.trace_id, intent.run_id)
        == (work.task_id, work.trace_id, work.run_id)
    )
    return intent, work, receipt


class NativeNotificationFactLoader:
    def __init__(
        self,
        catalog: PlanAdmissionCatalog,
        artifacts: BoundedArtifactReader,
        freshness: RegisteredSourceFreshness,
    ) -> None:
        self.catalog, self.artifacts, self.freshness = catalog, artifacts, freshness

    async def load(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        event: OutboxEvent,
    ) -> NativeNotificationFact:
        require_native(session.in_transaction() and event.company_id == scope.company_id)
        await require_brain_scope(session, control, scope, identity, owner=True)
        row = await session.get(BrainEvent, (scope.company_id, event.event_id))
        require_native(row is not None and event_record(row) == event)
        # A raw UUID, source wake, candidate, or future015 kind is not a meaningful fact.
        require_native(event.kind in {"receipt_recorded", "verification_recorded"})
        intent, work, receipt = await native_receipt(session, event)
        binding = await ManagementPlanStore.current_binding(session, scope.company_id, work.task_id)
        require_native(binding is not None)
        assert binding is not None
        accepted = await self._acceptance(session, control, identity, event, intent, work, receipt)
        refs = await receipt_artifacts(session, receipt) if receipt.artifacts else ()
        if accepted is not None:
            refs += tuple(proof.result_artifact for proof in accepted.proofs)
        refs = tuple({item.artifact_revision_id: item for item in refs}.values())
        provenance = await native_provenance(
            session,
            scope,
            binding,
            self.catalog,
            self.freshness,
            refs,
            canonical_sha256(receipt if accepted is None else accepted),
        )
        require_native(event.resource.resource_id in provenance.required_resource_ids)
        return _fact(event, work, receipt, accepted, provenance, binding.work.title)

    async def _acceptance(
        self,
        session: AsyncSession,
        control: CompanyControl,
        identity: VerifiedIdentity,
        event: OutboxEvent,
        intent: EffectIntent,
        work: ExecutionWork,
        receipt: ActionReceipt,
    ) -> WorkAcceptance | None:
        if event.kind == "receipt_recorded":
            require_native(intent.state == "failed" and receipt.outcome == "failed")
            return None
        require_native(intent.state == "succeeded" and receipt.outcome == "succeeded")
        accepted = await current_accepted_work(
            session, control, work, work, identity, self.artifacts, self.freshness
        )
        require_native(accepted is not None and accepted.target.action_id == intent.action_id)
        return accepted


def _fact(
    event: OutboxEvent,
    work: ExecutionWork,
    receipt: ActionReceipt,
    accepted: WorkAcceptance | None,
    provenance: NotificationProvenance,
    title: str,
) -> NativeNotificationFact:
    signal = NativeNotificationSignal(
        company_id=work.company_id,
        event_ids=(event.event_id,),
        subject_id=work.task_id,
        kind="failed" if accepted is None else "work_accepted",
        state_sha256=canonical_sha256(receipt if accepted is None else accepted),
        source_event=SourceTime(
            precision="instant",
            value=(accepted.recorded_at if accepted else receipt.recorded_at).isoformat(),
            basis="native WorkAcceptance recorded_at"
            if accepted
            else "native M1 receipt recorded_at",
        ),
        observed_at=event.recorded_at,
        acceptance=CurrentWorkAcceptance(company_id=work.company_id, acceptance=accepted)
        if accepted
        else None,
    )
    return NativeNotificationFact(
        company_id=work.company_id,
        signal=signal,
        work_title=title,
        provenance=provenance,
        details=(
            f"Receipt: {receipt.receipt_id}",
            "Billing and goal outcome remain separate native records.",
        ),
    )

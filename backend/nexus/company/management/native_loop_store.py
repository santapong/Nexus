"""One bounded explicit tick composes native preparation and scheduling, never approvals."""

from datetime import UTC, timedelta
from typing import Literal

import structlog

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.management.native_loop_authorization import authorize_loop_action
from nexus.company.management.native_loop_capacity import release_preparation_capacity
from nexus.company.management.native_loop_contracts import (
    LoopState,
    NativeOperatingRegistration,
    NativeOperatingTick,
    phase_states,
)
from nexus.company.management.native_loop_dispatch import schedule_loop_action
from nexus.company.management.native_loop_reads import LoopSnapshot, LoopWork, inspect_loop
from nexus.company.management.native_profile_admission import ledger_scope
from nexus.company.management.native_profile_store import NativeReportPreparationService
from nexus.company.management.scheduling_contracts import EventWake, SchedulerPolicy
from nexus.company.management.scheduling_store import ManagementScheduler
from nexus.company.management.scheduling_support import SchedulerServices
from nexus.execution.native_report_services import NativeReportServices
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.harness.journal_contracts import ActionRecord

logger = structlog.get_logger()


def _known_success(work: LoopWork) -> bool:
    return bool(work.effect and work.effect.receipt and work.effect.receipt.outcome == "succeeded")


class NativeReportOperatingLoop:
    """Trusted fixed services/registration; no timer, model, queue worker or owner issuer starts."""

    def __init__(
        self,
        registration: NativeOperatingRegistration,
        preparation: NativeReportPreparationService,
        native: NativeReportServices,
    ) -> None:
        self.registration = NativeOperatingRegistration.model_validate_json(
            registration.model_dump_json()
        )
        if (
            self.registration.company_id != preparation.catalog.company_id
            or native.producer is not preparation.producer
            or native.factory is not preparation.factory
            or native.publisher.catalog != preparation.catalog
        ):
            raise ValueError("Native loop services differ from trusted preparation composition")
        self.preparation, self.native = preparation, native
        self.scheduler = ManagementScheduler(
            native.factory,
            SchedulerServices(
                policy=SchedulerPolicy(
                    recipe_version="native-report-loop-v1",
                    consumer=f"native.report.loop.{registration.registration_id.hex}",
                    max_tasks=1,
                    workflows=(native.registration,),
                ),
                catalog=preparation.catalog,
                artifacts=native.artifacts,
                freshness=native.publisher.freshness,
                identities=native.identities,
                resources=native.resources,
            ),
        )

    def _result(
        self,
        current: LoopSnapshot,
        state: LoopState,
        reason: str,
        *,
        pending: ActionRecord | None = None,
        created: bool = False,
    ) -> NativeOperatingTick:
        now = current.observed_at
        return NativeOperatingTick(
            company_id=self.registration.company_id,
            registration_id=self.registration.registration_id,
            observed_at=now,
            state=state,
            reason=reason,
            author_action_id=self.registration.action_id("author"),
            verifier_action_id=self.registration.action_id("verifier"),
            pending=pending,
            preparation_performed=created,
            opportunity_scan=now.astimezone(UTC).minute % 15 == 0,
            next_fallback_at=now.replace(second=0, microsecond=0) + timedelta(minutes=1),
            acceptance=current.acceptance if state == "accepted" else None,
            historical_acceptance_ids=(current.historical.acceptance_id,)
            if current.historical
            else (),
        )

    async def tick(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        *,
        event: EventWake | None = None,
    ) -> NativeOperatingTick:
        """Inspect actual owner/native facts once and perform at most one prep or exact enqueue."""
        event = EventWake.model_validate_json(event.model_dump_json()) if event else None
        current = await inspect_loop(
            self.native.factory, self.registration, self.native, scope, identity, event
        )
        if current.stopped is not None:
            return self._result(current, "blocked", current.stopped)
        if current.acceptance is not None:
            return self._result(current, "accepted", "actual_current_proof")
        if current.historical is not None:
            return self._result(current, "closed", "historical_acceptance_not_current")
        assert current.profile is not None
        due = current.profile.due
        if (
            due.actionable_basis != "operator_explicit"
            or due.actionable_at is None
            or due.actionable_at > current.observed_at
        ):
            return self._result(current, "not_due", "no_current_owner_due_instant")
        for work in (current.author, current.verifier):
            if work.billing_unknown:
                return self._result(current, "outcome_unknown", "issued_billing_unknown")
            if work.effect is not None and not _known_success(work):
                return self._result(
                    current, "outcome_unknown", "issued_result_requires_reconciliation"
                )
        try:
            if not _known_success(current.author):
                return await self._author(current, scope, identity, event)
            if current.verifier.effect is not None:
                return self._result(current, "closed", "known_check_requires_proof_reconciliation")
            return await self._verifier(current, scope, identity, event)
        except ValueError as exc:
            logger.bind(
                task_id=str(current.author.execution.registration.work.task_id),
                trace_id=str(scope.trace_id),
            ).info("native_loop_admission_denied", error_type=type(exc).__name__)
            return self._result(current, "blocked", "current_admission_unavailable")

    async def _author(
        self,
        current: LoopSnapshot,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        event: EventWake | None,
    ) -> NativeOperatingTick:
        work = current.author
        if work.action is None:
            prepared = await self.preparation.prepare_author(self.registration.profile)
            return self._result(
                current,
                "author_pending",
                "exact_owner_decision_required",
                pending=prepared.action,
                created=True,
            )
        return await self._existing(current, work, "author", scope, identity, event)

    async def _verifier(
        self,
        current: LoopSnapshot,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        event: EventWake | None,
    ) -> NativeOperatingTick:
        if current.verifier.action is not None:
            return await self._existing(
                current, current.verifier, "verifier", scope, identity, event
            )
        assert current.profile is not None
        binding = current.profile.selection.verifier
        signed = self.native.identities.actor(binding)
        lease: ExecutionLease | None = None
        try:
            lease = await self.native.execution.claim(
                ledger_scope(binding),
                signed,
                self.native.worker_id,
                ttl_seconds=self.native.lease_ttl_seconds,
            )
            prepared = await self.preparation.prepare_verifier(
                self.registration.profile, lease, self.registration.action_id("author")
            )
            if prepared.action.state.value == "awaiting_approval":
                await self.native.execution.await_approval(
                    lease, signed, prepared.action.proposal.action_id
                )
            else:
                await self.native.execution.release(lease, signed)
            lease = None
            return self._result(
                current,
                "verifier_pending",
                "exact_owner_decision_required",
                pending=prepared.action,
                created=True,
            )
        finally:
            if lease is not None:
                try:
                    await self.native.execution.release(lease, signed)
                except ValueError as exc:
                    logger.bind(task_id=str(binding.task_id), trace_id=str(binding.trace_id)).info(
                        "native_loop_preparation_lease_not_released", error_type=type(exc).__name__
                    )

    async def _existing(
        self,
        current: LoopSnapshot,
        work: LoopWork,
        phase: Literal["author", "verifier"],
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        event: EventWake | None,
    ) -> NativeOperatingTick:
        assert work.action is not None
        action = work.action
        pending_state, dispatch_state = phase_states(phase)
        if work.dispatch:
            return self._result(current, dispatch_state, "existing_permanent_dispatch")
        assert current.profile is not None
        binding = (
            current.profile.selection.author
            if phase == "author"
            else current.profile.selection.verifier
        )
        if (
            phase == "verifier"
            and action.state.value == "awaiting_approval"
            and not await release_preparation_capacity(
                self.native, binding, work.execution, action, current.observed_at
            )
        ):
            return self._result(current, pending_state, "preparation_lease_active", pending=action)
        if (
            action.approval is not None
            and action.approval.decision == "approved"
            and action.consumed_at is None
        ):
            action = await authorize_loop_action(self.native, self.registration, binding, phase)
        if action.state.value == "awaiting_approval":
            return self._result(
                current, pending_state, "exact_owner_decision_required", pending=action
            )
        if action.state.value != "authorized" or action.consumed_at is None:
            return self._result(current, "closed", "native_action_not_authorized")
        scheduled = await schedule_loop_action(
            self.scheduler, current.observed_at, work.execution, action, scope, identity, event
        )
        if scheduled is None:
            return self._result(current, "blocked", "scheduler_current_admission_unavailable")
        return NativeOperatingTick.model_validate_json(
            self._result(current, dispatch_state, "native_authorized_dispatch")
            .model_copy(update={"scheduled": scheduled})
            .model_dump_json()
        )

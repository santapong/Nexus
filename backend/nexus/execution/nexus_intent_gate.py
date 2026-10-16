"""Required exact concrete Nexus checks, captured before awaits; never a permit or DTO."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.nexus_cycle_admission import validate_nexus_catalog
from nexus.company.management.plan_admission_candidates import capture_child_window
from nexus.company.management.plan_admission_window import PlanChildWindow
from nexus.company.management.plan_catalog import PlanAdmissionCatalog
from nexus.execution.intent_checks import BeforeIntentCheck, CompositeBeforeIntentCheck
from nexus.execution.qualification_intent_gate import _action_pin, _work_pin
from nexus.execution.runtime_contracts import AttemptKind, ExecutionDeniedError, ExecutionLease
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import JournalAction

if TYPE_CHECKING:
    from nexus.execution.effect_store import EffectStore

DENIED = "Fresh Nexus intent requires its exact original native checks"


def _shape(
    factory: async_sessionmaker[AsyncSession],
    effects: EffectStore,
    catalog: PlanAdmissionCatalog,
    work: ExecutionWork,
    lease: ExecutionLease,
    identity: VerifiedIdentity,
    action: JournalAction,
    kind: AttemptKind,
    check: BeforeIntentCheck | None,
) -> tuple[object, ...]:
    admission = validate_nexus_catalog(catalog.nexus_cycle_admission, catalog)
    assert admission is not None
    slot = next((slot for slot in admission.slots if slot.work.task_id == work.task_id), None)
    if slot is None:
        if work.model_profile in {
            "engineering.native.v1",
            "verification.native.v1",
            "notification.native.v1",
        }:
            raise ExecutionDeniedError(DENIED)
        return ()
    bound = slot.child.binding
    proposal = ActionProposal.model_validate_json(action.proposal_json)
    if (
        kind != ("model_requests" if slot.role == "planner" else "tool_attempts")
        or effects._factory is not factory
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
        or (identity.principal_id, identity.workspace_id) != (bound.actor_id, bound.workspace_id)
        or proposal.action_id != action.id
        or action.proposal_hash != action_hash(proposal)
        or (proposal.tool, proposal.tool_version, proposal.resource)
        != (slot.tool.tool, slot.tool.tool_version, slot.tool.resource)
    ):
        raise ExecutionDeniedError(DENIED)
    if slot.role == "planner":
        from nexus.company.management.nexus_planning_intent import NexusPlanningIntentCheck
        from nexus.harness.model_authorizer_contracts import model_action_parameters
        from nexus.harness.model_input_estimator import FullContextInputEstimator
        from nexus.harness.model_intent import ModelIntentCheck

        if type(check) is not CompositeBeforeIntentCheck or len(check._checks) != 3:
            raise ExecutionDeniedError(DENIED)
        planning, model, repeated = check._checks
        if (
            type(planning) is not NexusPlanningIntentCheck
            or type(model) is not ModelIntentCheck
            or repeated is not planning
        ):
            raise ExecutionDeniedError(DENIED)
        planning.require_composition()
        if (
            planning.factory is not factory
            or planning._context_check._lease != lease
            or planning.credential.identity != identity
            or model.lease != lease
            or type(model.estimator) is not FullContextInputEstimator
            or planning.registry != model.registry
            or model.estimator.estimate(model.call, model.registry, model.recipe)
            != planning._prepared.input_estimate
            or model.call != planning._prepared.request
            or canonical_sha256(model.registry) != canonical_sha256(catalog.models)
            or proposal.parameters != model_action_parameters(model.call, model.recipe)
        ):
            raise ExecutionDeniedError(DENIED)
        return (
            check,
            planning,
            model,
            planning.credential,
            planning._objects,
            planning._pins,
            model.call,
            canonical_sha256(model.registry),
            model.recipe,
            model.estimator,
            model.observations,
        )
    if slot.role in {"engineering", "engineering_check"}:
        from nexus.builder.contained_intent_check import ContainedParentIntentCheck
        from nexus.builder.nexus_source_guard import NexusBuilderSourceGuard

        if type(check) is not CompositeBeforeIntentCheck or len(check._checks) != 2:
            raise ExecutionDeniedError(DENIED)
        source, parent = check._checks
        if (
            type(source) is not NexusBuilderSourceGuard
            or type(parent) is not ContainedParentIntentCheck
        ):
            raise ExecutionDeniedError(DENIED)
        source.require_composition()
        if (
            source.lease != lease
            or source.identity != identity
            or source.artifacts.factory is not factory
            or (
                source.containment is not parent.services
                or canonical_sha256(source.catalog) != canonical_sha256(catalog)
            )
            or source.spec.job.action_id != action.id
            or proposal.parameters != source.spec.model_dump(mode="json")
        ):
            raise ExecutionDeniedError(DENIED)
        expected = parent.services.expectation
        job = source.spec.job
        if (
            expected.company_id,
            expected.task_id,
            expected.trace_id,
            expected.run_id,
            expected.action_id,
        ) != (job.company_id, job.task_id, job.trace_id, job.run_id, job.action_id):
            raise ExecutionDeniedError(DENIED)
        return (
            check,
            source,
            parent,
            source.credential,
            source._objects,
            source._pin,
            parent.services,
            parent.services.deadline,
        )
    if slot.role == "sender":
        from nexus.company.notifications.managed_effects import ManagedNotificationIntent
        from nexus.company.notifications.mixed_worker_intent import (
            require_mixed_notification_intent_check,
        )

        require_mixed_notification_intent_check(catalog, work, lease, identity, action, check)
        if type(check) is not ManagedNotificationIntent or check.preparation.factory is not factory:
            raise ExecutionDeniedError(DENIED)
        return check, check.frozen, check.preparation, check.preparation.catalog
    from nexus.company.management.generated_artifact_store import GeneratedArtifactPublisher
    from nexus.company.management.native_report_validator import NativeReportValidator
    from nexus.execution.native_report_context import NativeReportContext
    from nexus.execution.native_report_services import NativeReportServices
    from nexus.execution.nexus_report_intent import NexusReportIntent

    if type(check) is not NexusReportIntent or type(check.context) is not NativeReportContext:
        raise ExecutionDeniedError(DENIED)
    check.require_composition()
    context = check.context
    services = context.services
    if (
        type(services) is not NativeReportServices
        or context.lease != lease
        or context.identity != identity
        or (
            context.command.company_id,
            context.command.task_id,
            context.command.trace_id,
            context.command.run_id,
            context.command.actor_id,
            context.command.workspace_id,
            context.command.action_id,
            context.command.segment_id,
        )
        != (
            lease.company_id,
            lease.task_id,
            lease.trace_id,
            lease.run_id,
            lease.actor_id,
            lease.workspace_id,
            action.id,
            lease.segment_id,
        )
        or (
            context.action != proposal
            or services.factory is not factory
            or services.effects is not effects
            or services.execution._factory is not factory
            or services.publisher.factory is not factory
            or services.artifacts.factory is not factory
            or services.producer.factory is not factory
            or type(services.publisher) is not GeneratedArtifactPublisher
            or type(services.publisher.validator) is not NativeReportValidator
            or services.publisher.validator.producer is not services.producer
            or services.publisher.artifacts is not services.artifacts
            or canonical_sha256(services.publisher.catalog) != canonical_sha256(catalog)
        )
    ):
        raise ExecutionDeniedError(DENIED)
    from nexus.company.management.generated_artifact_identity import require_action_payload

    rule = services.publisher.rules.get(proposal.tool)
    if rule is None:
        raise ExecutionDeniedError(DENIED)
    require_action_payload(proposal, rule, check.prepared)
    return check, context, services, check.credential, check._objects, check._pins


@dataclass(frozen=True)
class NexusIntentGate:
    factory: async_sessionmaker[AsyncSession]
    effects: EffectStore
    catalog: PlanAdmissionCatalog | None
    work_pin: tuple[object, ...]
    action_pin: tuple[object, ...]
    lease: ExecutionLease
    identity: VerifiedIdentity
    kind: AttemptKind
    check: BeforeIntentCheck | None
    shape: tuple[object, ...]
    catalog_sha: str | None
    children: tuple[PlanChildWindow, ...]

    def validate_time(self, now: datetime) -> None:
        for child in self.children:
            child.require_time(now)

    def require_current(
        self, work: ExecutionWork, action: JournalAction, check: BeforeIntentCheck | None
    ) -> None:
        current = self.effects._management_catalog
        if self.catalog_sha is None:
            if current is not None and current.nexus_cycle_admission is not None:
                raise ExecutionDeniedError(DENIED)
            return
        try:
            if (
                current is not self.catalog
                or current is None
                or canonical_sha256(current) != self.catalog_sha
                or (
                    check is not self.check
                    or _work_pin(work) != self.work_pin
                    or _action_pin(action) != self.action_pin
                )
                or _shape(
                    self.factory,
                    self.effects,
                    current,
                    work,
                    self.lease,
                    self.identity,
                    action,
                    self.kind,
                    check,
                )
                != self.shape
            ):
                raise ExecutionDeniedError(DENIED)
        except (ValueError, AttributeError, TypeError) as error:
            raise ExecutionDeniedError(DENIED) from error


def bind_nexus_intent_check(
    factory: async_sessionmaker[AsyncSession],
    effects: EffectStore,
    work: ExecutionWork,
    lease: ExecutionLease,
    identity: VerifiedIdentity,
    action: JournalAction,
    kind: AttemptKind,
    check: BeforeIntentCheck | None,
    *,
    now: datetime,
) -> NexusIntentGate:
    catalog = effects._management_catalog
    digest = (
        canonical_sha256(catalog)
        if catalog is not None and catalog.nexus_cycle_admission is not None
        else None
    )
    try:
        shape = (
            _shape(factory, effects, catalog, work, lease, identity, action, kind, check)
            if digest is not None and catalog is not None
            else ()
        )
        children: tuple[PlanChildWindow, ...] = ()
        if shape and catalog is not None and catalog.nexus_cycle_admission is not None:
            slots = catalog.nexus_cycle_admission.slots
            selected = slots[:1] if slots[0].work.task_id == work.task_id else slots
            children = tuple(capture_child_window(catalog, slot.child, now) for slot in selected)
        gate = NexusIntentGate(
            factory,
            effects,
            catalog,
            _work_pin(work),
            _action_pin(action),
            lease,
            identity,
            kind,
            check,
            shape,
            digest,
            children,
        )
        gate.require_current(work, action, check)
        gate.validate_time(now)
        return gate
    except (ValueError, AttributeError, TypeError) as error:
        raise ExecutionDeniedError(DENIED) from error

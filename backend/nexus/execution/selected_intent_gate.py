"""Closed required check composition for fresh mixed E/EV; no permission from caller flags."""

from nexus.company.access import VerifiedIdentity
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.cycle_catalog_checks import validate_cycle_catalog
from nexus.company.management.plan_catalog import PlanAdmissionCatalog
from nexus.execution.intent_checks import BeforeIntentCheck, CompositeBeforeIntentCheck
from nexus.execution.runtime_contracts import ExecutionDeniedError, ExecutionLease
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.journal_models import JournalAction


def _require(value: bool) -> None:
    if not value:
        raise ExecutionDeniedError(
            "Fresh selected engineering intent requires its exact native checks"
        )


def require_selected_intent_check(
    catalog: PlanAdmissionCatalog | None,
    work: ExecutionWork,
    lease: ExecutionLease,
    identity: VerifiedIdentity,
    action: JournalAction,
    before_intent: BeforeIntentCheck | None,
) -> None:
    """Shape/binding only; both actual awaited checks and final time checks remain mandatory."""
    # Complete bounded composition comparison stays cohesive before any reservation or intent write.
    if catalog is None or catalog.cycle_admission is None:
        return
    admission = validate_cycle_catalog(catalog.cycle_admission, catalog)
    assert admission is not None
    native = admission.slots[2:4]
    expected = next((slot for slot in native if slot.child.binding.task_id == work.task_id), None)
    if expected is None and work.model_profile not in {
        "engineering.native.v1",
        "verification.native.v1",
    }:
        return
    _require(expected is not None and type(before_intent) is CompositeBeforeIntentCheck)
    assert expected is not None and type(before_intent) is CompositeBeforeIntentCheck
    checks = before_intent._checks
    _require(len(checks) == 2)
    from nexus.builder.contained_intent_check import ContainedParentIntentCheck
    from nexus.builder.selected_strategy_guard import StrategySelectedBuilderGuard

    selected = tuple(check for check in checks if type(check) is StrategySelectedBuilderGuard)
    parents = tuple(check for check in checks if type(check) is ContainedParentIntentCheck)
    _require(len(selected) == len(parents) == 1)
    guard, parent = selected[0], parents[0]
    _require(
        type(guard) is StrategySelectedBuilderGuard and type(parent) is ContainedParentIntentCheck
    )
    _require(checks == (guard, parent))
    bound, job = expected.child.binding, guard.spec.job
    _require(
        guard.lease == lease
        and guard.identity == identity == guard.credential.identity
        and guard.reader.reader.artifacts.factory is guard.artifacts.factory
        and guard.reader.reader.artifacts is guard.artifacts
        and guard.reader.reader.freshness is guard.freshness
        and canonical_sha256(guard.catalog) == canonical_sha256(catalog)
        and canonical_sha256(guard.reader.reader.catalog) == canonical_sha256(catalog)
        and parent.services is guard.containment
    )
    _require(
        (job.company_id, job.task_id, job.trace_id, job.run_id, job.actor_id, job.workspace_id)
        == (
            bound.company_id,
            bound.task_id,
            bound.trace_id,
            bound.run_id,
            bound.actor_id,
            bound.workspace_id,
        )
        == (
            work.company_id,
            work.task_id,
            work.trace_id,
            work.run_id,
            work.actor_id,
            work.workspace_id,
        )
        == (
            lease.company_id,
            lease.task_id,
            lease.trace_id,
            lease.run_id,
            lease.actor_id,
            lease.workspace_id,
        )
        and (action.id, action.task_id, action.trace_id, action.company_id)
        == (job.action_id, job.task_id, job.trace_id, job.company_id)
    )
    expected_parent = parent.services.expectation
    _require(
        (
            expected_parent.company_id,
            expected_parent.action_id,
            expected_parent.task_id,
            expected_parent.trace_id,
            expected_parent.run_id,
        )
        == (job.company_id, job.action_id, job.task_id, job.trace_id, job.run_id)
    )

"""Same-session owner choice observations; no registration, execute lease or call permit."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.scope_support import require_brain_scope
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.control_support import db_clock
from nexus.company.management.cycle_admission import validate_stockflow_cycle
from nexus.company.management.cycle_catalog_checks import validate_cycle_catalog
from nexus.company.management.plan_admission_capture import capture_plan_admission_locked
from nexus.company.management.plan_catalog import PlanAdmissionCatalog
from nexus.company.management.plans import PlanPayload
from nexus.company.management.transactions import ManagementDeniedError
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.harness.journal_models import CompanyControl

if TYPE_CHECKING:
    from nexus.company.management.strategy_transition_observation import (
        StrategyTransitionObservation,
    )
    from nexus.company.strategy.current_proof_reader import StrategyCurrentProofReader


def is_full_transition(payload: PlanPayload, catalog: PlanAdmissionCatalog) -> bool:
    """Configured mismatches deny; ordinary and strategy-stage plans cannot carry a choice."""
    validate_cycle_catalog(catalog.cycle_admission, catalog)
    selected = validate_stockflow_cycle(catalog.cycle_admission, catalog.models, payload)
    full = selected is not None and selected.stage == "full"
    if (payload.strategy_selection is not None) != full:
        raise ManagementDeniedError("Only a configured full plan requires an exact Strategy choice")
    return full


def require_transition_dependencies(
    payload: PlanPayload,
    catalog: PlanAdmissionCatalog,
    freshness: object,
    reader: object,
    credential: object,
    identity: VerifiedIdentity,
) -> None:
    """Reject missing concrete process composition before proposal/approval can write anything."""
    from nexus.company.strategy.current_proof_reader import StrategyCurrentProofReader

    if not is_full_transition(payload, catalog):
        return
    if (
        not isinstance(freshness, RegisteredSourceFreshness)
        or not isinstance(reader, StrategyCurrentProofReader)
        or not isinstance(credential, AuthenticatedWorkerIdentity)
        or credential.identity != identity
        or freshness is not reader.reader.freshness
        or canonical_sha256(reader.reader.catalog) != canonical_sha256(catalog)
    ):
        raise ManagementDeniedError(
            "Full plan requires the concrete current-owner proof composition"
        )


async def require_transition_partition_locked(
    session: AsyncSession,
    control: CompanyControl,
    identity: VerifiedIdentity,
    payload: PlanPayload,
    catalog: PlanAdmissionCatalog,
    observation: StrategyTransitionObservation,
) -> None:
    """Derive actual current stage; use the real owner sender only after actual registration."""
    from nexus.company.management.strategy_stage_partition import (
        require_strategy_stage_partition_locked,
    )
    from nexus.execution.cycle_partition_checks import require_cycle_native_partition
    from nexus.execution.runtime_models import ExecutionWork

    admission = validate_cycle_catalog(catalog.cycle_admission, catalog)
    if admission is None or not is_full_transition(payload, catalog):
        raise ManagementDeniedError("Full transition requires the complete configured occurrence")
    stage = observation.proof.current.pair.plan.plan.revision
    if stage == 1:
        await require_strategy_stage_partition_locked(
            session,
            control,
            identity,
            admission=admission,
            registry=catalog.models,
            proof=observation.proof,
        )
        return
    if stage != 2:
        raise ManagementDeniedError("Current Strategy plan stage is unavailable")
    sender = admission.slots[-1].child.binding
    if sender.actor_id != control.owner_id or identity.principal_id != sender.actor_id:
        raise ManagementDeniedError("The actual registered sender must be the current owner")
    work = await session.get(ExecutionWork, (control.company_id, sender.task_id))
    if work is None:
        raise ManagementDeniedError("Actual registered full-plan sender is unavailable")
    await require_cycle_native_partition(
        session, control, work, identity, admission=admission, registry=catalog.models
    )


async def read_strategy_transition_locked(
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    payload: PlanPayload,
    catalog: PlanAdmissionCatalog,
    freshness: RegisteredSourceFreshness,
    reader: StrategyCurrentProofReader,
    *,
    credential: AuthenticatedWorkerIdentity,
) -> StrategyTransitionObservation:
    """Real full-plan validation and concrete protected proof share the existing owner mutex."""
    from nexus.company.management.strategy_transition_observation import (
        StrategyTransitionObservation,
        validate_transition_proof,
    )

    require_transition_dependencies(payload, catalog, freshness, reader, credential, identity)
    if not is_full_transition(payload, catalog) or payload.strategy_selection is None:
        raise ManagementDeniedError("Current full-plan Strategy choice is unavailable")
    captured = await capture_plan_admission_locked(
        session, control, scope, identity, payload, catalog, freshness, credential=credential
    )
    current = BrainReadScope(
        company_id=scope.company_id,
        workspace_id=identity.workspace_id,
        principal_id=scope.principal_id,
        operation_id=scope.operation_id,
        trace_id=scope.trace_id,
    )
    proof = await reader.load_locked(
        session, control, current, identity, payload.strategy_selection, credential=credential
    )
    if proof.original.prepared.original.policy != reader.reader.production_policy:
        raise ManagementDeniedError(
            "Original Strategy production policy differs from configuration"
        )
    candidate = validate_transition_proof(payload, catalog, proof)
    observation = StrategyTransitionObservation(captured, proof, candidate)
    observation.require_time(await db_clock(session))
    return observation


async def finish_transition_locked(
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    first: StrategyTransitionObservation,
    current: StrategyTransitionObservation,
) -> None:
    """No further application await/write follows the last clock and synchronous window checks."""
    first.require_same_proof(current)
    first.admission.window.require_same_scope(current.admission.window)
    read = BrainReadScope(
        company_id=scope.company_id,
        workspace_id=identity.workspace_id,
        principal_id=scope.principal_id,
        operation_id=scope.operation_id,
        trace_id=scope.trace_id,
    )
    await require_brain_scope(session, control, read, identity, owner=True)
    now = await db_clock(session)
    first.require_time(now)
    current.require_time(now)

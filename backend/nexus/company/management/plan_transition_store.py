"""Same-session full-plan proposal/approval orchestration; no enqueue or native execution."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.control_support import db_clock, require_cas
from nexus.company.management.lifecycle import PlanRevision
from nexus.company.management.plan_models import ManagementPlanHead
from nexus.company.management.plan_registration import ensure_procedure, register_children
from nexus.company.management.plans import PlanPayload
from nexus.company.management.revision_store import (
    consume_revision,
    decision_locked,
    propose_locked,
)
from nexus.company.management.strategy_transition import (
    finish_transition_locked,
    read_strategy_transition_locked,
    require_transition_dependencies,
    require_transition_partition_locked,
)
from nexus.company.management.transactions import ManagementDeniedError
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.harness.journal_models import CompanyControl

if TYPE_CHECKING:
    from nexus.company.management.plan_store import ManagementPlanStore
    from nexus.company.strategy.current_proof_reader import StrategyCurrentProofReader


def _transition_inputs(
    store: ManagementPlanStore,
    payload: PlanPayload,
    identity: VerifiedIdentity,
    credential: AuthenticatedWorkerIdentity | None,
) -> tuple[RegisteredSourceFreshness, StrategyCurrentProofReader, AuthenticatedWorkerIdentity]:
    require_transition_dependencies(
        payload,
        store.catalog,
        store.source_freshness,
        store.strategy_proof_reader,
        credential,
        identity,
    )
    assert isinstance(store.source_freshness, RegisteredSourceFreshness)
    assert store.strategy_proof_reader is not None and credential is not None
    return store.source_freshness, store.strategy_proof_reader, credential


async def propose_transition_locked(
    store: ManagementPlanStore,
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    payload: PlanPayload,
    expected: UUID | None,
    credential: AuthenticatedWorkerIdentity | None,
) -> PlanRevision:
    freshness, reader, witness = _transition_inputs(store, payload, identity, credential)
    first = await read_strategy_transition_locked(
        session,
        control,
        scope,
        identity,
        payload,
        store.catalog,
        freshness,
        reader,
        credential=witness,
    )
    await require_transition_partition_locked(
        session, control, identity, payload, store.catalog, first
    )
    record = await propose_locked(session, scope, payload, expected, await db_clock(session))
    current = await read_strategy_transition_locked(
        session,
        control,
        scope,
        identity,
        payload,
        store.catalog,
        freshness,
        reader,
        credential=witness,
    )
    await require_transition_partition_locked(
        session, control, identity, payload, store.catalog, current
    )
    await finish_transition_locked(session, control, scope, identity, first, current)
    return record


async def approve_transition_locked(
    store: ManagementPlanStore,
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    record: PlanRevision,
    head: ManagementPlanHead,
    expected: UUID | None,
    credential: AuthenticatedWorkerIdentity | None,
) -> PlanRevision:
    # Keep one owner transaction's pre/post-staged-head proof and permanent writes cohesive.
    freshness, reader, witness = _transition_inputs(store, record.payload, identity, credential)
    first = await read_strategy_transition_locked(
        session,
        control,
        scope,
        identity,
        record.payload,
        store.catalog,
        freshness,
        reader,
        credential=witness,
    )
    await require_transition_partition_locked(
        session, control, identity, record.payload, store.catalog, first
    )
    replay = head.state == "approved" and head.current_revision_id == record.plan_revision_id
    if not replay:
        require_cas(head.current_revision_id, expected)
        if head.state == "revoked" and head.current_revision_id == record.plan_revision_id:
            raise ManagementDeniedError("A revoked plan needs an explicit new bounded revision")
        now = await db_clock(session)
        procedure = await ensure_procedure(
            session, store.directory, scope, identity, record.payload, now
        )
        decision = await decision_locked(session, scope, record, "approve", now)
        await consume_revision(session, scope, record, procedure, decision.decision_id, now)
        await register_children(
            session,
            store.directory,
            scope,
            identity,
            record.payload,
            record.plan_revision_id,
            first.admission.charters,
        )
        head.current_revision_id, head.state = record.plan_revision_id, "approved"
        head.procedure_id, head.decision_id = procedure.procedure_id, decision.decision_id
        await session.flush()
    current = await read_strategy_transition_locked(
        session,
        control,
        scope,
        identity,
        record.payload,
        store.catalog,
        freshness,
        reader,
        credential=witness,
    )
    await require_transition_partition_locked(
        session, control, identity, record.payload, store.catalog, current
    )
    await finish_transition_locked(session, control, scope, identity, first, current)
    return record

"""Same-session current qualification of one committed model intent, without reissuing it."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.actions import ActionProposal, ResourceRevision
from nexus.core.llm.company_adapter_contracts import CompanyModelRequest
from nexus.core.llm.company_pricing import CostQuote
from nexus.execution.effect_store import EffectStore
from nexus.execution.effect_support import effect_row, require_effect_authority
from nexus.execution.intent_checks import BeforeIntentCheck, FinalIntentTimeCheck
from nexus.execution.management_services import ManagementExecutionServices
from nexus.execution.runtime_contracts import EffectRecord, ExecutionLease
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import (
    db_now,
    execution_row,
    lease_scope,
    require_lease,
    runtime_transaction,
)
from nexus.harness.journal_models import CompanyControl, JournalAction
from nexus.harness.model_intent import ModelIntentCheck
from nexus.harness.model_managed_deadlines import (
    managed_model_deadlines,
    require_managed_model_time,
)


@dataclass(frozen=True, slots=True)
class ClaimedModelRequest:
    check: ModelIntentCheck
    effect: EffectRecord


@dataclass(frozen=True, slots=True)
class ModelPreSdkServices:
    factory: async_sessionmaker[AsyncSession]
    effects: EffectStore
    lease: ExecutionLease
    identity: VerifiedIdentity
    resources: tuple[ResourceRevision, ...]
    additional: BeforeIntentCheck | None
    management: ManagementExecutionServices | None = None


async def revalidate_before_sdk(
    services: ModelPreSdkServices,
    check: ModelIntentCheck,
    effect: EffectRecord,
    request: CompanyModelRequest,
    quote: CostQuote,
    eligibility_sha256: str | None,
) -> datetime:
    """Validate exact native issuance and all final clocks; dates alone never confer permission."""
    check.require_selection(request, quote, eligibility_sha256)
    scope = lease_scope(services.lease)
    async with runtime_transaction(services.factory, scope, services.identity) as (
        session,
        control,
        _,
    ):
        work = await execution_row(session, scope)
        action = await _current_native(session, control, work, services, request, effect)
        if services.additional is not None:
            await services.additional.validate(
                session, control, work, action, await db_now(session)
            )
        await check.revalidate_prepared(session, control, work, action, await db_now(session))
        await require_effect_authority(
            session,
            control,
            work,
            request.action_id,
            await db_now(session),
            services.resources,
            scope,
            services.identity,
        )
        snapshot = (
            await managed_model_deadlines(
                session, control, work, services.identity, services.management
            )
            if services.management is not None
            else None
        )
        final = await db_now(session)
        require_lease(work, services.lease, final, execute=True)
        check.require_prepared_time(final)
        if snapshot is not None and services.management is not None:
            require_managed_model_time(snapshot, services.management.catalog, final)
        if isinstance(services.additional, FinalIntentTimeCheck):
            services.additional.validate_time(final)
        return final


async def _current_native(
    session: AsyncSession,
    control: CompanyControl,
    work: ExecutionWork,
    services: ModelPreSdkServices,
    request: CompanyModelRequest,
    effect: EffectRecord,
) -> JournalAction:
    require_lease(work, services.lease, await db_now(session), execute=True)
    native = await effect_row(session, work, request.action_id)
    if (
        native.state != "intent"
        or native.receipt_json is not None
        or (native.intent_fence, native.attempt_kind, native.proposal_hash)
        != (effect.intent_fence, "model_requests", effect.proposal_hash)
        or native.intent_fence != services.lease.fence
    ):
        raise ValueError("Pre-SDK requires the exact still-unresolved native model intent")
    action = await require_effect_authority(
        session,
        control,
        work,
        request.action_id,
        await db_now(session),
        services.resources,
        lease_scope(services.lease),
        services.identity,
    )
    await services.effects.revalidate_execution_locked(
        session,
        control,
        work,
        services.identity,
        ActionProposal.model_validate_json(action.proposal_json),
        "model_requests",
    )
    return action

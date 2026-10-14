"""One registered engineering segment consumes actual native result and protected acceptance."""

from uuid import UUID

from nexus.builder.engineering_acceptance import EngineeringWorkAcceptanceStore
from nexus.builder.engineering_acceptance_recovery import EngineeringAcceptanceRecovery
from nexus.builder.engineering_pair_selection import resolve_pair
from nexus.company.management.acceptance import WorkAcceptance
from nexus.execution.engineering_worker_context import EngineeringContext
from nexus.execution.engineering_worker_contracts import (
    EngineeringSegmentResult,
    EngineeringStatus,
)
from nexus.execution.engineering_worker_observation import observe_acceptance, observe_published
from nexus.execution.engineering_worker_services import EngineeringWorkerServices
from nexus.execution.runtime_support import db_now, lease_scope, runtime_transaction


async def run_engineering_effect(
    services: EngineeringWorkerServices,
    context: EngineeringContext,
) -> EngineeringSegmentResult:
    """Existing runner owns the one-time effect permit; this adapter cannot issue directly."""
    result = await services.runner.run(
        context.lease, context.identity, context.action, context.spec, context.guard
    )
    if result is None or result.outcome == "outcome_unknown":
        return await observe_unknown(services, context)
    record = await services.runner.effects.get(
        context.guard.lease, context.identity, context.action.action_id
    )
    if record.receipt is None:
        return await observe_unknown(services, context)
    if record.receipt.outcome != "succeeded":
        return await observe_unknown(
            services, context, status="blocked", receipt_id=record.receipt.receipt_id
        )
    if context.phase == "author":
        return await observe_published(services, context, record.receipt)
    accepted = await verify_existing_pair(services, context)
    await services.observe("acceptance_recorded", context.command)
    return await observe_acceptance(services, context, record.receipt, accepted)


async def observe_unknown(
    services: EngineeringWorkerServices,
    context: EngineeringContext,
    *,
    status: EngineeringStatus = "outcome_unknown",
    receipt_id: UUID | None = None,
) -> EngineeringSegmentResult:
    """Unknown issuance remains unknown; no acceptance or new effect is inferred."""
    async with runtime_transaction(
        services.factory,
        lease_scope(context.guard.lease),
        context.identity,
        allow_paused=True,
        allow_inactive=True,
    ) as (session, _, _):
        return EngineeringSegmentResult(
            company_id=context.command.company_id,
            command=context.command,
            phase=context.phase,
            workflow_name="engineering.change"
            if context.phase == "author"
            else "engineering.verify",
            status=status,
            receipt_id=receipt_id,
            billing="unconfirmed",
            observed_at=await db_now(session),
        )


async def verify_existing_pair(
    services: EngineeringWorkerServices, context: EngineeringContext
) -> WorkAcceptance:
    """Recompute the registered proof with the current sealed actor credential."""
    if context.guard.lease.mode == "reconcile":
        recovery = EngineeringAcceptanceRecovery(
            services.factory,
            services.catalog,
            services.recovery.inputs,
            services.recovery.proof,
            credential=context.credential,
        )
        accepted = await recovery.reconcile_verified_result(
            context.guard.lease, context.identity, verifier_action_id=context.action.action_id
        )
    else:
        acceptance = EngineeringWorkAcceptanceStore(
            services.factory,
            services.catalog,
            services.acceptance.inputs,
            services.acceptance.proof,
            credential=context.credential,
        )
        async with runtime_transaction(
            services.factory, lease_scope(context.guard.lease), context.identity
        ) as (session, control, _):
            pair = await resolve_pair(
                session, control, context.guard.lease, verifier_action_id=context.action.action_id
            )
        proof = await acceptance.prepare_verified_result(
            context.guard.lease,
            context.identity,
            author_action_id=pair.author_action_id,
            verifier_action_id=pair.verifier_action_id,
        )
        await services.observe("proof_registered", context.command)
        accepted = await acceptance.publish_verified_result(
            context.guard.lease,
            context.identity,
            author_action_id=pair.author_action_id,
            verifier_action_id=pair.verifier_action_id,
            protected_result=proof,
        )
    return accepted

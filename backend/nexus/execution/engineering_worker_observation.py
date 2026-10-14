"""Current protected observations cannot make cached acceptance perpetual permission."""

from nexus.company.brain.access_support import require_resources
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.acceptance import WorkAcceptance
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_freshness import require_qualified_time
from nexus.company.management.acceptance_provenance import reference_sources
from nexus.company.management.acceptance_support import acceptance_scope
from nexus.execution.engineering_worker_context import EngineeringContext
from nexus.execution.engineering_worker_contracts import (
    EngineeringSegmentResult,
    accepted_segment_result,
)
from nexus.execution.engineering_worker_services import EngineeringWorkerServices
from nexus.execution.management_checks import current_accepted_work
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import (
    db_now,
    execution_row,
    lease_scope,
    require_lease,
    runtime_transaction,
)
from nexus.harness.journal_models import CostHold


async def observe_acceptance(
    services: EngineeringWorkerServices,
    context: EngineeringContext,
    receipt: ActionReceipt,
    acceptance: WorkAcceptance,
) -> EngineeringSegmentResult:
    """Current result evidence and final READ/lease dates precede the recorded observation."""
    scope = acceptance_scope(context.guard.lease, acceptance.target.action_id)
    refs = (*acceptance.target.artifacts, *(row.result_artifact for row in acceptance.proofs))
    async with runtime_transaction(
        services.factory, lease_scope(context.guard.lease), context.identity
    ) as (session, control, _):
        work = await execution_row(session, lease_scope(context.guard.lease))
        author = await session.get(
            ExecutionWork, (context.command.company_id, acceptance.target.author.task_id)
        )
        require_acceptance(author is not None)
        assert author is not None
        if acceptance.verdict == "pass":
            current = await current_accepted_work(
                session,
                control,
                work,
                author,
                context.identity,
                services.acceptance.inputs.reader,
                services.acceptance.inputs.freshness,
            )
            require_acceptance(current == acceptance)
        await services.acceptance.inputs.freshness.revalidate_references(
            session, scope, refs, await db_now(session)
        )
        source_ids, resources = await reference_sources(session, scope, refs)
        qualified = await services.acceptance.inputs.freshness._resolve(session, scope, source_ids)
        grants = await require_resources(session, scope, resources, await db_now(session))
        hold = await session.get(CostHold, context.action.action_id)
        final = await db_now(session)
        require_qualified_time(qualified, final)
        context.credential.require_time(final)
        require_lease(work, context.guard.lease, final)
        require_acceptance(all(row.expires_at is None or row.expires_at > final for row in grants))
        return accepted_segment_result(
            context.command,
            receipt,
            acceptance,
            billing="known" if hold is not None and hold.actual_usd is not None else "unconfirmed",
            observed_at=final,
        )


async def observe_published(
    services: EngineeringWorkerServices, context: EngineeringContext, receipt: ActionReceipt
) -> EngineeringSegmentResult:
    """Author publication remains a known receipt observation, distinct from acceptance."""
    async with runtime_transaction(
        services.factory, lease_scope(context.guard.lease), context.identity
    ) as (session, control, _):
        work = await execution_row(session, lease_scope(context.guard.lease))
        windows = await context.guard.disclosure_windows(session, control)
        hold = await session.get(CostHold, context.action.action_id)
        final = await db_now(session)
        context.credential.require_time(final)
        require_lease(work, context.guard.lease, final)
        require_acceptance(all(value > final for value in windows))
        return EngineeringSegmentResult(
            company_id=context.command.company_id,
            command=context.command,
            phase="author",
            workflow_name="engineering.change",
            status="published",
            receipt_id=receipt.receipt_id,
            billing="known" if hold is not None and hold.actual_usd is not None else "unconfirmed",
            observed_at=final,
        )

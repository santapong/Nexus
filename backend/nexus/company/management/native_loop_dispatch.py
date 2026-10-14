"""Just the fixed native task enters the existing signed-owner scheduler; no approvals here."""

from datetime import UTC, datetime

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.management.scheduling_contracts import (
    DueWake,
    EventWake,
    ScanRequest,
    ScheduledWork,
)
from nexus.company.management.scheduling_store import ManagementScheduler
from nexus.execution.runtime_contracts import ExecutionSnapshot
from nexus.harness.journal_contracts import ActionRecord


async def schedule_loop_action(
    scheduler: ManagementScheduler,
    observed_at: datetime,
    execution: ExecutionSnapshot,
    action: ActionRecord,
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    event: EventWake | None,
) -> ScheduledWork | None:
    """Select the exact task; current M1/source/cost/enqueue gates own admission."""
    request = ScanRequest(
        company_id=scope.company_id,
        wake=event or DueWake(bucket=observed_at.astimezone(UTC).replace(second=0, microsecond=0)),
        task_ids=(execution.registration.work.task_id,),
    )
    scanned = await scheduler.scan(scope, identity, request)
    return next(
        (
            row
            for row in scanned.receipt.work
            if row.action_id == action.proposal.action_id and row.dispatch != "none"
        ),
        None,
    )

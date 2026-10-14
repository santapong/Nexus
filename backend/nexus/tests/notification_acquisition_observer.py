"""TEST-only restarted helper observation delegates production acquisition and waits unchanged."""

import os
from datetime import datetime
from pathlib import Path

from sqlalchemy import text

from nexus.company.notifications.worker_guard import NotificationOperationGuard
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.notification_worker_services import NotificationDispatchWorkerServices
from nexus.execution.runtime_support import db_now, execution_row, runtime_transaction
from nexus.harness.journal_contracts import LedgerScope
from nexus.tests.notification_process_wrappers import append_process_marker


def install_notification_acquisition_observer(root: Path) -> None:
    """Observe the qualified live lease and delegated wait; no authority is manufactured."""
    # Cohesive instrumentation exception: both process-local wrappers share the
    # exact captured production methods and cannot alter admission or wait behavior.
    import nexus.execution.notification_lease_recovery as module

    original_prior, original_wait = module.prior_live_deadline, module.wait_prior

    async def prior(
        services: NotificationDispatchWorkerServices,
        scope: LedgerScope,
        credential: AuthenticatedWorkerIdentity,
        guard: NotificationOperationGuard,
        command: SegmentCommand,
    ) -> datetime | None:
        deadline = await original_prior(services, scope, credential, guard, command)
        if deadline is not None:
            async with runtime_transaction(
                services.reads.factory,
                scope,
                credential.identity,
                allow_paused=True,
                allow_inactive=True,
            ) as (session, control, _):
                work = await execution_row(session, scope)
                database = await session.scalar(text("SELECT current_database()"))
                now = await db_now(session)
                credential.require_time(now)
                guard.require_time(now)
                assert control.owner_id == credential.identity.principal_id
                assert work.segment_id == command.segment_id and work.lease_until == deadline
                record = {
                    "event": "live_prior_observed",
                    "pid": os.getpid(),
                    "new_worker_id": str(services.worker_id),
                    "database": database,
                    "command": command.model_dump(mode="json"),
                    "observed_at": now.isoformat(),
                    "deadline": deadline.isoformat(),
                    "still_live": deadline > now,
                    "prior_worker_id": str(work.worker_id),
                    "prior_fence": work.fence,
                    "actor_id": str(credential.identity.principal_id),
                    "workspace_id": str(credential.identity.workspace_id),
                    "current_member_scope_checked": True,
                }
            append_process_marker(root, "acquisition-observations.jsonl", record)
        return deadline

    async def waiting(seconds: float) -> None:
        append_process_marker(
            root,
            "acquisition-observations.jsonl",
            {"event": "acquisition_wait", "pid": os.getpid(), "seconds": seconds},
        )
        await original_wait(seconds)

    module.prior_live_deadline = prior
    module.wait_prior = waiting

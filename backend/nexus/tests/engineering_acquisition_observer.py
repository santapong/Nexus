"""Test-only observed acquisition entry delegates all native permission and wait behavior."""

import json
import os
from datetime import datetime
from pathlib import Path

from sqlalchemy import text

from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.engineering_worker_services import EngineeringWorkerServices
from nexus.execution.runtime_support import db_now, execution_row, runtime_transaction
from nexus.harness.journal_contracts import LedgerScope


def install_acquisition_observer(root: Path) -> None:
    """Record only actual successful prior-live preflight and the real subsequent wait."""
    import nexus.execution.engineering_lease_recovery as module

    original_prior, original_wait = module.prior_live_deadline, module.wait_prior

    async def prior(
        services: EngineeringWorkerServices,
        scope: LedgerScope,
        credential: AuthenticatedWorkerIdentity,
        command: SegmentCommand,
    ) -> datetime | None:
        deadline = await original_prior(services, scope, credential, command)
        if deadline is not None:
            async with runtime_transaction(
                services.factory, scope, credential.identity, allow_paused=True, allow_inactive=True
            ) as (session, _, _):
                work = await execution_row(session, scope)
                now = await db_now(session)
                database = await session.scalar(text("SELECT current_database()"))
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
            append(root, record)
        return deadline

    async def waiting(seconds: float) -> None:
        append(root, {"event": "acquisition_wait", "pid": os.getpid(), "seconds": seconds})
        await original_wait(seconds)

    module.prior_live_deadline = prior
    module.wait_prior = waiting


def append(root: Path, record: dict[str, object]) -> None:
    """Bound process-only metadata, never credentials or fabricated authority records."""
    path = root / "acquisition-observations.jsonl"
    if path.exists() and path.stat().st_size > 1048576:
        raise ValueError("Acquisition test observation exceeds bound")
    raw = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
    with path.open("a") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    path.chmod(0o600)

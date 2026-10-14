"""Recover only an expired unissued preparation lease into an actual pending approval wait."""

from datetime import datetime

from nexus.company.management.native_profile_admission import ledger_scope
from nexus.company.management.plans import RunBinding
from nexus.execution.native_report_services import NativeReportServices
from nexus.execution.runtime_contracts import ExecutionDeniedError, ExecutionSnapshot
from nexus.harness.journal_contracts import ActionRecord


async def release_preparation_capacity(
    native: NativeReportServices,
    binding: RunBinding,
    current: ExecutionSnapshot,
    action: ActionRecord,
    observed_at: datetime,
) -> bool:
    """A live peer lease is untouched; expired unissued work gets a fresh guarded lease/wait."""
    if current.worker_id is None:
        return True
    if current.expires_at is None:
        raise ExecutionDeniedError("Preparation lease deadline is unavailable")
    if current.expires_at > observed_at:
        return False
    identity = native.identities.actor(binding)
    lease = await native.execution.claim(
        ledger_scope(binding), identity, native.worker_id, ttl_seconds=native.lease_ttl_seconds
    )
    try:
        await native.execution.await_approval(lease, identity, action.proposal.action_id)
    except ValueError:
        await native.execution.release(lease, identity)
        raise
    return True

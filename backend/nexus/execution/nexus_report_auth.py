"""One finite original report credential/claim, with actual pending leaf ownership."""

import asyncio
from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import cast

from nexus.builder.contained_query import clock_us
from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.plans import RunBinding
from nexus.company.notifications.worker_identity import (
    AuthenticatedWorkerIdentity,
    NotificationWorkerIdentities,
)
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.native_report_context import NativeReportContext
from nexus.execution.native_report_services import NativeReportServices
from nexus.execution.runtime_contracts import ExecutionDeniedError, ExecutionLease
from nexus.harness.journal_contracts import LedgerScope


def _current(end: int) -> None:
    if clock_us() >= end:
        raise ExecutionDeniedError("Nexus report original context window expired")


def _track[T](services: NativeReportServices, call: Coroutine[None, None, T]) -> asyncio.Task[T]:
    services._nexus_owners[:] = list(services.pending_owners())
    task = asyncio.create_task(call)
    services._nexus_owners.append(cast(asyncio.Task[object], task))
    task.add_done_callback(lambda value: None if value.cancelled() else value.exception())
    return task


async def _await[T](task: asyncio.Task[T], end: int) -> T:
    _current(end)
    async with asyncio.timeout(max(0, end - clock_us()) / 1_000_000):
        value = await asyncio.shield(task)
    _current(end)
    return value


async def _retire(
    services: NativeReportServices,
    task: asyncio.Task[ExecutionLease],
    identity: VerifiedIdentity,
    witness: AuthenticatedWorkerIdentity,
    end_us: int,
) -> None:
    try:
        lease = await asyncio.shield(task)
        _current(end_us)
        now = datetime.now(UTC)
        witness.require_time(now)
        if lease.expires_at <= now or lease.expires_at > witness.expires_at:
            return
        release = _track(services, services.execution.release(lease, identity))
        await asyncio.shield(release)
    except BaseException:
        # No new native call/retry/ordinary adoption; actual leaf remains separately tracked.
        return


async def acquire_nexus_report(
    services: NativeReportServices,
    command: SegmentCommand,
    action: ActionProposal,
    identity: VerifiedIdentity,
    binding: RunBinding,
    scope: LedgerScope,
) -> NativeReportContext:
    original_end = clock_us() + services.lease_ttl_seconds * 1_000_000
    mapping = services.report_credentials
    matches = tuple(source for selected, source in mapping if selected == binding)
    if len(matches) != 1 or type(matches[0]) is not NotificationWorkerIdentities:
        raise ExecutionDeniedError("Nexus report requires its configured actual actor credential")
    provider = matches[0]
    read = _track(services, provider.current(binding))
    try:
        witness = await _await(read, original_end)
    except BaseException as error:
        error.__dict__["_nexus_native_report_pending"] = services.pending_owners()
        raise
    observed_mono = clock_us()
    now = datetime.now(UTC)
    witness.require_time(now)
    original_end = min(
        original_end, observed_mono + int((witness.expires_at - now).total_seconds() * 1_000_000)
    )
    if witness.identity != identity or services.report_credentials is not mapping:
        raise ExecutionDeniedError("Nexus report actor/provider binding changed")
    ttl = min(
        services.lease_ttl_seconds,
        int((witness.expires_at - now).total_seconds()),
        int((original_end - clock_us()) / 1_000_000),
    )
    if ttl < 1:
        raise ExecutionDeniedError("Nexus report has no original credential/lease headroom")
    claim = _track(
        services,
        services.execution.recover_dispatched(
            scope, identity, services.worker_id, command.segment_id, ttl_seconds=ttl
        ),
    )
    try:
        lease = await _await(claim, original_end)
        witness.require_time(datetime.now(UTC))
        if (
            lease.expires_at > witness.expires_at
            or lease.mode != "execute"
            or services.report_credentials is not mapping
            or matches[0] is not provider
        ):
            raise ExecutionDeniedError("Nexus report actual lease exceeds its original credential")
    except BaseException as error:
        _track(services, _retire(services, claim, identity, witness, original_end))
        error.__dict__["_nexus_native_report_pending"] = services.pending_owners()
        raise
    return NativeReportContext(
        services, command, action, identity, lease, witness, provider, original_end
    )

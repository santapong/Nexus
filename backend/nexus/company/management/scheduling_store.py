"""Deterministic native scans, dispatch and cursor acknowledgment commit together."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.management.control_support import db_clock
from nexus.company.management.scheduling_contracts import (
    ScanPage,
    ScanReceipt,
    ScanRequest,
    ScanResult,
    ScheduledWork,
    SchedulerPolicy,
    request_sha256,
)
from nexus.company.management.scheduling_cursors import ScanWindow, event_key, scan_window
from nexus.company.management.scheduling_models import ManagementSchedulerScan
from nexus.company.management.scheduling_projection import task_page
from nexus.company.management.scheduling_queue import enqueue_candidate
from nexus.company.management.scheduling_reads import inspect_task
from nexus.company.management.scheduling_support import SchedulerServices
from nexus.company.management.transactions import (
    ManagementDeniedError,
    management_owner_transaction,
)
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.journal_models import CompanyControl


def _record(row: ManagementSchedulerScan) -> ScanReceipt:
    record = ScanReceipt.model_validate_json(row.result_json)
    if (
        record.company_id,
        record.scan_id,
        record.consumer,
        record.recipe_version,
        record.event_key,
        record.request_sha256,
        record.owner_id,
        record.operation_id,
        record.trace_id,
        record.recorded_at,
        record.start_brain_sequence,
        record.end_brain_sequence,
        record.start_control_sequence,
        record.end_control_sequence,
        record.due_bucket,
    ) != (
        row.company_id,
        row.scan_id,
        row.consumer,
        row.recipe_version,
        row.event_key,
        row.request_sha256,
        row.owner_id,
        row.operation_id,
        row.trace_id,
        row.recorded_at,
        row.start_brain_sequence,
        row.end_brain_sequence,
        row.start_control_sequence,
        row.end_control_sequence,
        row.due_bucket,
    ):
        raise ManagementDeniedError("Stored scheduler receipt differs from its native record")
    return record


async def _prior(
    session: AsyncSession, company_id: UUID, policy: SchedulerPolicy, key: str, digest: str
) -> ScanReceipt | None:
    row = await session.scalar(
        select(ManagementSchedulerScan).where(
            ManagementSchedulerScan.company_id == company_id,
            ManagementSchedulerScan.consumer == policy.consumer,
            ManagementSchedulerScan.recipe_version == policy.recipe_version,
            ManagementSchedulerScan.event_key == key,
        )
    )
    if row is None:
        return None
    if row.request_sha256 != digest:
        raise ManagementDeniedError("Scheduler trigger identity cannot be rebound")
    return _record(row)


class ManagementScheduler:
    """No model/prepared-action factory or polling loop belongs in this service."""

    def __init__(
        self, factory: async_sessionmaker[AsyncSession], services: SchedulerServices
    ) -> None:
        self.factory, self.services = factory, services
        self.policy = SchedulerPolicy.model_validate_json(services.policy.model_dump_json())

    async def scan(
        self, scope: CompanyControlScope, identity: VerifiedIdentity, request: ScanRequest
    ) -> ScanResult:
        """Current owner reads and enqueue/cursor writes share one CompanyControl transaction."""
        request = ScanRequest.model_validate_json(request.model_dump_json())
        if (
            scope.company_id != request.company_id
            or self.services.catalog.company_id != scope.company_id
        ):
            raise ManagementDeniedError("Scheduler company is unavailable")
        digest = request_sha256(request)
        async with management_owner_transaction(
            self.factory, scope, identity, allow_paused=True
        ) as (
            session,
            control,
            _,
        ):
            key = await event_key(session, scope.company_id, request, digest)
            prior = await _prior(session, scope.company_id, self.policy, key, digest)
            if prior is not None:
                return ScanResult(receipt=prior, replayed=True)
            window = await scan_window(
                session,
                scope.company_id,
                request,
                self.policy.recipe_version,
                key,
                await db_clock(session),
            )
            record = await self._scan_current(
                session, control, scope, identity, request, digest, window
            )
            await _save(session, record)
            if record.next_page is None:
                window.brain.last_sequence, window.control.last_sequence = (
                    window.brain_end,
                    window.control_end,
                )
            await session.flush()
            return ScanResult(receipt=record, replayed=False)

    async def _scan_current(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        request: ScanRequest,
        digest: str,
        window: ScanWindow,
    ) -> ScanReceipt:
        rows, truncated = await task_page(session, scope.company_id, request, self.policy.max_tasks)
        work = []
        for row in rows:
            candidate = await inspect_task(session, control, row, identity, self.services)
            work.append(
                await enqueue_candidate(session, control, candidate, self.services)
                if candidate.projection.eligibility.state == "eligible"
                else candidate.projection
            )
        return _receipt(
            scope,
            control,
            request,
            self.policy,
            digest,
            window,
            rows,
            truncated,
            tuple(work),
            await db_clock(session),
        )


async def _save(session: AsyncSession, record: ScanReceipt) -> None:
    session.add(
        ManagementSchedulerScan(
            company_id=record.company_id,
            scan_id=record.scan_id,
            consumer=record.consumer,
            recipe_version=record.recipe_version,
            event_key=record.event_key,
            request_sha256=record.request_sha256,
            result_json=record.model_dump_json(),
            owner_id=record.owner_id,
            operation_id=record.operation_id,
            trace_id=record.trace_id,
            recorded_at=record.recorded_at,
            start_brain_sequence=record.start_brain_sequence,
            end_brain_sequence=record.end_brain_sequence,
            start_control_sequence=record.start_control_sequence,
            end_control_sequence=record.end_control_sequence,
            due_bucket=record.due_bucket,
        )
    )
    await session.flush()


def _receipt(
    scope: CompanyControlScope,
    control: CompanyControl,
    request: ScanRequest,
    policy: SchedulerPolicy,
    digest: str,
    window: ScanWindow,
    rows: tuple[ExecutionWork, ...],
    truncated: bool,
    work: tuple[ScheduledWork, ...],
    now: datetime,
) -> ScanReceipt:
    next_page = (
        ScanPage(
            after_task_id=rows[-1].task_id,
            brain_sequence=window.brain_end,
            control_sequence=window.control_end,
            plan_snapshot_sha256=window.plan_sha256,
        )
        if truncated
        else None
    )
    return ScanReceipt(
        company_id=scope.company_id,
        scan_id=uuid5(scope.company_id, window.event_key),
        consumer=policy.consumer,
        recipe_version=policy.recipe_version,
        event_key=window.event_key,
        request_sha256=digest,
        request=request,
        owner_id=control.owner_id,
        operation_id=scope.operation_id,
        trace_id=scope.trace_id,
        recorded_at=now,
        start_brain_sequence=window.brain.last_sequence,
        end_brain_sequence=window.brain_end,
        start_control_sequence=window.control.last_sequence,
        end_control_sequence=window.control_end,
        due_bucket=window.due_bucket,
        work=work,
        next_page=next_page,
    )

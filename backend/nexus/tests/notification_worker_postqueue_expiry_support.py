"""TEST-only public deadlines and real same-session post-SQL observation/wait; no clock edits."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange
from nexus.company.brain.access_models import BrainResource
from nexus.company.contracts.actions import ApprovalDecision
from nexus.company.management.base import ValueContract
from nexus.company.management.native_profile_admission import ledger_scope
from nexus.company.management.scheduling_contracts import ScheduledWork
from nexus.company.management.scheduling_queue import enqueue_candidate
from nexus.company.management.scheduling_support import SchedulerServices, SchedulingCandidate
from nexus.company.management.transactions import management_owner_transaction
from nexus.company.notifications import worker_enqueue
from nexus.company.notifications.dispatch_models import NotificationDispatchRow
from nexus.company.notifications.draft_models import NotificationDraftRow
from nexus.company.notifications.draft_store import owner_scope
from nexus.company.notifications.observation_models import NotificationObservationRow
from nexus.company.notifications.worker_identity import (
    AuthenticatedWorkerIdentity,
    NotificationWorkerIdentities,
)
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.dispatch_models import SegmentDispatch
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt, ExecutionWork
from nexus.execution.runtime_support import db_now
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_models import CompanyControl, CostHold, JournalAction
from nexus.tests.integration.test_company_directory import control
from nexus.tests.notification_worker_credential_fixture import TEST_KEY
from nexus.tests.notification_worker_enqueue_pg_fixture import AtomicNotificationDatabases
from nexus.tests.notification_worker_postqueue_fixture import StagedAtomicCase
from nexus.tests.notification_worker_tick_services_fixture import SyntheticTickCredential


class UnissuedLedger(ValueContract):
    """Trusted fixture metadata only; no message bodies, credentials or granted authority."""

    action_state: str
    consumed_at: datetime | None
    approval_sha256: str
    approval_issued_at: datetime
    approval_expires_at: datetime
    action_sha256: str
    draft_identity: tuple[UUID, str, str]
    reservations: tuple[int, int, int]
    effects: tuple[int, ...]
    counters: tuple[tuple[UUID, int, int], ...]
    source_action_state: str
    source_action_sha256: str


class PostQueueCapture(ValueContract):
    """Actual uncommitted SQL/native rows and clock crossing; not a reusable permit."""

    command: SegmentCommand
    before: datetime
    expiry: datetime
    after: datetime
    action_state: str
    consumed_at: datetime | None
    hold: tuple[str, str | None, str]
    queue_status: str
    canonical_binding: bool


async def deadline_case(
    case: StagedAtomicCase,
    boundary: str,
) -> tuple[AuthenticatedWorkerIdentity, datetime]:
    """Create one genuine original deadline and public owner decision after source staging."""
    binding = case.snapshot.value.registration.sender
    witness = case.credential
    async with management_owner_transaction(
        case.services.reads.factory, control(), witness.identity
    ) as (session, _, _):
        now = await db_now(session)
    if boundary == "sender_read":
        expiry = await finite_sender_read(case)
    elif boundary == "credential":
        witness = await short_signed_credential(case)
        expiry = witness.expires_at
    else:
        assert boundary == "approval"
        expiry = now + timedelta(seconds=10)
    journal, scope = CompanyJournal(case.services.reads.factory), ledger_scope(binding)
    record = await journal.get_action(scope, case.action_id)
    assert record.approval is None and record.consumed_at is None
    issued = now - timedelta(hours=24) + timedelta(seconds=10) if boundary == "approval" else now
    approved = await journal.approve_registered(
        scope,
        case.action_id,
        record.proposal_hash,
        issued,
        identity=witness.identity,
    )
    assert approved.approval is not None and approved.consumed_at is None
    if boundary == "approval":
        assert approved.approval.expires_at == expiry and approved.approval.issued_at == issued
    return witness, expiry


async def finite_sender_read(case: StagedAtomicCase) -> datetime:
    """Set only the actual target OWNER READ expiry via public current ACL CAS."""
    reads, witness = case.services.reads, case.credential
    target = reads.preparation.policy.target
    async with management_owner_transaction(reads.factory, control(), witness.identity) as (
        session,
        _,
        _,
    ):
        resource = await session.get(BrainResource, (target.company_id, target.resource_id))
        assert resource is not None
        generation = resource.acl_generation
        expiry = await db_now(session) + timedelta(seconds=10)
    actual = await ResourceAccessStore(reads.factory).change(
        owner_scope(control(), witness.identity),
        witness.identity,
        ResourceAccessChange(
            company_id=target.company_id,
            resource=target,
            principal_id=witness.identity.principal_id,
            active=True,
            expires_at=expiry,
            expected_generation=generation,
        ),
    )
    assert actual.active and actual.expires_at == expiry
    return expiry


async def short_signed_credential(case: StagedAtomicCase) -> AuthenticatedWorkerIdentity:
    """Only test code signs a10s token; actual verifier supplies the sealed witness."""
    binding = case.snapshot.value.registration.sender
    now = int(datetime.now(UTC).timestamp())
    token = jwt.encode(
        {
            "sub": str(binding.actor_id),
            "workspace_id": str(binding.workspace_id),
            "iat": now - 1,
            "exp": now + 10,
        },
        TEST_KEY,
        algorithm="HS256",
    )
    identities = NotificationWorkerIdentities(
        SyntheticTickCredential(SecretStr(token)),
        SecretStr(TEST_KEY),
        enabled=True,
    )
    return await identities.current(expected_binding=binding)


async def native_unissued_ledger(
    databases: AtomicNotificationDatabases,
    case: StagedAtomicCase,
) -> UnissuedLedger:
    """Read safe native rollback metadata through the current fixture owner without a body."""
    # Cohesive >50-line read-only fixture snapshot: one owner/native view and
    # separate DBOS count jointly describe the before/after rollback evidence.
    async with management_owner_transaction(databases.app, control(), case.credential.identity) as (
        session,
        _,
        _,
    ):
        row = await session.get(JournalAction, case.action_id)
        source = await session.get(JournalAction, case.source_action_id)
        draft = await session.get(
            NotificationDraftRow, (case.selection.company_id, case.selection.draft_id)
        )
        assert (
            row is not None
            and source is not None
            and draft is not None
            and row.approval_json is not None
        )
        hold = await session.scalar(select(func.count()).select_from(CostHold))
        dispatch = await session.scalar(select(func.count()).select_from(SegmentDispatch))
        assert hold is not None and dispatch is not None
        effects = []
        for model in (
            EffectIntent,
            ExecutionAttempt,
            NotificationDispatchRow,
            NotificationObservationRow,
        ):
            count = await session.scalar(select(func.count()).select_from(model))
            assert count is not None
            effects.append(count)
        works = tuple(
            (await session.scalars(select(ExecutionWork).order_by(ExecutionWork.task_id))).all()
        )
        counters = tuple((w.task_id, w.model_requests_used, w.tool_attempts_used) for w in works)
    async with databases.admin() as session:
        queued = await session.scalar(text("SELECT count(*) FROM dbos.workflow_status"))
        assert isinstance(queued, int)
    approval = ApprovalDecision.model_validate_json(row.approval_json)
    return UnissuedLedger(
        action_state=row.state,
        consumed_at=row.consumed_at,
        approval_sha256=hashlib.sha256(row.approval_json.encode()).hexdigest(),
        approval_issued_at=approval.issued_at,
        approval_expires_at=approval.expires_at,
        action_sha256=hashlib.sha256(row.proposal_json.encode()).hexdigest(),
        draft_identity=(draft.draft_id, draft.record_sha256, draft.payload_sha256),
        reservations=(hold, dispatch, queued),
        effects=tuple(effects),
        counters=counters,
        source_action_state=source.state,
        source_action_sha256=hashlib.sha256(source.proposal_json.encode()).hexdigest(),
    )


async def observed_sql(
    session: AsyncSession,
    case: StagedAtomicCase,
    result: ScheduledWork,
) -> tuple[SegmentCommand, str, datetime | None, tuple[str, str | None, str], str, bool]:
    """Read actual newly reserved and canonical enqueued state before the final nominated clock."""
    # Cohesive >50-line test observation exception: actual action/hold/dispatch
    # and complete queue/input pins must all precede the nominated before-clock.
    row = await session.get(JournalAction, case.action_id)
    hold = await session.get(CostHold, case.action_id)
    dispatch = await session.get(SegmentDispatch, (case.selection.company_id, case.action_id))
    assert row is not None and hold is not None and dispatch is not None
    assert row.state == "authorized" and row.consumed_at is not None
    assert hold.state == "held" and str(hold.amount_usd) == "0.010000" and hold.actual_usd is None
    command = SegmentCommand.model_validate_json(dispatch.binding_json)
    assert command.workflow_id == result.workflow_id and command.action_id == case.action_id
    saved = (
        (
            await session.execute(
                text(
                    "SELECT ws.name,ws.queue_name,ws.application_version,ws.application_name,"
                    "ws.serialization,ws.status,wi.inputs FROM dbos.workflow_status ws "
                    "JOIN dbos.workflow_input wi ON wi.workflow_uuid=ws.workflow_uuid "
                    "WHERE ws.workflow_uuid=:workflow_id"
                ),
                {"workflow_id": command.workflow_id},
            )
        )
        .mappings()
        .one()
    )
    registered = case.services.scheduler.policy.workflows[0]
    canonical = (
        saved["name"],
        saved["queue_name"],
        saved["application_version"],
        saved["application_name"],
        saved["serialization"],
    ) == (
        registered.workflow_name,
        registered.queue_name,
        registered.workflow_version,
        registered.application_name,
        "portable_json",
    ) and json.loads(saved["inputs"]) == {
        "positionalArgs": [command.model_dump_json()],
        "namedArgs": {},
    }
    assert saved["status"] == "ENQUEUED" and canonical
    return (
        command,
        row.state,
        row.consumed_at,
        (str(hold.amount_usd), None, hold.state),
        saved["status"],
        canonical,
    )


def observe_sql_then_cross_deadline(
    monkeypatch: pytest.MonkeyPatch,
    case: StagedAtomicCase,
    expiry: datetime,
    captures: list[PostQueueCapture],
) -> None:
    """Delegate unchanged public queue SQL, observe real rows, then cross an original deadline."""
    original = enqueue_candidate
    assert vars(worker_enqueue)["enqueue_candidate"] is original

    async def delayed(
        session: AsyncSession,
        control: CompanyControl,
        candidate: SchedulingCandidate,
        services: SchedulerServices,
    ) -> ScheduledWork:
        assert not captures
        result = await original(session, control, candidate, services)
        assert isinstance(result, ScheduledWork)
        command, state, consumed, hold, status, canonical = await observed_sql(
            session, case, result
        )
        before = await db_now(session)
        remaining = (expiry - before).total_seconds()
        assert 0 < remaining <= 15
        await asyncio.sleep(remaining + 0.04)
        after = await db_now(session)
        assert after >= expiry
        captures.append(
            PostQueueCapture(
                command=command,
                before=before,
                expiry=expiry,
                after=after,
                action_state=state,
                consumed_at=consumed,
                hold=hold,
                queue_status=status,
                canonical_binding=canonical,
            )
        )
        return result

    monkeypatch.setattr(worker_enqueue, "enqueue_candidate", delayed)

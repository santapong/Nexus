"""Actual M1 intent integration checks with schema-only notification row envelopes."""

from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.notifications.notification_models import (
    NotificationDispatchRow,
    NotificationDraftRow,
)
from nexus.execution.intent_checks import BeforeIntentCheck
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.canonical import action_hash
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_models import CompanyControl, JournalAction
from nexus.tests.generated_artifact_fixture import ledger
from nexus.tests.integration.test_company_directory import OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.native_profile_support import ProfileScenario, configured_profile


async def authorized_schema_work(
    factory: async_sessionmaker[AsyncSession], root: Path
) -> tuple[ProfileScenario, ExecutionLease, UUID]:
    case = await configured_profile(factory, root)
    profile = await case.preparation.resolve_profile(
        control(), identity(OWNER), case.report_id, case.commitment_id, case.evidence_ids
    )
    pending = await case.preparation.prepare_author(profile.reference)
    bound = case.payload.children[0].binding
    scope = ledger(bound)
    journal = CompanyJournal(factory)
    await journal.approve_registered(
        scope.model_copy(update={"principal_id": OWNER}),
        pending.action.proposal.action_id,
        action_hash(pending.action.proposal),
        datetime.now(ZoneInfo("UTC")),
        identity=identity(OWNER),
    )
    await journal.authorize_registered(
        scope,
        pending.action.proposal.action_id,
        datetime.now(ZoneInfo("UTC")),
        (),
        identity=identity(bound.actor_id),
    )
    lease = await case.native.execution.claim(scope, identity(bound.actor_id), uuid4())
    return case, lease, pending.action.proposal.action_id


class SchemaBinding(BeforeIntentCheck):
    """This trusted test hook binds actual native tuple; no transport or notification claim."""

    def __init__(self, draft: NotificationDraftRow, *, mismatch: str | None = None) -> None:
        self.draft, self.mismatch = draft, mismatch

    async def validate(
        self,
        session: AsyncSession,
        control: CompanyControl,
        work: ExecutionWork,
        action: JournalAction,
        now: datetime,
    ) -> None:
        row = NotificationDispatchRow(
            company_id=work.company_id,
            draft_id=self.draft.draft_id,
            action_id=action.id,
            task_id=work.task_id,
            trace_id=work.trace_id,
            run_id=work.run_id,
            intent_fence=work.fence,
            attempt_kind="tool_attempts",
            proposal_sha256=action.proposal_hash,
            registration_sha256=work.registration_hash,
            payload_sha256=self.draft.payload_sha256,
            recipient_policy_sha256=self.draft.recipient_policy_sha256,
            idempotency_key=f"nexus-owner-{work.company_id.hex}-{self.draft.draft_id.hex}",
            kind="routine",
            bangkok_day=now.astimezone(ZoneInfo("Asia/Bangkok")).date(),
            issued_at=now,
            issued_by=work.actor_id,
            operation_id=uuid4(),
            audit_trace_id=uuid4(),
        )
        if self.mismatch == "trace":
            row.trace_id = uuid4()
        elif self.mismatch == "fence":
            row.intent_fence += 1
        elif self.mismatch == "proposal":
            row.proposal_sha256 = "f" * 64
        elif self.mismatch == "kind":
            row.attempt_kind = "model_requests"
        session.add(row)
        await session.flush()

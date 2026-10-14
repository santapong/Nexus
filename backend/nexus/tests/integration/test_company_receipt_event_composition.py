"""Actual native composition wires receipt events without an optional fixture-side swap."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.event_models import BrainEvent
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.transactions import management_owner_transaction
from nexus.harness.canonical import action_hash
from nexus.harness.journal import CompanyJournal
from nexus.tests.generated_artifact_fixture import ledger
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.native_profile_support import configured_profile
from nexus.tests.receipt_event_support import receipt_factory as receipt_factory


async def test_native_report_composition_records_a_failed_issued_action_event(
    receipt_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    # Keep this51-line public composition/approval/issue/receipt sequence together
    # so the test cannot substitute an independently configured fixture effect store.
    case = await configured_profile(receipt_factory, tmp_path)
    profile = await case.preparation.resolve_profile(
        control(), identity(OWNER), case.report_id, case.commitment_id, case.evidence_ids
    )
    prepared = await case.preparation.prepare_author(profile.reference)
    action = prepared.action.proposal
    actor, actor_scope = identity(action.actor_id), ledger(profile.selection.author)
    journal = CompanyJournal(receipt_factory)
    await journal.approve_registered(
        actor_scope.model_copy(update={"principal_id": OWNER}),
        action.action_id,
        action_hash(action),
        datetime.now(UTC),
        identity=identity(OWNER),
    )
    await journal.authorize_registered(
        actor_scope, action.action_id, datetime.now(UTC), (), identity=actor
    )
    lease = await case.native.execution.claim(actor_scope, actor, uuid4())
    assert (await case.native.effects.begin(lease, actor, action.action_id)).permit_external_call
    receipt = ActionReceipt(
        company_id=COMPANY,
        receipt_id=uuid4(),
        action_id=action.action_id,
        task_id=action.task_id,
        trace_id=action.trace_id,
        proposal_hash=action_hash(action),
        outcome="failed",
        recorded_at=datetime.now(UTC),
        artifacts=(),
    )
    assert (await case.native.effects.record_receipt(lease, actor, receipt)).state == "failed"
    async with management_owner_transaction(receipt_factory, control(), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        assert (
            await session.scalar(
                select(func.count())
                .select_from(BrainEvent)
                .where(
                    BrainEvent.kind == "receipt_recorded",
                    BrainEvent.action_id == action.action_id,
                )
            )
            == 1
        )

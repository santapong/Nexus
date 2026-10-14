"""Author completion must be actual before one distinct verifier action can be prepared."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.generated_artifact_scope import generated_scope
from nexus.company.management.native_profile_contracts import NativeReportOperatingProfile
from nexus.harness.canonical import action_hash
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_models import JournalAction
from nexus.tests.generated_artifact_fixture import ledger
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_management_acceptance import saved_m1
from nexus.tests.native_profile_support import ProfileScenario, configured_profile
from nexus.tests.native_profile_support import profile_factory as profile_factory


async def publish_author(
    case: ProfileScenario, factory: async_sessionmaker[AsyncSession]
) -> tuple[NativeReportOperatingProfile, ActionProposal]:
    profile = await case.preparation.resolve_profile(
        control(), identity(OWNER), case.report_id, case.commitment_id, case.evidence_ids
    )
    prepared = await case.preparation.prepare_author(profile.reference)
    action = prepared.action.proposal
    author = case.payload.children[0].binding
    journal = CompanyJournal(factory)
    await journal.approve_registered(
        ledger(author).model_copy(update={"principal_id": OWNER}),
        action.action_id,
        action_hash(action),
        datetime.now(UTC),
        identity=identity(OWNER),
    )
    await journal.authorize_registered(
        ledger(author), action.action_id, datetime.now(UTC), (), identity=identity(author.actor_id)
    )
    lease = await case.native.execution.claim(ledger(author), identity(author.actor_id), uuid4())
    payload = await case.native.producer.prepare_report(
        generated_scope(lease, action.action_id),
        identity(author.actor_id),
        case.report_id,
        case.evidence_ids,
    )
    await case.native.effects.begin(lease, identity(author.actor_id), action.action_id)
    output = await case.native.publisher.publish(
        lease, identity(author.actor_id), action.action_id, payload
    )
    receipt = ActionReceipt(
        company_id=COMPANY,
        receipt_id=uuid4(),
        action_id=action.action_id,
        task_id=author.task_id,
        trace_id=author.trace_id,
        proposal_hash=action_hash(action),
        outcome="succeeded",
        recorded_at=datetime.now(UTC),
        artifacts=(
            ArtifactRef(
                company_id=COMPANY,
                artifact_id=output.artifact_id,
                reference="protected:native-author",
                revision=output.revision,
                sha256=output.sha256,
            ),
        ),
    )
    await case.native.effects.record_receipt(
        lease, identity(author.actor_id), receipt, actual_usd=Decimal(0)
    )
    await case.native.execution.release(lease, identity(author.actor_id))
    return profile, action


async def test_actual_author_receipt_prepares_exact_independent_verifier_without_second_effect(
    profile_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    case = await configured_profile(profile_factory, tmp_path)
    profile, action = await publish_author(case, profile_factory)
    verifier = case.payload.children[1].binding
    lease = await case.native.execution.claim(
        ledger(verifier), identity(verifier.actor_id), uuid4()
    )
    before = await saved_m1(profile_factory)
    pending = await case.preparation.prepare_verifier(profile.reference, lease, action.action_id)
    assert pending.phase == "verifier" and pending.action.approval is None
    assert (
        pending.action.proposal.actor_id == verifier.actor_id != profile.selection.author.actor_id
    )
    assert (
        await case.preparation.prepare_verifier(profile.reference, lease, action.action_id)
        == pending
    )
    assert await saved_m1(profile_factory) == before
    async with profile_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.scalar(select(func.count()).select_from(JournalAction)) == 2


async def test_execute_lease_alone_cannot_replace_missing_actual_author_receipt(
    profile_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    case = await configured_profile(profile_factory, tmp_path)
    profile = await case.preparation.resolve_profile(
        control(), identity(OWNER), case.report_id, case.commitment_id, case.evidence_ids
    )
    await case.preparation.prepare_author(profile.reference)
    verifier = case.payload.children[1].binding
    # Real native guard itself denies verifier execution before a known author result.
    with pytest.raises(ValueError):
        await case.native.execution.claim(ledger(verifier), identity(verifier.actor_id), uuid4())
    async with profile_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.scalar(select(func.count()).select_from(JournalAction)) == 1

"""Exclusive native_events015 qualified drafts; synthetic recipient, no sender or transport."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.events import OutboxEvent
from nexus.company.brain.native_fact_contracts import DecisionSelector, RegisteredDigestPolicy
from nexus.company.brain.native_fact_emitter import NativeFactEmitter
from nexus.company.brain.native_fact_reader import NativeFactReader
from nexus.company.notifications.contracts import NotificationPolicy, OwnerRecipientPolicy
from nexus.company.notifications.native_loader import NativeNotificationFactLoader
from nexus.company.notifications.qualified_adapter import QualifiedNotificationFactAdapter
from nexus.company.notifications.qualified_store import QualifiedNotificationDraftStore
from nexus.company.notifications.recipient_registry import (
    FileOwnerRecipients,
    RecipientRegistryFile,
)
from nexus.tests.integration.test_company_brain_ingestion import owner_scope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.native_fact_fixture import configured_facts
from nexus.tests.native_profile_support import ProfileScenario


async def configured_qualified(
    factory: async_sessionmaker[AsyncSession],
    root: Path,
    *,
    digest_kind: Literal["daily", "weekly"] = "weekly",
) -> tuple[QualifiedNotificationDraftStore, ProfileScenario, Path]:
    services, case = await configured_facts(factory, root)
    now = datetime.now(UTC)
    policy = NotificationPolicy(enabled=True, daily_digest=True, weekly_digest=True)
    registration = RegisteredDigestPolicy(
        company_id=COMPANY,
        schedule=f"qualified-{digest_kind}-v1",
        kind=digest_kind,
        report_id=case.report_id,
        policy=policy,
        resource=services.resource,
        registered_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
    )
    reader = NativeFactReader(replace(services, digests=(registration,)))
    legacy = NativeNotificationFactLoader(services.catalog, services.artifacts, services.freshness)
    path = root / "synthetic-qualified-owner-recipient.json"
    recipient = OwnerRecipientPolicy(
        company_id=COMPANY,
        owner_id=OWNER,
        policy_id=OWNER,
        version="qualified-only.v1",
        sender="system@example.invalid",
        recipient="owner@example.invalid",
        registered_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
    )
    path.write_text(RecipientRegistryFile(policies=(recipient,)).model_dump_json())
    path.chmod(0o600)
    return (
        QualifiedNotificationDraftStore(
            factory,
            QualifiedNotificationFactAdapter(legacy, reader),
            FileOwnerRecipients(path),
            policy=policy,
        ),
        case,
        path,
    )


async def pending_event(
    factory: async_sessionmaker[AsyncSession],
    store: QualifiedNotificationDraftStore,
    case: ProfileScenario,
) -> OutboxEvent:
    profile = await case.preparation.resolve_profile(
        control(), identity(OWNER), case.report_id, case.commitment_id, case.evidence_ids
    )
    pending = await case.preparation.prepare_author(profile.reference)
    event = await NativeFactEmitter(factory, store.loader.reader).emit(
        owner_scope(),
        identity(OWNER),
        DecisionSelector(company_id=COMPANY, action_id=pending.action.proposal.action_id),
    )
    assert event is not None
    return event


async def resolve_event(
    factory: async_sessionmaker[AsyncSession], case: ProfileScenario, event: OutboxEvent
) -> None:
    """The actual owner records the exact current native proposal approval; no authorization."""
    from nexus.company.contracts.actions import ActionProposal
    from nexus.company.management.transactions import management_owner_transaction
    from nexus.harness.canonical import action_hash
    from nexus.harness.journal import CompanyJournal
    from nexus.harness.journal_models import JournalAction
    from nexus.tests.generated_artifact_fixture import ledger

    async with management_owner_transaction(factory, control(), identity(OWNER)) as (session, _, _):
        action = await session.get(JournalAction, event.action_id)
        assert action is not None
        proposal = ActionProposal.model_validate_json(action.proposal_json)
    await CompanyJournal(factory).approve_registered(
        ledger(case.payload.children[0].binding).model_copy(update={"principal_id": OWNER}),
        proposal.action_id,
        action_hash(proposal),
        datetime.now(UTC),
        identity=identity(OWNER),
    )

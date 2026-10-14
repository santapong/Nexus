"""TEST-only public source mutation and actual final-clock/obsolete qualification observers."""

from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain import native_fact_emitter
from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.brain.access_models import BrainResource
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.event_models import BrainEvent
from nexus.company.brain.events import OutboxEvent
from nexus.company.brain.ingestion_store import BrainIngestionStore
from nexus.company.brain.native_fact_emitter import NativeFactEmitter
from nexus.company.brain.native_fact_reader import NativeFactReader
from nexus.company.brain.native_fact_services import NativeFactServices
from nexus.company.brain.source_models import BrainSource, BrainSourceHead, BrainSourceRevision
from nexus.company.brain.source_registry import SourceRegistry
from nexus.company.brain.sources import IngestReceipt
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.operating_report_capture import capture_data
from nexus.company.management.operating_report_store import OperatingReportStore
from nexus.company.management.transactions import management_owner_transaction
from nexus.company.notifications import qualified_store
from nexus.company.notifications.contracts import OwnerRecipientPolicy
from nexus.company.notifications.draft_store import owner_scope
from nexus.company.notifications.qualified_contracts import DraftPublication
from nexus.company.notifications.qualified_obsolete import obsolete_publication_locked
from nexus.company.notifications.recipient_registry import RegisteredOwnerRecipients
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import CompanyControl
from nexus.tests.integration.management_acceptance_source_fixture import Policies
from nexus.tests.integration.test_company_brain_ingestion import RESOURCE, SOURCE, Reader, command
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.notification_worker_digest_fixture import WorkerDigestCase


async def emit_digest_wake(case: WorkerDigestCase, *, expected: bool = True) -> UUID | None:
    assert case.window is not None
    services = case.services
    bound = services.registrations.snapshot().value.registration.sender
    witness = await services.identities.current(expected_binding=bound)
    selector = services.registrations.snapshot().value.registration.subjects[0].selector
    event = await NativeFactEmitter(services.factory, NativeFactReader(services.facts)).emit(
        owner_scope(control(), witness.identity),
        witness.identity,
        selector,
    )
    assert (event is not None) == expected
    return event.event_id if event else None


async def revoke_actual_source_read(case: WorkerDigestCase) -> None:
    services = case.services
    bound = services.registrations.snapshot().value.registration.sender
    witness = await services.identities.current(expected_binding=bound)
    async with management_owner_transaction(services.factory, control(), witness.identity) as (
        session,
        _,
        _,
    ):
        resource = await session.get(BrainResource, (COMPANY, RESOURCE))
        assert resource is not None
        generation = resource.acl_generation
    revoked = await ResourceAccessStore(services.factory).change(
        owner_scope(control(), witness.identity),
        witness.identity,
        ResourceAccessChange(
            company_id=COMPANY,
            resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
            principal_id=OWNER,
            active=False,
            expected_generation=generation,
        ),
    )
    assert not revoked.active


def lose_worker_file_at_final_clock(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
    seen: list[int],
) -> None:
    assert vars(native_fact_emitter)["db_now"] is db_now
    original: Callable[[AsyncSession], Awaitable[datetime]] = db_now
    calls = 0

    async def lost(session: AsyncSession) -> datetime:
        nonlocal calls
        calls += 1
        assert calls <= 2
        actual = await original(session)
        if calls == 2:
            count = await session.scalar(
                select(func.count()).select_from(BrainEvent).where(BrainEvent.kind == "digest_due")
            )
            assert count == 1
            actual = await original(session)
            (root / "synthetic-tick-registration.json").unlink()
            seen.append(calls)
        return actual

    monkeypatch.setattr(native_fact_emitter, "db_now", lost)


async def revise_actual_digest_source(case: WorkerDigestCase, root: Path) -> IngestReceipt:
    services = case.services
    async with management_owner_transaction(services.factory, control(), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        source = await session.get(BrainSource, (COMPANY, SOURCE))
        head = await session.get(BrainSourceHead, (COMPANY, SOURCE))
        assert source is not None and head is not None and head.availability == "available"
        previous = await session.get(BrainSourceRevision, (COMPANY, head.current_revision_id))
        assert previous is not None and previous.source_id == source.source_id
        assert (source.resource_id, source.source_symbol, source.external_key) == (
            RESOURCE,
            "fixture.source.v1",
            "document-1",
        )
        assert (source.authority_profile, source.data_classification) == (
            "fixture.reported.v1",
            "internal",
        )
        generation, revision_id = head.generation, head.current_revision_id
    raw = b"Citation coverage baseline: 0. Revised synthetic digest source; no completion claim."
    revision = "digest-source-r2"
    store = BrainIngestionStore(
        services.factory,
        SourceRegistry((Policies().policy(source.source_symbol),), Reader({revision: raw})),
        ProtectedBlobStore(root / "blobs", storage_symbol="fixture.blobs.v1"),
    )
    receipt = await store.ingest(
        owner_scope(control(), identity(OWNER)),
        identity(OWNER),
        command(raw, revision, revision_id),
    )
    assert receipt.status == "accepted" and receipt.reason_code is None
    async with management_owner_transaction(services.factory, control(), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        current = await session.get(BrainSourceHead, (COMPANY, SOURCE))
        assert current is not None and current.generation == generation + 1
        assert current.current_revision_id == receipt.source.source_revision_id
        assert current.current_revision_id != revision_id
    return receipt


async def current_digest_is_stale(case: WorkerDigestCase) -> None:
    services, facts = case.services, case.services.facts
    reports = OperatingReportStore(
        services.factory, facts.catalog, facts.artifacts, facts.freshness
    )
    assert await reports.get_saved(control(), identity(OWNER), case.saved.report_id) == case.saved
    async with management_owner_transaction(services.factory, control(), identity(OWNER)) as (
        session,
        actual,
        _,
    ):
        brain = owner_scope(control(), identity(OWNER))
        current = await capture_data(
            session,
            actual,
            brain,
            identity(OWNER),
            case.saved.selection,
            facts.catalog,
            facts.artifacts,
            facts.freshness,
        )
        assert canonical_sha256(current) != case.saved.data_sha256
        selector = services.registrations.snapshot().value.registration.subjects[0].selector
        assert (
            await NativeFactReader(facts).load_locked(
                session, actual, brain, identity(OWNER), selector
            )
            is None
        )


def record_licensed_obsolete(
    monkeypatch: pytest.MonkeyPatch,
    expected_event: UUID,
    seen: list[UUID],
) -> None:
    assert vars(qualified_store)["obsolete_publication_locked"] is obsolete_publication_locked

    async def checked(
        session: AsyncSession,
        control: CompanyControl,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        event: OutboxEvent,
        services: NativeFactServices,
        recipient: OwnerRecipientPolicy,
        recipients: RegisteredOwnerRecipients,
    ) -> DraftPublication:
        result = await obsolete_publication_locked(
            session, control, scope, identity, event, services, recipient, recipients
        )
        if event.event_id == expected_event:
            assert result.state == "obsolete" and result.reason == "obsolete_native_state"
            assert result.draft is None and result.protection_deadlines
            seen.append(event.event_id)
        return result

    monkeypatch.setattr(qualified_store, "obsolete_publication_locked", checked)

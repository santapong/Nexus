"""TEST-only direct supplied-session history probes and exact real final-clock observation."""

import asyncio
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain import artifact_store
from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.brain.access_models import BrainResource, BrainResourceAccess
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.obsolete_native_provenance import qualify_obsolete_native_inputs
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.transactions import management_owner_transaction
from nexus.company.notifications.draft_store import owner_scope
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import CompanyControl
from nexus.tests.integration.test_company_brain_ingestion import RESOURCE
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.notification_worker_digest_fixture import WorkerDigestCase, worker_digest_case
from nexus.tests.notification_worker_digest_loss_support import revise_actual_digest_source


async def old_reference_case(
    factory: async_sessionmaker[AsyncSession], root: Path
) -> WorkerDigestCase:
    case = await worker_digest_case(factory, root, "weekly")
    assert case.baseline_references
    changed = await revise_actual_digest_source(case, root)
    assert changed.status == "accepted"
    return case


@asynccontextmanager
async def direct_history_context(
    case: WorkerDigestCase,
) -> AsyncIterator[
    tuple[AsyncSession, CompanyControl, BrainReadScope, AuthenticatedWorkerIdentity]
]:
    bound = case.services.registrations.snapshot().value.registration.sender
    witness = await case.services.identities.current(expected_binding=bound)
    async with management_owner_transaction(case.services.factory, control(), witness.identity) as (
        session,
        actual,
        _,
    ):
        yield session, actual, owner_scope(control(), witness.identity), witness


async def direct_reference(
    case: WorkerDigestCase,
    session: AsyncSession,
    actual: CompanyControl,
    brain: BrainReadScope,
    witness: AuthenticatedWorkerIdentity,
    *,
    historical: bool,
    reference: ArtifactRevisionRef | None = None,
) -> tuple[datetime, ...] | None:
    value = reference or case.baseline_references[0]
    reader = case.services.facts.artifacts
    if historical:
        return await reader.revalidate_historical_artifact_reference(
            session,
            actual,
            brain,
            witness.identity,
            value,
            await db_now(session),
        )
    await reader.revalidate_artifact_reference(
        session,
        actual,
        brain,
        witness.identity,
        value,
        await db_now(session),
    )
    return None


async def direct_qualifier(
    case: WorkerDigestCase,
    session: AsyncSession,
    actual: CompanyControl,
    brain: BrainReadScope,
    witness: AuthenticatedWorkerIdentity,
) -> tuple[tuple[UUID, ...], tuple[datetime, ...]]:
    return await qualify_obsolete_native_inputs(
        session,
        actual,
        brain,
        witness.identity,
        case.services.facts,
        case.saved.data.required_resource_ids,
        case.baseline_references,
    )


def forbid_blob_read(monkeypatch: pytest.MonkeyPatch, case: WorkerDigestCase) -> None:
    async def denied(self: object, reference: ArtifactRevisionRef) -> bytes:
        raise AssertionError("Locked historical metadata must not read a blob")

    monkeypatch.setattr(type(case.services.facts.artifacts.blobs), "read", denied)

    # Owned metadata methods use the supplied session; only this reader's factory is nominated.
    def denied_factory(*args: object, **kwargs: object) -> AsyncSession:
        raise AssertionError("Locked historical metadata must not acquire another session")

    monkeypatch.setattr(case.services.facts.artifacts, "factory", denied_factory)


async def finite_historical_source_grant(case: WorkerDigestCase) -> datetime:
    bound = case.services.registrations.snapshot().value.registration.sender
    witness = await case.services.identities.current(expected_binding=bound)
    async with management_owner_transaction(case.services.factory, control(), witness.identity) as (
        session,
        _,
        _,
    ):
        resource = await session.get(BrainResource, (COMPANY, RESOURCE))
        assert resource is not None
        generation = resource.acl_generation
        expires = await db_now(session) + timedelta(seconds=10)
    saved = await ResourceAccessStore(case.services.factory).change(
        owner_scope(control(), witness.identity),
        witness.identity,
        ResourceAccessChange(
            company_id=COMPANY,
            resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
            principal_id=OWNER,
            active=True,
            expected_generation=generation,
            expires_at=expires,
        ),
    )
    assert saved.active and saved.expires_at == expires
    return expires


def nominate_historical_final_clock(
    monkeypatch: pytest.MonkeyPatch,
    case: WorkerDigestCase,
    expires: datetime,
    seen: list[tuple[datetime, datetime, int]],
) -> None:
    target = BoundedArtifactReader.revalidate_historical_artifact_reference.__code__
    original: Callable[[AsyncSession], Awaitable[datetime]] = vars(artifact_store)["_clock"]
    calls = 0

    async def observed(session: AsyncSession) -> datetime:
        nonlocal calls
        caller = sys._getframe(1)
        try:
            direct = caller.f_code is target
        finally:
            del caller
        if not direct:
            return await original(session)
        calls += 1
        assert calls <= 3
        if calls != 3:
            return await original(session)
        grant = await session.get(BrainResourceAccess, (COMPANY, RESOURCE, OWNER))
        assert grant is not None and grant.active and grant.expires_at == expires
        before = await original(session)
        assert before < expires
        remaining = (expires - datetime.now(UTC)).total_seconds()
        assert 0 < remaining < 15
        await asyncio.sleep(remaining + 0.03)
        after = await original(session)
        assert after >= expires
        seen.append((before, after, calls))
        return after

    monkeypatch.setattr(artifact_store, "_clock", observed)

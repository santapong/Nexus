"""Actual immutable nominated-byte reobservation; old event, row, TTL and outcome stay history."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.builder.snapshot import committed_archive
from nexus.company.brain.base import SourceTime
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.ingestion_store import BrainIngestionStore
from nexus.company.brain.scope_support import brain_transaction
from nexus.company.brain.source_models import BrainSourceHead, BrainSourceRevision
from nexus.company.brain.source_registry import SourceRegistry, SourceSnapshot
from nexus.company.brain.sources import ArtifactRevisionRef, IngestCommand, SourceRegistration
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.settings import settings
from nexus.tests.builder_stockflow_support import REPOSITORY
from nexus.tests.integration.test_company_brain_ingestion import owner_scope
from nexus.tests.integration.test_company_directory import OWNER
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.local_stockflow_packet import ROOT, write_private
from nexus.tests.stockflow_packet_contracts import PreparedState


class NominatedReader:
    def __init__(self, state: PreparedState) -> None:
        self.state = state

    async def read(self, source: SourceRegistration, revision: str) -> SourceSnapshot:
        if (
            source.source_id != UUID(int=9900)
            or source.source_symbol != self.state.source_policy.source_symbol
        ):
            raise ValueError("Reobservation source identity changed")
        await committed_archive(REPOSITORY, self.state.spec.job.source)
        raw = json.dumps({"source": self.state.spec.job.source.model_dump(mode="json")}).encode()
        if hashlib.sha256(raw).hexdigest() != self.state.metadata.sha256:
            raise ValueError("Nominated actual metadata bytes changed")
        return SourceSnapshot(
            company_id=source.company_id,
            source_id=source.source_id,
            source_symbol=source.source_symbol,
            external_key=source.external_key,
            revision=revision,
            raw_bytes=raw,
            source_event=SourceTime(
                precision="instant",
                value="2026-09-01T13:56:41+07:00",
                basis="git committer time; same nominated occurrence, new observation",
            ),
        )


async def reobserve(
    factory: async_sessionmaker[AsyncSession], state: PreparedState
) -> ArtifactRevisionRef:
    # Old fixture source-event is unknown; this precise git commit event does not alter its row.
    async with brain_transaction(factory, owner_scope(), identity(OWNER)) as (session, _, _):
        head = await session.get(BrainSourceHead, (state.spec.job.company_id, UUID(int=9900)))
        if head is None:
            raise ValueError("Actual registered nominated source head is absent")
        old = await session.get(
            BrainSourceRevision, (state.spec.job.company_id, head.current_revision_id)
        )
        if old is None:
            raise ValueError("Actual prior nominated observation is absent")
        previous = head.current_revision_id
        original_event = {
            "precision": old.source_event_precision,
            "value": old.source_event_value,
            "basis": old.source_event_basis,
        }
        before_head = {
            "current_revision_id": str(previous),
            "fresh_until": head.fresh_until.isoformat() if head.fresh_until else None,
        }
    observed = datetime.now(UTC)
    revision = "observed-20261014-2"
    artifact = state.metadata.model_copy(
        update={"artifact_id": uuid4(), "artifact_revision_id": uuid4(), "revision": revision}
    )
    store = BrainIngestionStore(
        factory,
        SourceRegistry((state.source_policy,), NominatedReader(state)),
        ProtectedBlobStore(ROOT, storage_symbol="fixture.blobs.v1"),
    )
    result = await store.ingest(
        owner_scope(),
        identity(OWNER),
        IngestCommand(
            company_id=state.spec.job.company_id,
            source_id=UUID(int=9900),
            revision=revision,
            artifact=artifact,
            expected_previous_revision_id=previous,
        ),
    )
    receipt = {
        "scope": "same registered source/permissions/bytes; new immutable observation",
        "observed_at": observed.isoformat(),
        "before_head": before_head,
        "original_event_unchanged": original_event,
        "underlying_commit_event": "2026-09-01T13:56:41+07:00",
        "same_metadata_sha256": artifact.sha256,
        "ttl_unchanged_seconds": state.source_policy.freshness_seconds,
        "ingestion": result.model_dump(mode="json"),
        "project_processes": 0,
        "old_expiry_rewrites": 0,
        "occurrence_rewrites": 0,
    }
    await asyncio.to_thread(
        write_private,
        ROOT / "source-reobservation-accepted-receipt.json",
        json.dumps(receipt, indent=2).encode(),
    )
    if result.status != "accepted":
        raise ValueError("Reobservation quarantined; it cannot become a job source")
    return result.artifact


async def main() -> None:
    state = PreparedState.model_validate_json(
        await asyncio.to_thread((ROOT / "native-state.json").read_bytes)
    )
    catalog = PlanAdmissionCatalog.model_validate_json(
        await asyncio.to_thread((ROOT / "refreshed-catalog.json").read_bytes)
    )
    url = make_url(settings.company_test_database_url)
    if url.database != "nexus_company_test_builder":
        raise ValueError("Only retained builder database supported")
    engine = create_async_engine(url.set(username="nexus_company_app"))
    try:
        ref = await reobserve(async_sessionmaker(engine, expire_on_commit=False), state)
        current = PreparedState.model_validate_json(
            state.model_copy(update={"metadata": ref, "catalog": catalog}).model_dump_json()
        )
        await asyncio.to_thread(
            write_private,
            ROOT / "accepted-preparation-state.json",
            current.model_dump_json(indent=2).encode(),
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

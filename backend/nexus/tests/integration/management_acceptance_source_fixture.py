"""Configured bounded actual protected report/result bytes with explicit source policies."""

import hashlib
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.ingestion_store import BrainIngestionStore
from nexus.company.brain.source_registry import SourcePolicy, SourceRegistry
from nexus.company.brain.sources import ArtifactRevisionRef, IngestCommand, SourceRegistration
from nexus.tests.integration.test_company_brain_ingestion import owner_scope
from nexus.tests.integration.test_company_brain_retrieval import Reader
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.management_plan_support import VERIFIER


class Policies:
    """Server-configured fixture registry; no publication request can select a policy."""

    def __init__(self) -> None:
        initial = SourcePolicy(
            source_symbol="fixture.source.v1",
            authority_profile="fixture.reported.v1",
            data_classification="internal",
            media_type="text/plain",
            parser_version="utf8-identity-v1",
            chunker_version="utf8-sections-v1",
            search_config="simple",
            freshness_seconds=3600,
            allowed_external_keys=frozenset({"document-1"}),
        )
        self.values = {initial.source_symbol: initial}

    def policy(self, symbol: str) -> SourcePolicy:
        return self.values[symbol]


async def protected_text(
    factory: async_sessionmaker[AsyncSession],
    blobs: ProtectedBlobStore,
    policies: Policies,
    text: str,
    identifier: int,
    ttl: int | None = 300,
) -> ArtifactRevisionRef:
    symbol = f"acceptance.fixture.{identifier}"
    policy = SourcePolicy(
        source_symbol=symbol,
        authority_profile="fixture.reported.v1",
        data_classification="internal",
        media_type="text/plain",
        parser_version="utf8-identity-v1",
        chunker_version="utf8-sections-v1",
        search_config="simple",
        freshness_seconds=ttl,
        allowed_external_keys=frozenset({f"source-{identifier}"}),
    )
    policies.values[symbol] = policy
    store = BrainIngestionStore(
        factory, SourceRegistry((policy,), Reader({"1": text.encode()}, ())), blobs
    )
    source = SourceRegistration(
        company_id=COMPANY,
        source_id=UUID(int=identifier),
        resource=ResourceRef(company_id=COMPANY, resource_id=UUID(int=identifier + 1)),
        source_symbol=symbol,
        external_key=f"source-{identifier}",
    )
    await store.register(owner_scope(), identity(OWNER), source, readers=(OWNER, ACTOR, VERIFIER))
    raw = text.encode()
    reference = ArtifactRevisionRef(
        company_id=COMPANY,
        artifact_id=UUID(int=identifier + 2),
        artifact_revision_id=UUID(int=identifier + 3),
        revision="1",
        sha256=hashlib.sha256(raw).hexdigest(),
        byte_length=len(raw),
    )
    await store.ingest(
        owner_scope(),
        identity(OWNER),
        IngestCommand(
            company_id=COMPANY, source_id=source.source_id, revision="1", artifact=reference
        ),
    )
    return reference

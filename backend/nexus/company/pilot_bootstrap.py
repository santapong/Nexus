"""Explicit disposable operator bootstrap calls actual native services, never test fixtures."""

import asyncio
import hashlib
from dataclasses import dataclass
from uuid import UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.ingestion_store import BrainIngestionStore
from nexus.company.brain.sources import ArtifactRevisionRef, IngestCommand, SourceRegistration
from nexus.company.directory_contracts import CompanyRegistration, MembershipChange
from nexus.company.management.artifact_target_store import ArtifactTargetStore
from nexus.company.pilot_composition import PilotServices
from nexus.company.pilot_config import PREVIEW_PROFILE, PilotConfig
from nexus.company.pilot_sources import PRIVATE_TEXT, PUBLIC_TEXT, pilot_sources
from nexus.harness.journal_contracts import CompanyPolicy, LedgerScope


async def bootstrap_directory(services: PilotServices, config: PilotConfig) -> None:
    from nexus.company.directory_store import PersistentCompanyDirectory

    scope = config.control()
    await services.base.journal.create_company(
        CompanyPolicy(
            company_id=config.company_id,
            owner_id=config.owner_id,
            policy_version=(
                "nexus-preview-supervised-v1"
                if config.profile == PREVIEW_PROFILE
                else "uat-supervised-v1"
            ),
            price_version=(
                "nexus-preview-no-provider-v1"
                if config.profile == PREVIEW_PROFILE
                else "uat-offline-v1"
            ),
        ),
        LedgerScope(
            company_id=config.company_id,
            principal_id=config.owner_id,
            task_id=scope.operation_id,
            trace_id=scope.trace_id,
        ),
    )
    directory = services.base.directory
    assert isinstance(directory, PersistentCompanyDirectory)
    await directory.bootstrap(
        CompanyRegistration(
            company_id=config.company_id, workspace_id=config.workspace_id, owner_id=config.owner_id
        ),
        scope,
    )
    for principal in (config.author_id, config.verifier_id, config.member_id):
        await directory.set_membership(
            MembershipChange(company_id=config.company_id, principal_id=principal, role="member"),
            config.control(),
        )


async def bootstrap_sources(factory: async_sessionmaker[AsyncSession], config: PilotConfig) -> None:
    registry = await asyncio.to_thread(pilot_sources, config)
    store = BrainIngestionStore(
        factory,
        registry,
        ProtectedBlobStore(config.blob_root, storage_symbol="uat.local-blobs.v1"),
    )
    scope = BrainReadScope(
        company_id=config.company_id,
        workspace_id=config.workspace_id,
        principal_id=config.owner_id,
        operation_id=config.control().operation_id,
        trace_id=config.control().trace_id,
    )
    for seed in await asyncio.to_thread(source_seeds, config):
        await ingest_seed(store, scope, config, seed)
    if config.profile == PREVIEW_PROFILE:
        return
    targets = ArtifactTargetStore(factory)
    for target in (config.report_resource_id, config.check_resource_id):
        await targets.provision(
            scope,
            config.identity(),
            ResourceRef(company_id=config.company_id, resource_id=target),
            readers=(config.owner_id, config.author_id, config.verifier_id),
        )


@dataclass(frozen=True)
class SourceSeed:
    source_id: UUID
    resource_id: UUID
    symbol: str
    key: str
    text: str
    readers: tuple[UUID, ...]
    revision: str = "uat-synthetic-v1"


def source_seeds(config: PilotConfig) -> tuple[SourceSeed, ...]:
    if config.profile == PREVIEW_PROFILE:
        from nexus.company.pilot_preview import document_symbol, preview_documents

        return tuple(
            SourceSeed(
                uuid5(config.public_source_id, document.pin.path),
                uuid5(config.public_resource_id, document.pin.path),
                document_symbol(index),
                document.pin.path,
                document.text,
                (config.owner_id, config.author_id, config.verifier_id, config.member_id),
                document.commit,
            )
            for index, document in enumerate(preview_documents(config))
        )
    return (
        SourceSeed(
            config.public_source_id,
            config.public_resource_id,
            "uat.synthetic.public.v1",
            "uat-public",
            PUBLIC_TEXT,
            (config.owner_id, config.author_id, config.verifier_id, config.member_id),
        ),
        SourceSeed(
            config.private_source_id,
            config.private_resource_id,
            "uat.synthetic.private.v1",
            "uat-private",
            PRIVATE_TEXT,
            (config.owner_id,),
        ),
    )


async def ingest_seed(
    store: BrainIngestionStore, scope: BrainReadScope, config: PilotConfig, seed: SourceSeed
) -> None:
    await store.register(
        scope,
        config.identity(),
        SourceRegistration(
            company_id=config.company_id,
            source_id=seed.source_id,
            resource=ResourceRef(company_id=config.company_id, resource_id=seed.resource_id),
            source_symbol=seed.symbol,
            external_key=seed.key,
        ),
        readers=seed.readers,
    )
    raw = seed.text.encode()
    artifact = ArtifactRevisionRef(
        company_id=config.company_id,
        artifact_id=uuid5(seed.source_id, "uat-artifact"),
        artifact_revision_id=uuid5(
            seed.source_id,
            f"document:{seed.revision}" if config.profile == PREVIEW_PROFILE else "uat-artifact-v1",
        ),
        revision=seed.revision,
        sha256=hashlib.sha256(raw).hexdigest(),
        byte_length=len(raw),
    )
    await store.ingest(
        scope,
        config.identity(),
        IngestCommand(
            company_id=config.company_id,
            source_id=seed.source_id,
            revision=artifact.revision,
            artifact=artifact,
        ),
    )

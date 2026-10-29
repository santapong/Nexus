"""Real committed Nexus source ingestion and public J publication, never fabricated refs.

Cohesion exception: these two source boundaries share the exact input receipt,
native parse selectors and complete byte closure. No generalized fixture/store
layer is introduced to split the source acquisition from its output-source proof.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import stat
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from uuid import UUID, uuid5

from pydantic import Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.builder.contained_query import clock_us
from nexus.builder.contracts import BuilderArtifact, RepositoryPin
from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.access_support import require_resources
from nexus.company.brain.base import BrainReadScope, SourceTime, ValueContract
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.context import ContextLimits
from nexus.company.brain.context_store import PersistentContextAssembler
from nexus.company.brain.evidence_models import BrainEvidence
from nexus.company.brain.git_source import CommittedGitSourceReader, GitSnapshotSpec
from nexus.company.brain.ingestion_store import BrainIngestionStore
from nexus.company.brain.retrieval import RetrievalLimits, SearchRequest
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.brain.scope_support import brain_transaction
from nexus.company.brain.source_registry import SourcePolicy, SourceRegistry
from nexus.company.brain.sources import (
    ArtifactRevisionRef,
    EvidenceRef,
    IngestCommand,
    SourceRegistration,
    SourceRevisionRef,
)
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.coding_prepared_store import CodingPreparedStore
from nexus.company.management.coding_publication_contracts import (
    CodingPublicationRules,
    PublishedCodingPatch,
)
from nexus.company.management.coding_publication_store import CodingPublicationStore
from nexus.company.management.coding_repository import (
    CodingRepositoryReader,
)
from nexus.company.management.coding_sources import CodingSourceRef
from nexus.company.management.lifecycle import PlanRevision
from nexus.company.management.owner_view_sources import OwnerViewSources, owner_brain_scope
from nexus.company.management.plan_catalog import NamedPlanResource, PlanAdmissionCatalog
from nexus.company.management.planning_authority import ManagementPlanningAuthority
from nexus.company.management.planning_native_facts import require_time
from nexus.execution.management_services import ManagementExecutionServices
from nexus.execution.planning_application_config import PlanningSourcePolicies

if TYPE_CHECKING:
    from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
    from nexus.execution.coding_application import CodingApplication
    from nexus.execution.coding_preparation import PreparedCodingAction
    from nexus.tests.integration.nexus_coding_application_fixture import Case, Database

CODE_PATH = "backend/nexus/company/management/canonical.py"
DOCUMENT_PATH = "docs/company-system/ARCHITECTURE.md"
COMMIT = "3fda71b534521247019b18c703a5c8e5ed92f8e9"
TREE = "c5a5ecaa51acdcf9a9347d6054795dd8fde9f5ff"
ARCHIVE_SHA = "a30ca35a7aed151d4f30e686a5cbd6e331f514ce94e0a989d2300b36d242f1a4"
DATABASE = "nexus_company_test_nexus_coding_application_v11"
RELEASE_ROOT = Path("/var/tmp/nexus-coding-application-actual-checks-20261028-11")
SOCKET = "/var/tmp/nexus-coding-application-pg-20261028-11/socket"
PORT = 55907
PYTEST_BASETEMP = Path("/var/tmp/nexus-coding-application-pytest-20261028-11")
SOURCE_RECEIPT = Path(
    "/home/santapong/.codex/nexus-source-recovery-20261028-2/SOURCE_SELECTION_20261028.json"
)
SOURCE_RECEIPT_SHA = "bfdf851751330da43feeaf3227d363e97c23bb9f5804b0ea293aeb6cfed9d259"


class SelectedBlob(ValueContract):
    """Root-observed immutable metadata; source IDs belong to this new public registration."""

    path: str
    git_blob: str = Field(pattern=r"^[0-9a-f]{40}$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_length: int = Field(gt=0, le=65536, strict=True)
    source_event: SourceTime


class SourceReceipt(ValueContract):
    format: Literal["nexus.c.application.source-selection.v1"]
    checked_at: datetime
    repository_path: Path
    source: RepositoryPin
    files: tuple[SelectedBlob, ...]
    archive_byte_length: int
    prior_actual_reader_probe: dict[str, str]
    seconds: float
    scope: str


class AcceptanceRelease(ValueContract):
    """Required Root release; no default source receipt or executable placeholder exists."""

    database: Literal["nexus_company_test_nexus_coding_application_v11"]
    source_receipt: Path
    source_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_executions: Literal[0]
    socket_path: Literal["/var/tmp/nexus-coding-application-pg-20261028-11/socket"]
    port: Literal[55907]
    role: Literal["nexus_company_app"]
    pytest_basetemp: Literal["/var/tmp/nexus-coding-application-pytest-20261028-11"]

    @model_validator(mode="after")
    def separate_data_and_pytest(self) -> AcceptanceRelease:
        """Root driver must ALSO do this BEFORE pytest can clear its basetemp."""
        base, cluster = Path(self.pytest_basetemp), Path(self.socket_path).parent
        assert base != cluster and base not in cluster.parents and cluster not in base.parents
        assert base != RELEASE_ROOT and RELEASE_ROOT not in base.parents
        return self


def private_bytes(path: Path, limit: int) -> bytes:
    """Ordinary UID-owned private file only, with matching final named identity."""

    def signature(value: os.stat_result) -> tuple[int, ...]:
        return (
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_uid,
            value.st_gid,
            value.st_nlink,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )

    first = path.lstat()
    assert stat.S_ISREG(first.st_mode) and stat.S_IMODE(first.st_mode) == 0o600
    assert first.st_uid == os.getuid() and first.st_nlink == 1 and first.st_size <= limit
    with path.open("rb") as stream:
        assert signature(os.fstat(stream.fileno())) == signature(first)
        raw = stream.read(limit + 1)
    assert signature(path.lstat()) == signature(first) and 0 < len(raw) <= limit
    return raw


def required_source() -> SourceReceipt:
    """Root creates the release separately; this function never queries a Git repository."""
    release = AcceptanceRelease.model_validate_json(
        private_bytes(RELEASE_ROOT / "ROOT_RELEASE_1.json", 16384)
    )
    assert (release.source_receipt, release.source_receipt_sha256) == (
        SOURCE_RECEIPT,
        SOURCE_RECEIPT_SHA,
    )
    raw = private_bytes(release.source_receipt, 65536)
    assert hashlib.sha256(raw).hexdigest() == release.source_receipt_sha256
    source = SourceReceipt.model_validate_json(raw)
    assert (source.source.commit, source.source.tree, source.source.archive_sha256) == (
        COMMIT,
        TREE,
        ARCHIVE_SHA,
    )
    assert source.repository_path == Path(
        "/home/santapong/.codex/nexus-source-recovery-20261028-2/nexus.git"
    )
    assert {row.path for row in source.files} == {CODE_PATH, DOCUMENT_PATH}
    assert len(source.files) == 2
    return source


@dataclass(frozen=True)
class Sources:
    receipt: SourceReceipt
    source: RepositoryPin
    document: GitSnapshotSpec
    code: CodingSourceRef
    document_evidence: EvidenceRef
    code_resource: ResourceRef
    document_resource: ResourceRef
    registry: SourceRegistry
    blobs: ProtectedBlobStore
    retriever: PersistentBrainRetriever
    originals: bytes


async def ingest_sources(
    database: Database,
    root: Path,
    owner: AuthenticatedWorkerIdentity,
    scope: BrainReadScope,
    readers: tuple[UUID, ...],
) -> Sources:
    """Actual Git→public ingestion→complete spans in one exact source-closure sequence."""
    receipt = await asyncio.to_thread(required_source)
    specs = tuple(
        GitSnapshotSpec(
            company_id=scope.company_id,
            source_id=uuid5(scope.company_id, "source:" + row.path),
            source_symbol="nexus.acceptance.code.v1"
            if row.path == CODE_PATH
            else "nexus.acceptance.docs.v1",
            external_key=row.path,
            path=row.path,
            commit=receipt.source.commit,
            git_blob=row.git_blob,
            sha256=row.sha256,
            byte_length=row.byte_length,
            source_event=row.source_event,
        )
        for row in receipt.files
    )
    policies = tuple(
        SourcePolicy(
            source_symbol=row.source_symbol,
            authority_profile="nexus.committed-source.v1",
            data_classification="internal",
            media_type="text/plain" if row.path == CODE_PATH else "text/markdown",
            parser_version="utf8-identity-v1",
            chunker_version="utf8-sections-v1",
            search_config="simple",
            freshness_seconds=3600,
            allowed_external_keys=frozenset({row.path}),
        )
        for row in specs
    )
    registry = SourceRegistry(policies, CommittedGitSourceReader(receipt.repository_path, specs))
    blobs = ProtectedBlobStore(root / "brain", storage_symbol="nexus.acceptance.brain.v1")
    ingestion = BrainIngestionStore(database.factory, registry, blobs)
    retriever = PersistentBrainRetriever(database.factory, blobs, limits=RetrievalLimits())
    mapped: dict[str, CodingSourceRef] = {}
    resources: dict[str, ResourceRef] = {}
    original: dict[str, bytes] = {}
    for spec in specs:
        resource = ResourceRef(
            company_id=scope.company_id, resource_id=uuid5(spec.source_id, "resource")
        )
        registration = SourceRegistration(
            company_id=scope.company_id,
            source_id=spec.source_id,
            resource=resource,
            source_symbol=spec.source_symbol,
            external_key=spec.external_key,
        )
        await ingestion.register(scope, owner.identity, registration, readers=readers)
        artifact = ArtifactRevisionRef(
            company_id=scope.company_id,
            artifact_id=uuid5(spec.source_id, "artifact"),
            artifact_revision_id=uuid5(spec.source_id, spec.commit),
            revision=spec.commit,
            sha256=spec.sha256,
            byte_length=spec.byte_length,
        )
        accepted = await ingestion.ingest(
            scope,
            owner.identity,
            IngestCommand(
                company_id=scope.company_id,
                source_id=spec.source_id,
                revision=spec.commit,
                artifact=artifact,
            ),
        )
        assert accepted.status == "accepted"
        ids = await evidence_ids(database.factory, scope, owner.identity, resource, accepted.source)
        found = await retriever.search(
            scope,
            owner.identity,
            SearchRequest(
                company_id=scope.company_id,
                query="Nexus",
                explicit_evidence_ids=ids,
            ),
        )
        handles = tuple(
            row.handle for row in found.handles if row.handle.record.source == accepted.source
        )
        # Complete fixed files, never synthetic references or partial FTS excerpts.
        assert handles
        material = await retriever.materialize(scope, owner.identity, handles)
        ordered = sorted(material, key=lambda row: row.record.raw_span.start_byte)
        cursor = 0
        for row in ordered:
            assert row.record.raw_span.start_byte == cursor
            cursor = row.record.raw_span.end_byte
        raw = "".join(row.text for row in ordered).encode()
        assert (cursor, len(raw), hashlib.sha256(raw).hexdigest()) == (
            spec.byte_length,
            spec.byte_length,
            spec.sha256,
        )
        mapped[spec.path] = CodingSourceRef(
            file=BuilderArtifact(path=spec.path, sha256=spec.sha256, byte_length=spec.byte_length),
            git=spec,
            source=accepted.source,
            artifact=accepted.artifact,
            evidence=tuple(
                EvidenceRef(company_id=scope.company_id, evidence_id=row.record.evidence_id)
                for row in ordered
            ),
        )
        resources[spec.path], original[spec.path] = resource, raw
    document = mapped[DOCUMENT_PATH]
    return Sources(
        receipt,
        receipt.source,
        document.git,
        mapped[CODE_PATH],
        document.evidence[0],
        resources[CODE_PATH],
        resources[DOCUMENT_PATH],
        registry,
        blobs,
        retriever,
        original[CODE_PATH],
    )


async def evidence_ids(
    factory: async_sessionmaker[AsyncSession],
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    resource: ResourceRef,
    source: SourceRevisionRef,
) -> tuple[UUID, ...]:
    """Actual persisted parse selectors under current ACL, followed by public retrieval.

    FTS relevance cannot prove full closure; no imagined deterministic EvidenceRef
    or raw body substitutes for the actual current native metadata read.
    """
    async with brain_transaction(factory, scope, identity) as (session, _, now):
        await require_resources(session, scope, (resource.resource_id,), now)
        return tuple(
            (
                await session.scalars(
                    select(BrainEvidence.evidence_id)
                    .where(
                        BrainEvidence.company_id == scope.company_id,
                        BrainEvidence.source_revision_id == source.source_revision_id,
                    )
                    .order_by(BrainEvidence.raw_start_byte)
                )
            ).all()
        )


def publication_rules(case: Case, action: UUID) -> CodingPublicationRules:
    """Closed server targets; actor/model output cannot select source IDs or audiences."""
    company = case.config.catalog.company_id
    registrations, policies = [], []
    for kind, maximum in (("model_origin", 131072), ("code_patch", 32768)):
        symbol = "nexus.coding." + kind + ".v1"
        registrations.append(
            SourceRegistration(
                company_id=company,
                source_id=uuid5(action, f"coding-{kind}-source-v1"),
                resource=ResourceRef(
                    company_id=company, resource_id=uuid5(company, kind + "-resource")
                ),
                source_symbol=symbol,
                external_key=str(action),
            )
        )
        policies.append(
            SourcePolicy(
                source_symbol=symbol,
                authority_profile="coding.generated.v1",
                data_classification="internal",
                origin_kind="derived",
                media_type="application/json" if kind == "model_origin" else "text/plain",
                parser_version="utf8-identity-v1",
                chunker_version="utf8-sections-v1",
                search_config="simple",
                freshness_seconds=None,
                allowed_external_keys=frozenset({str(action)}),
                max_bytes=maximum,
            )
        )
    return CodingPublicationRules(
        company_id=company,
        action_id=action,
        origin=registrations[0],
        patch=registrations[1],
        origin_policy=policies[0],
        patch_policy=policies[1],
        readers=tuple(
            sorted(
                {
                    case.owner.identity.principal_id,
                    *(slot.child.binding.actor_id for slot in case.config.admission.slots[5:7]),
                }
            )
        ),
    )


def publication_catalog_view(
    runtime: PlanAdmissionCatalog,
    rules: CodingPublicationRules,
    *,
    expected_runtime_sha256: str,
) -> PlanAdmissionCatalog:
    """Fresh J-only output view after real registration; original C input pins stay fixed."""
    checked = PlanAdmissionCatalog.model_validate_json(runtime.model_dump_json())
    if canonical_sha256(checked) != expected_runtime_sha256:
        raise ValueError("J catalog requires the unchanged original runtime catalog")
    admission = checked.nexus_coding_admission
    if admission is None or rules.company_id != checked.company_id:
        raise ValueError("J catalog requires the original coding company admission")
    inputs = {slot.tool.resource for slot in admission.slots}
    symbols = {row.symbol for row in checked.resources}
    if symbols not in (inputs, inputs | {"nexus.knowledge"}):
        raise ValueError("J runtime catalog contains resources outside original inputs")
    outputs = tuple(
        NamedPlanResource(symbol="coding." + kind, resource=registration.resource)
        for kind, registration in (("model_origin", rules.origin), ("code_patch", rules.patch))
    )
    if any(
        row.resource.resource_id != uuid5(checked.company_id, kind + "-resource")
        or row.resource.resource_id in {item.resource.resource_id for item in checked.resources}
        for kind, row in zip(("model_origin", "code_patch"), outputs, strict=True)
    ):
        raise ValueError("J output resources require their distinct fixed future targets")
    view = PlanAdmissionCatalog.model_validate_json(
        checked.model_copy(update={"resources": (*checked.resources, *outputs)}).model_dump_json()
    )
    if checked.model_dump(exclude={"resources"}) != view.model_dump(exclude={"resources"}):
        raise ValueError("J catalog changed an original C projection")
    return view


async def publish_candidate(
    case: Case,
    app: CodingApplication,
    prepared: PreparedCodingAction,
    head: PlanRevision,
) -> PublishedCodingPatch:
    """Real J service, not HTTP. One original owner window covers registration/publication.

    Cohesion exception: keep actual same-graph construction, recipient checks and
    the original owner/read cutoff together; no late metadata is a new permission.
    """
    before, now = clock_us(), datetime.now(UTC)
    case.owner.require_time(now)
    end = min(
        before + 30_000_000, before + (case.owner.expires_at - now) // timedelta(microseconds=1)
    )
    require_time(end)
    rules = publication_rules(case, prepared.action.proposal.action_id)
    policies = (*case.config.planning.source_policies, rules.origin_policy, rules.patch_policy)
    registry = SourceRegistry(policies, case.source.registry._reader)
    published_blobs = app.services.management.artifacts.blobs
    assert type(published_blobs) is ProtectedBlobStore
    ingestion = BrainIngestionStore(app.services.factory, registry, published_blobs)
    scope = case.owner_scope()
    brain = owner_brain_scope(scope, case.owner.identity)
    for source in (rules.origin, rules.patch):
        async with asyncio.timeout(max(0, end - clock_us()) / 1_000_000):
            await ingestion.register(brain, case.owner.identity, source, readers=rules.readers)
        case.owner.require_time(datetime.now(UTC))
        require_time(end)
    fresh = RegisteredSourceFreshness(
        app.services.factory, PlanningSourcePolicies(policies=policies)
    )
    catalog = publication_catalog_view(
        app.services.management.catalog,
        rules,
        expected_runtime_sha256=canonical_sha256(case.config.catalog),
    )
    management = ManagementExecutionServices(catalog, app.services.management.artifacts, fresh)
    contexts = PersistentContextAssembler(
        app.services.factory,
        app.services.contexts._retriever,
        ManagementPlanningAuthority(management, case.config.role_policy, case.config.recipe),
        limits=ContextLimits(policy_version=case.config.planning.policy_version),
    )
    repository = CodingRepositoryReader(
        case.config.repository_path, case.config.repository_selection
    )
    store = CodingPreparedStore(
        app.services.factory,
        management,
        contexts,
        app.services.prepared_blobs,
        OwnerViewSources(management.artifacts, fresh),
        case.config.recipe,
        repository,
    )
    publisher = CodingPublicationStore(
        app.services.factory,
        management.catalog,
        store,
        app.services.evidence,
        published_blobs,
        repository,
        rules=rules,
    )
    case.publishers.append(publisher)
    published = await publisher.publish(
        scope,
        case.owner,
        rules.action_id,
        prepared.action.proposal_hash,
        expected_goal=case.config.goal,
        expected_current_revision_id=head.plan_revision_id,
        end_us=end,
    )
    end = min(end, published.read_end_us)
    require_time(end)
    case.owner.require_time(datetime.now(UTC))
    assert published.value.patch.status == "accepted"
    assert not publisher.pending_owners()
    for principal in rules.readers:
        if principal == case.owner.identity.principal_id:
            continue
        recipient_witness = case.identities[principal]
        recipient_witness.require_time(datetime.now(UTC))
        identity = recipient_witness.identity
        recipient = brain.model_copy(update={"principal_id": principal})
        selected: list[UUID] = []
        for registration, revision in (
            (rules.origin, published.value.origin.source),
            (rules.patch, published.value.patch.source),
        ):
            selected.extend(
                (
                    await evidence_ids(
                        app.services.factory, recipient, identity, registration.resource, revision
                    )
                )[:1]
            )
        assert len(selected) <= 32
        result = await case.source.retriever.search(
            recipient,
            identity,
            SearchRequest(
                company_id=scope.company_id,
                query="Nexus",
                explicit_evidence_ids=tuple(selected),
            ),
        )
        relevant = tuple(
            row.handle
            for row in result.handles
            if row.handle.record.source
            in {published.value.origin.source, published.value.patch.source}
        )
        assert relevant
        values = await case.source.retriever.materialize(recipient, identity, relevant)
        recipient_witness.require_time(datetime.now(UTC))
        require_time(end)
        assert {value.record.source for value in values} == {
            published.value.origin.source,
            published.value.patch.source,
        }
    return published.value

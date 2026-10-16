"""True current owner publishes one atomic native-backed C origin/patch pair.

Cohesion exception: original concrete storage/native/source bindings, the first
recipient cutoff and final paired publication share one bounded operation. No
callback, posted candidate or decoded proof can enter this write boundary.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import stat
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope
from nexus.company.brain.access_contracts import ResourceGeneration
from nexus.company.brain.access_models import BrainResource, BrainResourceAccess
from nexus.company.brain.access_support import require_resources
from nexus.company.brain.artifact_input_support import CLASSIFICATIONS, artifact_input_closure
from nexus.company.brain.base import BrainReadScope, ValueContract
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.ingestion_records import source_record
from nexus.company.brain.native_fact_inputs import source_artifact_reference
from nexus.company.brain.source_models import BrainSource, BrainSourceRevision
from nexus.company.brain.sources import ArtifactRevisionRef, SourceRecord, SourceRegistration
from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.directory_models import DirectoryMembership
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.artifact_target_store import require_initial_readers
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.coding_prepared_checks import require_action_header, shorten
from nexus.company.management.coding_prepared_contracts import (
    StoredCodingRequest,
    repository_selection,
)
from nexus.company.management.coding_prepared_store import CodingPreparedStore
from nexus.company.management.coding_publication_contracts import (
    CodingPublicationRead,
    CodingPublicationRules,
)
from nexus.company.management.coding_publication_rows import (
    PublicationPair,
    append_pair,
    model_origin,
    prepare_pair,
    require_native_result,
)
from nexus.company.management.coding_repository import CodingRepositoryReader
from nexus.company.management.coding_sources import require_coding_sources
from nexus.company.management.cycle_cost_contracts import NativeCostSelection
from nexus.company.management.cycle_model_reader import cost_read_end, native_cost_selection
from nexus.company.management.goals import GoalRevisionRef
from nexus.company.management.nexus_coding_admission import NexusCodingAdmission
from nexus.company.management.nexus_coding_catalog import configured_nexus_admission
from nexus.company.management.owner_view_sources import owner_brain_scope
from nexus.company.management.plan_catalog import PlanAdmissionCatalog
from nexus.company.management.planning_native_facts import clock_us, require_time
from nexus.company.management.transactions import (
    ManagementDeniedError,
    management_owner_transaction,
)
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.runtime_support import db_now
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CompanyControl
from nexus.harness.model_evidence import FileModelEvidenceStore


class PublicationAudience(ValueContract):
    sources: tuple[SourceRecord, ...]
    grants: tuple[tuple[UUID, tuple[ResourceGeneration, ...]], ...]


@dataclass(frozen=True, slots=True)
class PublicationGate:
    native: NativeCostSelection
    audience: PublicationAudience
    inputs: tuple[ArtifactRevisionRef, ...]
    end: int
    observed_at: datetime

    def require_same(self, other: PublicationGate) -> None:
        if (self.native, self.audience, self.inputs) != (
            other.native,
            other.audience,
            other.inputs,
        ):
            raise ManagementDeniedError(
                "Coding native/source/recipient state changed during private IO"
            )


class CodingPublicationStore:
    """Concrete native/H/model/Brain graph; a public method takes IDs, never caller proof.

    Cohesion exception: the original sealed graph, real owners and initial/final
    source windows remain adjacent to the one atomic owner publication operation.
    """

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        catalog: PlanAdmissionCatalog,
        prepared: CodingPreparedStore,
        evidence: FileModelEvidenceStore,
        blobs: ProtectedBlobStore,
        repository: CodingRepositoryReader,
        *,
        rules: CodingPublicationRules,
    ) -> None:
        admission = configured_nexus_admission(catalog)
        if (
            type(admission) is not NexusCodingAdmission
            or type(prepared) is not CodingPreparedStore
            or prepared.factory is not factory
            or prepared.management.catalog is not catalog
            or type(evidence) is not FileModelEvidenceStore
            or type(blobs) is not ProtectedBlobStore
            or prepared.sources.artifacts.blobs is not blobs
            or type(repository) is not CodingRepositoryReader
            or prepared.repository is not repository
            or type(prepared.sources.freshness) is not RegisteredSourceFreshness
        ):
            raise ValueError("Coding publication requires the original concrete full-company graph")
        self.factory, self.catalog, self.prepared, self.evidence, self.blobs, self.repository = (
            factory,
            catalog,
            prepared,
            evidence,
            blobs,
            repository,
        )
        self.rules = CodingPublicationRules.model_validate_json(rules.model_dump_json())
        if rules.company_id != catalog.company_id or not {
            rules.origin.resource,
            rules.patch.resource,
        } <= {row.resource for row in catalog.resources}:
            raise ValueError(
                "Coding publication targets were not configured in the original catalog"
            )
        self.admission = admission
        self._objects = (factory, catalog, prepared, evidence, blobs, repository, self.rules)
        self._pins = self._values()
        self._owners: list[asyncio.Task[object]] = []
        self._stopped = False
        self._first_error: BaseException | None = None
        self.require_composition()

    def _values(self) -> tuple[object, ...]:
        return (
            canonical_sha256(self.catalog),
            canonical_sha256(self.rules),
            self.evidence._root,
            self.blobs._root,
            self.blobs.storage_symbol,
            self.repository.selection_sha256,
            self.prepared.sources.freshness,
        )

    def require_composition(self) -> None:
        if (
            any(
                a is not b
                for a, b in zip(
                    self._objects,
                    (
                        self.factory,
                        self.catalog,
                        self.prepared,
                        self.evidence,
                        self.blobs,
                        self.repository,
                        self.rules,
                    ),
                    strict=True,
                )
            )
            or self._values() != self._pins
            or self.prepared.factory is not self.factory
            or self.prepared.management.catalog is not self.catalog
            or self.prepared.repository is not self.repository
            or self.prepared.sources.artifacts.blobs is not self.blobs
        ):
            raise ManagementDeniedError("Original coding publication graph changed")
        self.prepared.require_composition()
        freshness = self.prepared.sources.freshness
        if type(freshness) is not RegisteredSourceFreshness:
            raise ManagementDeniedError("Coding publication source qualifier changed")
        for policy in (self.rules.origin_policy, self.rules.patch_policy):
            if freshness._policies.policy(policy.source_symbol) != policy:
                raise ManagementDeniedError(
                    "Coding publication policy was not in the original source graph"
                )

    def request_stop(self) -> None:
        self._stopped = True
        # These are the actual sealed operations, not caller callbacks. Already
        # issued leaves remain retained; later preparation phases cannot start.
        self.prepared.request_stop()
        self.repository.request_stop()

    def pending_owners(self) -> tuple[asyncio.Task[object], ...]:
        return tuple(
            dict.fromkeys(
                (
                    *(row for row in self._owners if not row.done() or row.cancelled()),
                    *self.prepared.pending_owners(),
                    *self.evidence.pending_owners(),
                    *self.blobs.pending_owners(),
                    *self.repository.pending_owners(),
                )
            )
        )

    def _current(self, owner: AuthenticatedWorkerIdentity, end: int) -> None:
        self.require_composition()
        require_time(end)
        if self._stopped or type(owner) is not AuthenticatedWorkerIdentity:
            raise ManagementDeniedError("Original coding publication was stopped")
        owner.require_time(datetime.now(UTC))

    async def _owned[T](
        self, operation: Awaitable[T], owner: AuthenticatedWorkerIdentity, end: int
    ) -> T:
        try:
            self._current(owner, end)
            if len(self.pending_owners()) >= 32:
                raise ManagementDeniedError("Coding publication pending resource bound exceeded")
        except BaseException:
            if inspect.iscoroutine(operation):
                operation.close()
            raise
        task = asyncio.ensure_future(operation)
        self._owners[:] = [row for row in self._owners if not row.done() or row.cancelled()]
        self._owners.append(task)
        task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        try:
            async with asyncio.timeout(max(0, end - clock_us()) / 1_000_000):
                result = await asyncio.shield(task)
            self._current(owner, end)
            return result
        except BaseException as first:
            self._first_error = self._first_error or first
            self.request_stop()
            first.__dict__["_nexus_coding_publication_pending"] = self.pending_owners()
            raise

    async def _audience(
        self, session: AsyncSession, scope: BrainReadScope, loaded: StoredCodingRequest
    ) -> PublicationAudience:
        """Cohesion exception: both fixed resources and every reader share ONE CC snapshot."""
        ids = {row.resource_id for row in loaded.header.contributors}
        targets = {self.rules.origin.resource.resource_id, self.rules.patch.resource.resource_id}
        if ids & targets or len(ids | targets) > 32 or len(loaded.header.source_heads) + 2 > 32:
            raise ValueError("Coding complete original graph plus two sources exceeds its bound")
        records = []
        for source, policy in (
            (self.rules.origin, self.rules.origin_policy),
            (self.rules.patch, self.rules.patch_policy),
        ):
            row = await session.get(BrainSource, (scope.company_id, source.source_id))
            resource = await session.get(
                BrainResource, (scope.company_id, source.resource.resource_id)
            )
            if row is None or resource is None or not resource.active or resource.kind != "source":
                raise ManagementDeniedError(
                    "Coding publication requires explicitly registered source resources"
                )
            record = source_record(row)
            if (
                SourceRegistration(
                    **record.model_dump(include=set(SourceRegistration.model_fields))
                )
                != source
                or record.authority_profile != policy.authority_profile
                or record.data_classification != policy.data_classification
            ):
                raise ManagementDeniedError("Coding publication registration/policy changed")
            await require_initial_readers(session, scope, source.resource, self.rules.readers)
            grants = tuple(
                (
                    await session.scalars(
                        select(BrainResourceAccess).where(
                            BrainResourceAccess.company_id == scope.company_id,
                            BrainResourceAccess.resource_id == source.resource.resource_id,
                            BrainResourceAccess.active.is_(True),
                        )
                    )
                ).all()
            )
            now = await db_now(session)
            if {
                row.principal_id for row in grants if row.expires_at is None or row.expires_at > now
            } != set(self.rules.readers):
                raise ManagementDeniedError(
                    "Coding initial output audience is unavailable or changed"
                )
            records.append(record)
        audiences = []
        for principal in self.rules.readers:
            member = await session.get(DirectoryMembership, (scope.company_id, principal))
            if member is None or not member.principal_active or not member.membership_active:
                raise ManagementDeniedError("Coding publication recipient is unavailable")
            recipient = scope.model_copy(update={"principal_id": principal})
            current_grants = await require_resources(
                session, recipient, tuple(sorted(ids | targets)), await db_now(session)
            )
            audiences.append((principal, current_grants))
        return PublicationAudience(sources=tuple(records), grants=tuple(audiences))

    async def _gate_locked(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: CompanyControlScope,
        owner: AuthenticatedWorkerIdentity,
        loaded: StoredCodingRequest,
        expected_hash: str,
        end: int,
    ) -> PublicationGate:
        """Cohesion exception: actual H/native/source/recipient joins retain their first end."""
        self._current(owner, end)
        header = loaded.header
        brain = owner_brain_scope(scope, owner.identity)
        end = min(
            end,
            await self.prepared.validate_loaded_locked(
                session,
                control,
                brain,
                loaded,
                owner,
                None,
                mode="owner",
                now=await db_now(session),
            ),
        )
        self._current(owner, end)
        native = await native_cost_selection(session, scope.company_id, header.action_id)
        self._current(owner, end)
        work, intent, hold = native.directory.work, native.intent, native.hold
        action = native.action
        require_action_header(action.proposal, header)
        if CLASSIFICATIONS.index(
            self.rules.origin_policy.data_classification
        ) < CLASSIFICATIONS.index(loaded.prepared.request.data_classification):
            raise ManagementDeniedError(
                "Coding output classification cannot lower its actual model input"
            )
        if (
            control.paused
            or (control.company_id, control.owner_id, control.price_version, control.policy_version)
            != (
                header.company_id,
                owner.identity.principal_id,
                loaded.prepared.request.price_version,
                action.proposal.policy_version,
            )
            or action.proposal_hash != expected_hash
            or action_hash(action.proposal) != expected_hash
            or action.consumed_at is None
            or action.approval is None
            or action.approval.decision != "approved"
            or action.approval.approver_id != control.owner_id
            or work is None
            or intent is None
            or intent.state != "succeeded"
            or intent.receipt is None
            or intent.attempt_kind != "model_requests"
            or len(intent.receipt.artifacts) != 1
            or intent.receipt.outcome != "succeeded"
            or hold is None
            or hold.state != "reconciled"
            or hold.actual_usd is None
            or work.worker_id is not None
            or work.expires_at is not None
            or work.state != "verifying"
            or work.fence <= intent.intent_fence
            or scope.principal_id not in intent.receipt.artifacts[0].allowed_principals
        ):
            raise ManagementDeniedError(
                "Coding publication needs actual known success/released native C/current owner"
            )
        require_native_result(loaded, native)
        audience = await self._audience(session, brain, loaded)
        self._current(owner, end)
        inputs = []
        for head in header.source_heads:
            row = await session.get(
                BrainSourceRevision, (scope.company_id, head.current.source_revision_id)
            )
            if row is None:
                raise ManagementDeniedError("Coding source disappeared before publication")
            inputs.append(await source_artifact_reference(session, brain, row.artifact_revision_id))
            self._current(owner, end)
        before = clock_us()
        now = await db_now(session)
        end = shorten(
            end,
            before,
            now,
            (
                *tuple(
                    grant.expires_at
                    for _, grants in audience.grants
                    for grant in grants
                    if grant.expires_at is not None
                ),
                owner.expires_at,
            ),
        )
        self._current(owner, end)
        return PublicationGate(native, audience, tuple(inputs), end, now)

    async def _gate(
        self,
        scope: CompanyControlScope,
        owner: AuthenticatedWorkerIdentity,
        loaded: StoredCodingRequest,
        expected_hash: str,
        end: int,
    ) -> PublicationGate:
        async with management_owner_transaction(self.factory, scope, owner.identity) as (
            session,
            control,
            _,
        ):
            return await self._gate_locked(
                session, control, scope, owner, loaded, expected_hash, end
            )

    def _physical(
        self, reference: ArtifactRef, action: UUID, request: UUID
    ) -> tuple[tuple[int, ...], ...]:
        path = self.evidence._path(reference.company_id, action, request)
        if reference.reference != str(path):
            raise ValueError("Coding model record has another path")
        result: list[tuple[int, ...]] = []
        for directory in (self.evidence._root, path.parent.parent, path.parent):
            row = directory.stat(follow_symlinks=False)
            if (
                not stat.S_ISDIR(row.st_mode)
                or stat.S_IMODE(row.st_mode) != 0o700
                or row.st_uid != os.getuid()
                or directory.resolve() != directory
            ):
                raise ValueError("Coding model record directory is not private/owned")
            result.append((row.st_dev, row.st_ino, row.st_mode, row.st_uid))
        row = path.stat(follow_symlinks=False)
        if (
            not stat.S_ISREG(row.st_mode)
            or stat.S_IMODE(row.st_mode) != 0o400
            or row.st_uid != os.getuid()
            or row.st_nlink != 1
        ):
            raise ValueError("Coding model record is not immutable/private")
        result.append(
            (
                row.st_dev,
                row.st_ino,
                row.st_mode,
                row.st_uid,
                row.st_nlink,
                row.st_size,
                row.st_mtime_ns,
                row.st_ctime_ns,
            )
        )
        return tuple(result)

    async def publish(
        self,
        scope: CompanyControlScope,
        owner: AuthenticatedWorkerIdentity,
        action_id: UUID,
        expected_hash: str,
        *,
        expected_goal: GoalRevisionRef,
        expected_current_revision_id: UUID,
        end_us: int,
    ) -> CodingPublicationRead:
        """Cohesion exception: no new private phase may lose its original owner or read end."""
        end = cost_read_end(scope, owner, end_us)
        self._current(owner, end)
        if (scope.company_id, action_id) != (self.rules.company_id, self.rules.action_id):
            raise ManagementDeniedError(
                "Coding publisher accepts only its configured native C action"
            )
        loaded = await self._owned(
            self.prepared.load_owner(scope, owner, action_id, end_us=end), owner, end
        )
        end = min(end, loaded.read_end_us)
        if (
            loaded.header.goal != expected_goal
            or loaded.header.plan.plan_revision_id != expected_current_revision_id
        ):
            raise ManagementDeniedError("Coding publication Goal/head CAS differs")
        initial = await self._owned(
            self._gate(scope, owner, loaded, expected_hash, end), owner, end
        )
        end = min(end, initial.end)
        intent = initial.native.intent
        assert intent is not None and intent.receipt is not None
        reference = intent.receipt.artifacts[0]
        before = await self._owned(
            asyncio.to_thread(
                self._physical, reference, action_id, loaded.header.parameters.request_id
            ),
            owner,
            end,
        )
        record = await self._owned(self.evidence.load_record(reference), owner, end)
        after = await self._owned(
            asyncio.to_thread(
                self._physical, reference, action_id, loaded.header.parameters.request_id
            ),
            owner,
            end,
        )
        if before != after:
            raise ManagementDeniedError("Coding protected model record changed during read")
        origin = model_origin(
            loaded, initial.native, record.evidence, self.catalog.models, wire=record.wire
        )
        if self.repository.selection_sha256 != canonical_sha256(
            repository_selection(loaded.prepared)
        ):
            raise ManagementDeniedError("Coding publication repository nomination differs")
        root = self.admission.procedure.binding
        brain = owner_brain_scope(scope, owner.identity).model_copy(
            update={
                "task_id": root.task_id,
                "task_trace_id": root.trace_id,
                "actor_id": owner.identity.principal_id,
            }
        )
        material = await self._owned(self.repository.read(brain, end_us=end), owner, end)
        end = min(end, material.read_end_us)
        originals = require_coding_sources(
            loaded.prepared.binding, loaded.prepared.context, loaded.prepared.sources
        )
        if (
            material.value.source != loaded.header.repository_source
            or material.value.selection_sha256 != loaded.header.repository_selection_sha256
            or tuple(row.metadata for row in material.value.files)
            != loaded.prepared.binding.source_files
            or {row.metadata.path: row.text.encode() for row in material.value.files} != originals
        ):
            raise ManagementDeniedError(
                "Actual coding committed source bytes differ from protected input"
            )
        pair = await self._owned(
            asyncio.to_thread(
                prepare_pair,
                origin,
                self.rules,
                self.blobs.storage_symbol,
                initial.observed_at,
                initial.inputs,
            ),
            owner,
            min(
                end,
                clock_us()
                + min(
                    self.rules.origin_policy.parse_timeout_seconds,
                    self.rules.patch_policy.parse_timeout_seconds,
                )
                * 1_000_000,
            ),
        )
        for value in (pair.origin, pair.patch):
            ref = ArtifactRevisionRef(
                **value.artifact.model_dump(include=set(ArtifactRevisionRef.model_fields))
            )
            await self._owned(self.blobs.save(ref, value.artifact.raw_text.encode()), owner, end)
        return await self._owned(
            self._publish(scope, owner, loaded, expected_hash, initial, pair, end), owner, end
        )

    async def _publish(
        self,
        scope: CompanyControlScope,
        owner: AuthenticatedWorkerIdentity,
        loaded: StoredCodingRequest,
        expected_hash: str,
        initial: PublicationGate,
        pair: PublicationPair,
        end: int,
    ) -> CodingPublicationRead:
        async with management_owner_transaction(self.factory, scope, owner.identity) as (
            session,
            control,
            _,
        ):
            final = await self._gate_locked(
                session, control, scope, owner, loaded, expected_hash, end
            )
            initial.require_same(final)
            end = min(end, initial.end, final.end)
            self._current(owner, end)
            brain = owner_brain_scope(scope, owner.identity)
            await append_pair(session, brain, pair, self.rules, final.observed_at)
            self._current(owner, end)
            await artifact_input_closure(
                session, brain, (pair.value.patch.artifact.artifact_revision_id,)
            )
            current = await self._gate_locked(
                session, control, scope, owner, loaded, expected_hash, end
            )
            initial.require_same(current)
            end = min(end, current.end)
            raw = pair.value.model_dump_json(by_alias=True)
            if len(raw.encode()) > 32_768:
                raise ValueError("Complete coding publication response exceeds bound")
            self._current(owner, end)
        self._current(owner, end)
        return CodingPublicationRead(pair.value, end)

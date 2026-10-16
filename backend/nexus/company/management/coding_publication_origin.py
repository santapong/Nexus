"""Concrete E/EV READ of the actual published C pair; decoded data is never permission.

Cohesion exception: first native/source admission, actual protected IO ownership,
immutable pair replay and final current revalidation form one closed read boundary.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
from collections.abc import Awaitable
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.builder.engineering_bodies import (
    CompleteEngineeringBody,
    _metadata,
    revalidate_complete_engineering_artifact_locked,
)
from nexus.builder.execution_contracts import BuilderExecutionSpec
from nexus.company.access import VerifiedIdentity
from nexus.company.brain.artifact_contracts import ArtifactSlice
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.base import BrainReadScope, ValueContract
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.ingestion_store import PreparedIngest
from nexus.company.brain.native_fact_inputs import source_artifact_reference
from nexus.company.brain.scope_support import BrainDeniedError, brain_transaction
from nexus.company.brain.source_models import BrainSourceRevision
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.acceptance_freshness import (
    QualifiedFreshness,
    RegisteredSourceFreshness,
)
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.coding_prepared_checks import (
    require_code_metadata,
    shorten,
    source_read,
)
from nexus.company.management.coding_publication_contracts import (
    CodingModelOrigin,
    CodingPublicationRules,
    PublishedCodingPatch,
)
from nexus.company.management.coding_publication_origin_native import (
    OriginSelection,
    read_origin_selection,
    require_origin_native,
)
from nexus.company.management.coding_publication_rows import (
    PublicationPair,
    prepare_pair,
    replay_pair,
)
from nexus.company.management.cycle_cost_contracts import NativeCostSelection
from nexus.company.management.lifecycle import PlanRevisionRef
from nexus.company.management.nexus_coding_catalog import validate_nexus_coding_catalog
from nexus.company.management.owner_view_sources import OwnerViewSources
from nexus.company.management.plan_catalog import PlanAdmissionCatalog
from nexus.company.management.planning_native_facts import clock_us, require_time
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import (
    db_now,
    execution_row,
    lease_scope,
)
from nexus.harness.journal_models import CompanyControl, JournalAction
from nexus.harness.model_authorizer_contracts import ModelInputRecipe


@dataclass(slots=True)
class _ReadStop:
    """Per-call stop scheduling, never a credential, proof or shared-reader poison."""

    stopped: bool = False
    first_error: BaseException | None = None


_READ_STOP: ContextVar[_ReadStop | None] = ContextVar("coding_origin_read_stop", default=None)


@dataclass(frozen=True, slots=True, eq=False)
class CodingOriginRead:
    """Only the reader's actual issuance identity can license later locked revalidation."""

    origin: CodingModelOrigin
    bodies: tuple[CompleteEngineeringBody, ...]
    pair: PublicationPair
    selection: OriginSelection
    read_end_us: int


def coding_scope(
    lease: ExecutionLease, credential: AuthenticatedWorkerIdentity, action: UUID
) -> BrainReadScope:
    """Use the actual E/EV actor; never substitute the original C owner."""
    return BrainReadScope(
        company_id=lease.company_id,
        workspace_id=lease.workspace_id,
        principal_id=credential.identity.principal_id,
        operation_id=action,
        trace_id=lease.trace_id,
        task_id=lease.task_id,
        task_trace_id=lease.trace_id,
        actor_id=lease.actor_id,
    )


class _ReadMaterial(ValueContract):
    origin: CodingModelOrigin
    first: tuple[ArtifactSlice, ...]
    raw_sha256s: tuple[str, ...]
    freshness: tuple[tuple[QualifiedFreshness, ...], ...]
    native: NativeCostSelection
    references: tuple[ArtifactRevisionRef, ...]
    inputs: tuple[ArtifactRevisionRef, ...]
    owner_id: UUID
    source_signature: str
    root_registration_sha256: str
    plan: PlanRevisionRef
    end_us: int
    pair: tuple[PreparedIngest, PreparedIngest]
    pair_inputs: tuple[ArtifactRevisionRef, ...]
    pair_resources: tuple[UUID, ...]
    pair_value: PublishedCodingPatch
    first_end_us: int


class CodingPublicationOriginReader:
    """One sealed concrete graph; IO leaves remain reachable after caller cancellation.

    Cohesion exception: this complete original/current source/native read is kept
    adjacent so no partial DTO, renewed expiry or callback can grant E/EV admission.
    """

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        catalog: PlanAdmissionCatalog,
        artifacts: BoundedArtifactReader,
        freshness: RegisteredSourceFreshness,
        *,
        rules: CodingPublicationRules,
        recipe: ModelInputRecipe,
    ) -> None:
        admission = validate_nexus_coding_catalog(catalog.nexus_coding_admission, catalog)
        if (
            admission is None
            or type(artifacts) is not BoundedArtifactReader
            or type(artifacts.blobs) is not ProtectedBlobStore
            or type(freshness) is not RegisteredSourceFreshness
            or artifacts.factory is not factory
            or freshness._factory is not factory
            or rules.company_id != catalog.company_id
        ):
            raise ValueError("Coding origin requires the shared concrete full10 Brain graph")
        self.factory, self.catalog, self.artifacts, self.freshness = (
            factory,
            catalog,
            artifacts,
            freshness,
        )
        blobs = artifacts.blobs
        if type(blobs) is not ProtectedBlobStore:
            raise ValueError("Actual concrete Brain blob store is required")
        self.blobs = blobs
        self._storage = (blobs._root, blobs.storage_symbol)
        self.rules = CodingPublicationRules.model_validate_json(rules.model_dump_json())
        self.recipe = recipe
        self.sources = OwnerViewSources(artifacts, freshness)
        self.admission = admission
        self._objects = (
            factory,
            catalog,
            artifacts,
            artifacts.blobs,
            freshness,
            freshness._policies,
            recipe,
            self.sources,
        )
        self._pin = (
            canonical_sha256(catalog),
            canonical_sha256(self.rules),
            canonical_sha256(recipe),
        )
        self._operations: list[
            tuple[
                ExecutionLease,
                AuthenticatedWorkerIdentity,
                BuilderExecutionSpec,
                str,
                str,
                VerifiedIdentity,
                datetime,
                datetime,
            ]
        ] = []
        self._owners: list[asyncio.Task[object]] = []
        self._issued: list[
            tuple[
                CodingOriginRead,
                ExecutionLease,
                AuthenticatedWorkerIdentity,
                BuilderExecutionSpec,
                str,
            ]
        ] = []
        self.require_composition()

    def require_composition(self) -> None:
        """Retain actual source/storage/factory/policy objects and immutable values."""
        actual = (
            self.factory,
            self.catalog,
            self.artifacts,
            self.artifacts.blobs,
            self.freshness,
            self.freshness._policies,
            self.recipe,
            self.sources,
        )
        if (
            any(a is not b for a, b in zip(actual, self._objects, strict=True))
            or (
                canonical_sha256(self.catalog),
                canonical_sha256(self.rules),
                canonical_sha256(self.recipe),
            )
            != self._pin
            or self.artifacts.blobs is not self.blobs
            or (self.blobs._root, self.blobs.storage_symbol) != self._storage
            or self.sources.artifacts is not self.artifacts
            or self.sources.freshness is not self.freshness
            or self.artifacts.factory is not self.factory
            or self.freshness._factory is not self.factory
            or validate_nexus_coding_catalog(self.catalog.nexus_coding_admission, self.catalog)
            != self.admission
        ):
            raise ValueError("Original coding origin reader graph changed")
        for policy in (self.rules.origin_policy, self.rules.patch_policy):
            if self.freshness._policies.policy(policy.source_symbol) != policy:
                raise ValueError("Original generated source policy differs")

    def pending_owners(self) -> tuple[asyncio.Task[object], ...]:
        """Actual wrapper and blob leaves; cancellation is not resource settlement."""
        own = tuple(task for task in self._owners if not task.done() or task.cancelled())
        blobs = self.artifacts.blobs
        if type(blobs) is not ProtectedBlobStore:
            raise ValueError("Original concrete Brain blob store changed")
        return tuple(dict.fromkeys((*own, *blobs.pending_owners())))

    def _current(self, credential: AuthenticatedWorkerIdentity, end_us: int) -> None:
        operation = _READ_STOP.get()
        if operation is not None and operation.stopped:
            raise ValueError("Original coding origin read has stopped")
        self.require_composition()
        require_time(end_us)
        credential.require_time(datetime.now(UTC))
        for (
            lease,
            original,
            spec,
            lease_wire,
            spec_wire,
            identity,
            issued,
            expires,
        ) in self._operations:
            if original is credential and (
                lease.model_dump_json() != lease_wire
                or spec.model_dump_json() != spec_wire
                or (credential.identity, credential.issued_at, credential.expires_at)
                != (identity, issued, expires)
            ):
                raise ValueError("Original coding actor/lease/spec values changed across IO")
        require_time(end_us)
        credential.require_time(datetime.now(UTC))

    async def _checked[T](
        self, call: Awaitable[T], credential: AuthenticatedWorkerIdentity, end_us: int
    ) -> T:
        """Stop a metadata chain after its first late await; retain its actual outer owner."""
        try:
            self._current(credential, end_us)
        except BaseException:
            if inspect.iscoroutine(call):
                call.close()
            raise
        result = await call
        self._current(credential, end_us)
        return result

    async def _page(
        self,
        scope: BrainReadScope,
        credential: AuthenticatedWorkerIdentity,
        reference: ArtifactRevisionRef,
        offset: int,
        end_us: int,
    ) -> ArtifactSlice:
        """Same strict four UTF8 attempts; each potential private retry checks THIS read."""
        maximum = min(16384, reference.byte_length - offset)
        if not 0 < maximum <= 16384:
            raise ValueError("Coding origin page offset exceeds its original bound")
        for retreat in range(4):
            self._current(credential, end_us)
            try:
                value = await self.artifacts.bounded_artifact(
                    scope,
                    credential.identity,
                    reference.artifact_revision_id,
                    start_byte=offset,
                    max_bytes=maximum - retreat,
                    include_history=False,
                )
            except BrainDeniedError as error:
                if (
                    str(error) != "Artifact byte boundary splits UTF8 content"
                    or type(error.__cause__) is not UnicodeDecodeError
                    or retreat == min(3, maximum - 1)
                ):
                    raise
                self._current(credential, end_us)  # BEFORE another actual private attempt.
                continue
            self._current(credential, end_us)
            value = ArtifactSlice.model_validate_json(value.model_dump_json())
            if (
                value.company_id != scope.company_id
                or value.artifact != reference
                or value.source_state != "current"
                or value.span.start_byte != offset
                or value.span.end_byte != offset + maximum - retreat
            ):
                raise ValueError("Actual coding publication page binding differs")
            self._current(credential, end_us)
            return value
        raise AssertionError("Four strict coding UTF8 attempts cannot fall through")

    async def _body(
        self,
        scope: BrainReadScope,
        credential: AuthenticatedWorkerIdentity,
        reference: ArtifactRevisionRef,
        end_us: int,
    ) -> CompleteEngineeringBody:
        """Schedule pages only while this ORIGINAL call is live; admitted leaves settle.

        The ordinary complete engineering page/snapshot checks are reused. The
        caller's stop token is checked after EACH admitted page, before freshness
        or any later page. No actual blob/SQL leaf is cancelled or window renewed.
        """
        first = None
        qualified: tuple[QualifiedFreshness, ...] = ()
        raw = bytearray()
        for _ in range(33):
            self._current(credential, end_us)
            page = await self._page(scope, credential, reference, len(raw), end_us)
            self._current(credential, end_us)
            if first is None:
                first = page
                qualified = await self._checked(
                    self.freshness.prepare(scope, credential.identity, (first,)), credential, end_us
                )
            elif _metadata(page) != _metadata(first):
                raise ValueError("Coding publication page snapshot changed")
            raw.extend(page.text.encode())
            if len(raw) > reference.byte_length:
                raise ValueError("Coding publication page exceeds its original bound")
            if not page.has_more:
                break
        if first is None or len(raw) != reference.byte_length:
            raise ValueError("Coding publication full body is incomplete")
        result = CompleteEngineeringBody(first, bytes(raw), qualified)
        self._current(credential, end_us)
        async with brain_transaction(self.factory, scope, credential.identity) as (
            session,
            control,
            _,
        ):
            await self._checked(
                revalidate_complete_engineering_artifact_locked(
                    self.artifacts,
                    session,
                    control,
                    scope,
                    credential.identity,
                    first,
                    await db_now(session),
                ),
                credential,
                end_us,
            )
            await self._checked(
                self.freshness.revalidate(session, scope, qualified, await db_now(session)),
                credential,
                end_us,
            )
        self._current(credential, end_us)
        return result

    async def _owned[T](
        self, call: Awaitable[T], credential: AuthenticatedWorkerIdentity, end_us: int
    ) -> T:
        try:
            self._current(credential, end_us)
        except BaseException:
            if inspect.iscoroutine(call):
                call.close()
            raise

        async def run() -> T:
            return await call

        task = asyncio.create_task(run())
        # Task covariance is kept by a separate done observer; owners accept heterogeneous results.
        self._owners.append(cast(asyncio.Task[object], task))
        task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        try:
            result = await asyncio.wait_for(
                asyncio.shield(task), max(0, (end_us - clock_us()) / 1_000_000)
            )
        except BaseException as first:
            operation = _READ_STOP.get()
            if operation is not None:
                if operation.first_error is None:
                    operation.first_error = first
                operation.stopped = True
            raise
        self._current(credential, end_us)
        return result

    def _role(self, lease: ExecutionLease, credential: AuthenticatedWorkerIdentity) -> None:
        self.require_composition()
        slots = self.admission.slots[5:7]
        expected = next(
            (row.child.binding for row in slots if row.work.task_id == lease.task_id), None
        )
        if (
            expected is None
            or not isinstance(credential, AuthenticatedWorkerIdentity)
            or credential.identity.principal_id != lease.actor_id
            or credential.identity.workspace_id != lease.workspace_id
            or lease.mode != "execute"
            or lease.expires_at > credential.expires_at
            or (
                lease.company_id,
                lease.task_id,
                lease.trace_id,
                lease.run_id,
                lease.actor_id,
                lease.workspace_id,
            )
            != (
                expected.company_id,
                expected.task_id,
                expected.trace_id,
                expected.run_id,
                expected.actor_id,
                expected.workspace_id,
            )
        ):
            raise ValueError("Coding origin requires its actual independent E/EV lease and actor")

    def _fingerprint(self, proof: CodingOriginRead) -> str:
        return canonical_sha256(
            _ReadMaterial(
                origin=proof.origin,
                first=tuple(b.first for b in proof.bodies),
                raw_sha256s=tuple(hashlib.sha256(b.raw).hexdigest() for b in proof.bodies),
                freshness=tuple(b.freshness for b in proof.bodies),
                native=proof.selection.native,
                references=proof.selection.references,
                inputs=proof.selection.inputs,
                owner_id=proof.selection.owner_id,
                source_signature=proof.selection.source_signature,
                root_registration_sha256=proof.selection.root_registration_sha256,
                plan=proof.selection.plan,
                end_us=proof.read_end_us,
                pair=(proof.pair.origin, proof.pair.patch),
                pair_inputs=proof.pair.inputs,
                pair_resources=proof.pair.resources,
                pair_value=proof.pair.value,
                first_end_us=proof.selection.end_us,
            )
        )

    def require_loaded(
        self,
        proof: CodingOriginRead,
        lease: ExecutionLease,
        credential: AuthenticatedWorkerIdentity,
        spec: BuilderExecutionSpec,
    ) -> None:
        """Only the actual original read, actor witness and unchanged spec are usable."""
        self._role(lease, credential)
        found = next((row for row in self._issued if row[0] is proof), None)
        if (
            found is None
            or found[1:4] != (lease, credential, spec)
            or found[2] is not credential
            or found[4] != self._fingerprint(proof)
        ):
            raise ValueError("Coding origin requires its actual issued read and original witness")
        self._current(credential, proof.read_end_us)

    async def load(
        self,
        lease: ExecutionLease,
        credential: AuthenticatedWorkerIdentity,
        spec: BuilderExecutionSpec,
        *,
        end_us: int,
    ) -> CodingOriginRead:
        """Public per-read scheduling ownership; stopping one call never stops the store."""
        operation = _ReadStop()
        token = _READ_STOP.set(operation)
        try:
            return await self._load(lease, credential, spec, end_us=end_us)
        except BaseException as first:
            if operation.first_error is None:
                operation.first_error = first
            operation.stopped = True
            raise
        finally:
            _READ_STOP.reset(token)

    async def _load(
        self,
        lease: ExecutionLease,
        credential: AuthenticatedWorkerIdentity,
        spec: BuilderExecutionSpec,
        *,
        end_us: int,
    ) -> CodingOriginRead:
        """One original bounded read; no page/stage renewal and no raw model-file access."""
        self._role(lease, credential)
        BuilderExecutionSpec.model_validate(spec.model_dump(warnings=False))
        if (
            spec.job.company_id,
            spec.job.task_id,
            spec.job.trace_id,
            spec.job.run_id,
            spec.job.actor_id,
            spec.job.workspace_id,
        ) != (
            lease.company_id,
            lease.task_id,
            lease.trace_id,
            lease.run_id,
            lease.actor_id,
            lease.workspace_id,
        ):
            raise ValueError("Coding origin spec belongs to another actual E/EV job")
        if len(self._operations) >= 64:
            raise ValueError("Coding origin operation bound exhausted")
        self._operations.append(
            (
                lease,
                credential,
                spec,
                lease.model_dump_json(),
                spec.model_dump_json(),
                credential.identity,
                credential.issued_at,
                credential.expires_at,
            )
        )
        end = min(end_us, clock_us() + 30_000_000)
        self._current(credential, end)
        scope = coding_scope(lease, credential, spec.job.action_id)

        async def first() -> OriginSelection:
            async with brain_transaction(self.factory, scope, credential.identity) as (
                session,
                control,
                _,
            ):
                return await read_origin_selection(
                    self, session, control, lease, credential, spec, end
                )

        selected = await self._owned(first(), credential, end)
        end = min(end, selected.end_us)
        bodies = []
        for reference in selected.references:
            bodies.append(
                await self._owned(
                    self._body(scope, credential, reference, end),
                    credential,
                    end,
                )
            )
        origin = CodingModelOrigin.model_validate_json(bodies[0].raw)
        require_origin_native(self, origin, selected, spec)
        if bodies[1].raw != origin.content.patch.encode():
            raise ValueError("Published raw patch differs from actual model-origin content")
        blobs = self.artifacts.blobs
        if type(blobs) is not ProtectedBlobStore:
            raise ValueError("Original concrete Brain blob store changed")
        pair = await self._owned(
            asyncio.to_thread(
                prepare_pair,
                origin,
                self.rules,
                blobs.storage_symbol,
                origin.checked_at,
                selected.inputs,
            ),
            credential,
            end,
        )
        proof = CodingOriginRead(origin, tuple(bodies), pair, selected, end)
        if len(self._issued) >= 64:
            raise ValueError("Coding origin reader issuance bound exhausted")

        async def final() -> int:
            async with brain_transaction(self.factory, scope, credential.identity) as (
                session,
                control,
                _,
            ):
                work = await execution_row(session, lease_scope(lease))
                action = await session.get(JournalAction, spec.job.action_id)
                if action is None:
                    raise ValueError("Actual E/EV action disappeared")
                return await self._validate_material(
                    session, control, work, action, proof, lease, credential, spec
                )

        final_end = await self._owned(final(), credential, end)
        # Do not replace the issued object or increase its source window.
        if final_end < end:
            proof = CodingOriginRead(origin, tuple(bodies), pair, selected, final_end)
        fingerprint = self._fingerprint(proof)
        self._current(credential, proof.read_end_us)
        self._issued.append((proof, lease, credential, spec, fingerprint))
        self.require_loaded(proof, lease, credential, spec)
        return proof

    async def revalidate_locked(
        self,
        session: AsyncSession,
        control: CompanyControl,
        work: ExecutionWork,
        action: JournalAction,
        proof: CodingOriginRead,
        *,
        now: datetime,
    ) -> int:
        """Only metadata/complete provenance revalidation under the caller's native lock."""
        found = next((row for row in self._issued if row[0] is proof), None)
        if found is None:
            raise ValueError("Unissued coding origin read")
        _, lease, credential, spec, _ = found
        self.require_loaded(proof, lease, credential, spec)
        return await self._validate_material(
            session, control, work, action, proof, lease, credential, spec
        )

    async def _validate_material(
        self,
        session: AsyncSession,
        control: CompanyControl,
        work: ExecutionWork,
        action: JournalAction,
        proof: CodingOriginRead,
        lease: ExecutionLease,
        credential: AuthenticatedWorkerIdentity,
        spec: BuilderExecutionSpec,
    ) -> int:
        """Closed internal staged/current material check; no caller can register a read here."""
        end = proof.read_end_us
        self._role(lease, credential)
        self._current(credential, end)
        if work.task_id != lease.task_id or action.id != spec.job.action_id:
            raise ValueError("Origin read is bound to another actual E/EV job")
        current = await self._checked(
            read_origin_selection(
                self, session, control, lease, credential, spec, proof.read_end_us
            ),
            credential,
            end,
        )
        if (
            current.native,
            current.references,
            current.inputs,
            current.owner_id,
            current.source_signature,
            current.root_registration_sha256,
            current.plan,
        ) != (
            proof.selection.native,
            proof.selection.references,
            proof.selection.inputs,
            proof.selection.owner_id,
            proof.selection.source_signature,
            proof.selection.root_registration_sha256,
            proof.selection.plan,
        ):
            raise ValueError("Original C native or publication changed during protected read")
        require_origin_native(self, proof.origin, current, spec)
        scope = coding_scope(lease, credential, action.id)
        await self._checked(
            require_code_metadata(session, scope, proof.origin.header),
            credential,
            proof.read_end_us,
        )
        expected_inputs = []
        for head in proof.origin.header.source_heads:
            row = await self._checked(
                session.get(
                    BrainSourceRevision, (scope.company_id, head.current.source_revision_id)
                ),
                credential,
                proof.read_end_us,
            )
            if row is None or row.source_id != head.source_id:
                raise ValueError("Original C source/artifact input disappeared")
            expected_inputs.append(
                await self._checked(
                    source_artifact_reference(session, scope, row.artifact_revision_id),
                    credential,
                    proof.read_end_us,
                )
            )
        if (
            len(set(expected_inputs)) != len(expected_inputs)
            or set(current.inputs) != set(expected_inputs)
            or set(proof.pair.inputs) != set(expected_inputs)
        ):
            raise ValueError("Published origin contains missing or extra original C inputs")
        before = clock_us()
        source_windows = await self._checked(
            source_read(
                session,
                control,
                coding_scope(lease, credential, action.id),
                credential.identity,
                proof.origin.header,
                self.sources,
            ),
            credential,
            end,
        )
        current_end = shorten(
            current.end_us,
            before,
            await self._checked(db_now(session), credential, end),
            source_windows,
        )
        end = min(end, current_end)
        for body in proof.bodies:
            await self._checked(
                revalidate_complete_engineering_artifact_locked(
                    self.artifacts,
                    session,
                    control,
                    coding_scope(lease, credential, action.id),
                    credential.identity,
                    body.first,
                    await self._checked(db_now(session), credential, end),
                ),
                credential,
                end,
            )
            await self._checked(
                self.freshness.revalidate(
                    session,
                    coding_scope(lease, credential, action.id),
                    body.freshness,
                    await self._checked(db_now(session), credential, end),
                ),
                credential,
                end,
            )
        if not await self._checked(
            replay_pair(
                session, coding_scope(lease, credential, action.id), proof.pair, self.rules
            ),
            credential,
            end,
        ):
            raise ValueError("Actual immutable publication pair is missing")
        self._current(credential, current_end)
        return current_end

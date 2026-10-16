"""Real repository/source proof and immutable C preparation, before native pending input.

Cohesion exception: current and historical reads share original owned private I/O,
identity/deadline fences and native markers. No loaded DTO or orphan file is a permit.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.context_store import PersistentContextAssembler
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.brain.scope_support import brain_transaction
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.coding_intent import PreparedCodingRequest, require_coding_registry
from nexus.company.management.coding_prepared_checks import (
    CodingNative,
    action_sources,
    current_native,
    require_native_header,
    shorten,
    source_read,
)
from nexus.company.management.coding_prepared_contracts import (
    CodingHeaderRead,
    CodingPreparedHeader,
    CodingPreparedRef,
    StoredCodingRequest,
    decode_header,
    encode_prepared,
    header_for,
    header_reference,
    prepared_reference,
    repository_selection,
    require_body,
)
from nexus.company.management.coding_repository import CodingRepositoryReader
from nexus.company.management.coding_sources import require_coding_sources
from nexus.company.management.owner_view_sources import OwnerViewSources, owner_brain_scope
from nexus.company.management.planning_authority import ManagementPlanningAuthority
from nexus.company.management.planning_native_facts import clock_us, read_end, require_time
from nexus.company.management.planning_prepared_store import PlanningPreparedStore
from nexus.company.management.transactions import (
    ManagementDeniedError,
)
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.management_services import ManagementExecutionServices
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import CompanyControl, JournalAction
from nexus.harness.model_authorizer_contracts import ModelInputRecipe, model_action_parameters

Mode = Literal["owner", "actor", "worker"]


class CodingPreparedStore:
    """Concrete per-operation source reader and retained native/private resource graph.

    The cohesive >300-line class keeps issuance seals private and brackets every
    actual read/write with the same native/source/credential cutoff. It never
    submits/approves an action, claims a lease, or spends/replenishes allowance.
    """

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        management: ManagementExecutionServices,
        contexts: PersistentContextAssembler,
        blobs: ProtectedBlobStore,
        sources: OwnerViewSources,
        recipe: ModelInputRecipe,
        repository: CodingRepositoryReader,
    ) -> None:
        if (
            type(management) is not ManagementExecutionServices
            or type(contexts) is not PersistentContextAssembler
            or type(contexts._retriever) is not PersistentBrainRetriever
            or contexts._retriever.factory is not factory
            or type(sources.freshness) is not RegisteredSourceFreshness
            or sources.freshness._factory is not factory
            or type(contexts._authority) is not ManagementPlanningAuthority
            or type(contexts._retriever.blobs) is not ProtectedBlobStore
            or type(repository) is not CodingRepositoryReader
            or contexts._factory is not factory
            or contexts._authority.management is not management
            or management.artifacts is not sources.artifacts
            or management.freshness is not sources.freshness
            or contexts._retriever.blobs is not sources.artifacts.blobs
            or contexts._authority.recipe != recipe
            or management.catalog.nexus_coding_admission is None
        ):
            raise ValueError("Coding store requires its original concrete C/source/native graph")
        policy = contexts._authority.policy
        if (policy.workflow_name, policy.workflow_version, policy.model_profile) != (
            "company.coding.v1",
            "v1",
            "engineering",
        ):
            raise ValueError("Coding store cannot borrow another role authority")
        self._authority = contexts._authority
        self._source_blobs = contexts._retriever.blobs
        self.factory, self.management, self.contexts = factory, management, contexts
        self.blobs, self.sources, self.repository = blobs, sources, repository
        self.recipe = ModelInputRecipe.model_validate_json(recipe.model_dump_json())
        self._io = PlanningPreparedStore(factory, blobs, sources, recipe)
        self._stopped = False
        self._issued: list[
            tuple[
                StoredCodingRequest, AuthenticatedWorkerIdentity, ExecutionLease | None, Mode, str
            ]
        ] = []
        self._objects = (
            factory,
            management,
            contexts,
            blobs,
            sources,
            repository,
            contexts._authority,
            contexts._retriever,
        )
        self._pins = self._values()
        self.require_composition()

    def _values(self) -> tuple[object, ...]:
        return (
            canonical_sha256(self.management.catalog),
            self.recipe.model_dump_json(),
            self.repository.selection_sha256,
            self._authority.policy,
            self.sources.artifacts.blobs,
            self.sources.freshness,
        )

    def require_composition(self) -> None:
        self._io._composition()
        if (
            any(
                a is not b
                for a, b in zip(
                    self._objects,
                    (
                        self.factory,
                        self.management,
                        self.contexts,
                        self.blobs,
                        self.sources,
                        self.repository,
                        self.contexts._authority,
                        self.contexts._retriever,
                    ),
                    strict=True,
                )
            )
            or self._values() != self._pins
            or self._io.factory is not self.factory
            or self._io.blobs is not self.blobs
            or self._io.sources is not self.sources
            or self.management.artifacts is not self.sources.artifacts
            or self.management.freshness is not self.sources.freshness
            or self.contexts._authority is not self._authority
            or self.contexts._retriever.blobs is not self._source_blobs
        ):
            raise ManagementDeniedError("Original coding store composition changed")
        self._authority._require_original()

    def request_stop(self) -> None:
        self._stopped = True
        self._io.request_stop()
        self.repository.request_stop()

    def pending_owners(self) -> tuple[asyncio.Task[object], ...]:
        return tuple(
            dict.fromkeys(
                (
                    *self._io.pending_owners(),
                    *self.blobs.pending_owners(),
                    *self._source_blobs.pending_owners(),
                    *self.repository.pending_owners(),
                )
            )
        )

    def _current(self, credential: AuthenticatedWorkerIdentity, end: int) -> None:
        self.require_composition()
        require_time(end)
        if self._stopped or type(credential) is not AuthenticatedWorkerIdentity:
            raise ManagementDeniedError("Coding requires its original unstopped authenticated read")
        credential.require_time(datetime.now(UTC))

    def _end(
        self, credential: AuthenticatedWorkerIdentity, lease: ExecutionLease | None, end: int
    ) -> int:
        self._current(credential, end)
        windows = (credential.expires_at, *((lease.expires_at,) if lease is not None else ()))
        return shorten(read_end(end), clock_us(), datetime.now(UTC), windows)

    async def _owned[T](
        self, value: Awaitable[T], credential: AuthenticatedWorkerIdentity, end: int
    ) -> T:
        try:
            self._current(credential, end)
        except BaseException:
            if inspect.iscoroutine(value):
                value.close()
            raise
        try:
            result = await self._io._owned(value, end)
            self._current(credential, end)
            return result
        except BaseException as first:
            self.request_stop()
            first.__dict__["_nexus_coding_prepared_pending"] = self.pending_owners()
            raise

    async def _native(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        credential: AuthenticatedWorkerIdentity,
        task: UUID,
        action: UUID,
        lease: ExecutionLease | None,
        mode: Mode,
    ) -> CodingNative:
        return await current_native(
            session,
            control,
            scope,
            credential.identity,
            self.management.catalog,
            task,
            action,
            self.recipe,
            lease=lease,
            mode=mode,
        )

    async def _checked_locked(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        credential: AuthenticatedWorkerIdentity,
        header: CodingPreparedHeader,
        lease: ExecutionLease | None,
        mode: Mode,
        end: int,
        *,
        saving: bool = False,
    ) -> tuple[CodingNative, int]:
        self._current(credential, end)
        native = await self._native(
            session, control, scope, credential, header.task_id, header.action_id, lease, mode
        )
        admission = self.management.catalog.nexus_coding_admission
        assert admission is not None
        require_native_header(native, header, admission, self.recipe)
        if (saving and (control.paused or native.current.proposal is not None)) or (
            not saving and native.current.proposal is None
        ):
            raise ManagementDeniedError("Coding pending input cannot be recreated or omitted")
        model = next(
            (
                row
                for row in self.management.catalog.models.models
                if row.registry_id == header.parameters.registry_id
            ),
            None,
        )
        if (
            model is None
            or header.registry_sha256 != canonical_sha256(self.management.catalog.models)
            or header.model_sha256 != canonical_sha256(model)
        ):
            raise ManagementDeniedError("Coding original registry/model financial proof changed")
        windows = await source_read(
            session, control, scope, credential.identity, header, self.sources
        )
        final = await self._native(
            session, control, scope, credential, header.task_id, header.action_id, lease, mode
        )
        require_native_header(final, header, admission, self.recipe)
        if final != native:
            raise ManagementDeniedError("Coding native state changed during source checks")
        before, now = clock_us(), await db_now(session)
        end = shorten(
            end,
            before,
            now,
            (*windows, credential.expires_at, *((lease.expires_at,) if lease else ())),
        )
        self._current(credential, end)
        return native, end

    async def _checked(
        self,
        scope: BrainReadScope,
        credential: AuthenticatedWorkerIdentity,
        header: CodingPreparedHeader,
        lease: ExecutionLease | None,
        mode: Mode,
        end: int,
        *,
        saving: bool = False,
    ) -> tuple[CodingNative, int]:
        async with brain_transaction(
            self.factory, scope, credential.identity, owner=mode == "owner"
        ) as (session, control, _):
            result, end = await self._checked_locked(
                session, control, scope, credential, header, lease, mode, end, saving=saving
            )
        self._current(credential, end)
        return result, end

    async def _repository(
        self, prepared: PreparedCodingRequest, credential: AuthenticatedWorkerIdentity, end: int
    ) -> int:
        if self.repository.selection_sha256 != canonical_sha256(repository_selection(prepared)):
            raise ManagementDeniedError("Coding reader nomination differs from frozen input")
        result = await self._owned(
            self.repository.read(prepared.scope, end_us=end), credential, end
        )
        originals = require_coding_sources(prepared.binding, prepared.context, prepared.sources)
        if (
            result.value.company_id != prepared.request.company_id
            or result.value.source != prepared.binding.source
            or result.value.selection_sha256 != self.repository.selection_sha256
            or {row.metadata.path: row.text.encode("utf-8") for row in result.value.files}
            != originals
            or tuple(row.metadata for row in result.value.files) != prepared.binding.source_files
        ):
            raise ManagementDeniedError(
                "Actual committed repository bytes differ from context originals"
            )
        end = min(end, result.read_end_us)
        self._current(credential, end)
        return end

    async def save_worker(
        self,
        lease: ExecutionLease,
        credential: AuthenticatedWorkerIdentity,
        prepared: PreparedCodingRequest,
        *,
        end_us: int,
    ) -> CodingPreparedRef:
        end = self._end(credential, lease, end_us)
        prepared = PreparedCodingRequest.model_validate_json(
            prepared.model_dump_json(by_alias=True)
        )
        require_coding_registry(prepared, self.management.catalog.models)
        if prepared.input_recipe != self.recipe:
            raise ManagementDeniedError("Coding prepared recipe differs")
        raw, body = encode_prepared(prepared)

        async def first() -> CodingPreparedHeader:
            async with brain_transaction(self.factory, prepared.scope, credential.identity) as (
                session,
                control,
                _,
            ):
                native = await self._native(
                    session,
                    control,
                    prepared.scope,
                    credential,
                    prepared.request.task_id,
                    prepared.request.action_id,
                    lease,
                    "worker",
                )
                admission = self.management.catalog.nexus_coding_admission
                assert admission is not None
                return header_for(
                    prepared,
                    body,
                    owner_id=native.current.owner_id,
                    registration_sha256=native.current.registration_sha256,
                    root_task_id=admission.procedure.binding.task_id,
                    root_run_id=admission.procedure.binding.run_id,
                    root_registration_sha256=native.root_registration_sha256,
                    procedure_id=admission.procedure.procedure_id,
                )

        header = await self._owned(first(), credential, end)
        initial, end = await self._owned(
            self._checked(prepared.scope, credential, header, lease, "worker", end, saving=True),
            credential,
            end,
        )
        end = await self._repository(prepared, credential, end)
        reference, metadata = header_reference(header)
        await self._owned(self._io._save(body, raw, end), credential, end)
        await self._owned(self._io._save(reference.header, metadata, end), credential, end)
        final, end = await self._owned(
            self._checked(prepared.scope, credential, header, lease, "worker", end, saving=True),
            credential,
            end,
        )
        if final != initial:
            raise ManagementDeniedError("Coding original native/source proof changed during save")
        self._current(credential, end)
        return reference

    async def load_owner(
        self,
        scope: CompanyControlScope,
        credential: AuthenticatedWorkerIdentity,
        action_id: UUID,
        *,
        end_us: int,
    ) -> StoredCodingRequest:
        return await self._load(
            owner_brain_scope(scope, credential.identity),
            credential,
            action_id,
            None,
            "owner",
            end_us,
        )

    async def load_actor(
        self,
        scope: BrainReadScope,
        credential: AuthenticatedWorkerIdentity,
        action_id: UUID,
        *,
        end_us: int,
    ) -> StoredCodingRequest:
        return await self._load(scope, credential, action_id, None, "actor", end_us)

    async def load_worker(
        self,
        lease: ExecutionLease,
        credential: AuthenticatedWorkerIdentity,
        action_id: UUID,
        *,
        end_us: int,
    ) -> StoredCodingRequest:
        scope = BrainReadScope(
            company_id=lease.company_id,
            workspace_id=credential.identity.workspace_id,
            principal_id=credential.identity.principal_id,
            operation_id=uuid5(action_id, "coding-prepared-read:v1"),
            trace_id=lease.trace_id,
            task_id=lease.task_id,
            task_trace_id=lease.trace_id,
            actor_id=lease.actor_id,
        )
        return await self._load(scope, credential, action_id, lease, "worker", end_us)

    async def _select(
        self,
        scope: BrainReadScope,
        credential: AuthenticatedWorkerIdentity,
        action: UUID,
        lease: ExecutionLease | None,
        mode: Mode,
        end: int,
    ) -> tuple[CodingNative, CodingPreparedRef, int]:
        async with brain_transaction(
            self.factory, scope, credential.identity, owner=mode == "owner"
        ) as (session, control, _):
            row = await session.get(JournalAction, action)
            if row is None or row.company_id != scope.company_id:
                raise ManagementDeniedError("Coding actual native proposal is unavailable")
            native = await self._native(
                session, control, scope, credential, row.task_id, action, lease, mode
            )
            if native.current.proposal is None:
                raise ManagementDeniedError("Coding read requires actual native proposal")
            _, windows = await action_sources(
                session,
                control,
                scope,
                credential.identity,
                native.current.proposal,
                self.sources,
                historical=False,
            )
            before, now = clock_us(), await db_now(session)
            end = shorten(
                end,
                before,
                now,
                (*windows, credential.expires_at, *((lease.expires_at,) if lease else ())),
            )
            reference = prepared_reference(native.current.proposal)
        self._current(credential, end)
        return native, reference, end

    async def _load(
        self,
        scope: BrainReadScope,
        credential: AuthenticatedWorkerIdentity,
        action: UUID,
        lease: ExecutionLease | None,
        mode: Mode,
        end: int,
    ) -> StoredCodingRequest:
        end = self._end(credential, lease, end)
        selected, reference, end = await self._owned(
            self._select(scope, credential, action, lease, mode, end), credential, end
        )
        header = decode_header(
            await self._owned(self._io._read(reference.header, end), credential, end), reference
        )
        initial, end = await self._owned(
            self._checked(scope, credential, header, lease, mode, end), credential, end
        )
        if selected != initial:
            raise ManagementDeniedError("Coding native selection changed during header read")
        prepared = require_body(
            header, await self._owned(self._io._read(header.body, end), credential, end)
        )
        require_coding_registry(prepared, self.management.catalog.models)
        if (
            initial.current.proposal is None
            or initial.current.proposal.parameters
            != model_action_parameters(prepared.request, self.recipe)
        ):
            raise ManagementDeniedError(
                "Coding exact actual model action differs from loaded input"
            )
        if mode != "owner":
            end = await self._repository(prepared, credential, end)
        final, end = await self._owned(
            self._checked(scope, credential, header, lease, mode, end), credential, end
        )
        if final != initial:
            raise ManagementDeniedError(
                "Coding native/source proof changed during protected body read"
            )
        loaded = StoredCodingRequest(prepared, reference, header, end)
        self._issued[:] = [row for row in self._issued if row[0].read_end_us > clock_us()]
        if len(self._issued) >= 32:
            raise ManagementDeniedError("Coding store-issued read bound exceeded")
        lease_pin = ExecutionLease.model_validate_json(lease.model_dump_json()) if lease else None
        self._issued.append((loaded, credential, lease_pin, mode, self._fingerprint(loaded)))
        self._current(credential, end)
        return loaded

    @staticmethod
    def _fingerprint(stored: StoredCodingRequest) -> str:
        return "|".join(
            (
                stored.prepared.model_dump_json(by_alias=True),
                stored.reference.model_dump_json(),
                stored.header.model_dump_json(),
                str(stored.read_end_us),
            )
        )

    def require_loaded(
        self,
        stored: StoredCodingRequest,
        credential: AuthenticatedWorkerIdentity,
        lease: ExecutionLease | None,
        *,
        mode: Mode = "worker",
        end_us: int | None = None,
    ) -> None:
        self._current(
            credential,
            min(stored.read_end_us, end_us) if end_us is not None else stored.read_end_us,
        )
        match = next((row for row in self._issued if row[0] is stored), None)
        if (
            match is None
            or match[1] is not credential
            or match[2] != lease
            or match[3] != mode
            or match[4] != self._fingerprint(stored)
            or (mode == "worker") != (lease is not None)
        ):
            raise ManagementDeniedError(
                "Coding requires the original store-issued read/witness/mode/lease"
            )

    async def validate_loaded_locked(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        stored: StoredCodingRequest,
        credential: AuthenticatedWorkerIdentity,
        lease: ExecutionLease | None,
        *,
        mode: Mode = "worker",
        now: datetime,
    ) -> int:
        self.require_loaded(stored, credential, lease, mode=mode)
        credential.require_time(now)
        _, end = await self._checked_locked(
            session, control, scope, credential, stored.header, lease, mode, stored.read_end_us
        )
        self.require_loaded(stored, credential, lease, mode=mode, end_us=end)
        return end

    async def read_history_header(
        self,
        scope: CompanyControlScope,
        credential: AuthenticatedWorkerIdentity,
        action_id: UUID,
        *,
        end_us: int,
    ) -> CodingHeaderRead:
        from nexus.company.management.coding_prepared_history import read_history_header

        return await read_history_header(self, scope, credential, action_id, end_us=end_us)

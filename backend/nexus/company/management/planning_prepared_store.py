"""Protected planning inputs before approval; source/native checks bracket owned blob I/O."""

from __future__ import annotations

import asyncio
import inspect
import os
import stat
from collections.abc import Awaitable
from datetime import datetime, timedelta
from typing import Literal, cast
from uuid import UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.scope_support import brain_transaction
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.control_support import db_clock
from nexus.company.management.owner_view_sources import OwnerViewSources, owner_brain_scope
from nexus.company.management.planning_intent import PreparedPlanningRequest
from nexus.company.management.planning_native_facts import clock_us, read_end, require_time
from nexus.company.management.planning_prepared_checks import (
    NativePrepared,
    native_prepared,
    require_native_header,
    source_read,
)
from nexus.company.management.planning_prepared_contracts import (
    PlanningPreparedDescriptor,
    PlanningPreparedRef,
    StoredPlanningRequest,
    decode_descriptor,
    descriptor_for,
    descriptor_reference,
    encode_prepared,
    prepared_reference,
    require_body,
)
from nexus.company.management.transactions import ManagementDeniedError
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.harness.journal_models import JournalAction
from nexus.harness.model_authorizer_contracts import ModelInputRecipe, model_action_parameters


class PlanningPreparedStore:
    """Exact configured storage and native/source readers; loaded data is never a permit.

    Cohesion exception: owned I/O and the owner/actor/worker entrypoints share one
    original deadline, source/native validation sequence, and immutable composition.
    """

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        blobs: ProtectedBlobStore,
        sources: OwnerViewSources,
        input_recipe: ModelInputRecipe,
    ) -> None:
        if (
            type(blobs) is not ProtectedBlobStore
            or type(sources.artifacts) is not BoundedArtifactReader
            or sources.artifacts.factory is not factory
        ):
            raise ValueError("Planning preparation requires its concrete same-factory readers")
        self.factory, self.blobs, self.sources = factory, blobs, sources
        self.recipe = ModelInputRecipe.model_validate_json(input_recipe.model_dump_json())
        self._bound = (
            factory,
            blobs,
            blobs._root,
            blobs.storage_symbol,
            sources,
            sources.artifacts,
            sources.artifacts.blobs,
            sources.freshness,
            self.recipe.model_dump_json(),
        )
        self._owners: list[asyncio.Task[object]] = []
        self._stopped = False

    def request_stop(self) -> None:
        """Stop subsequent private phases; already-admitted filesystem leaves stay owned."""
        self._stopped = True

    def _composition(self) -> None:
        original = self._bound
        if (
            self.factory is not original[0]
            or self.blobs is not original[1]
            or (self.blobs._root, self.blobs.storage_symbol) != original[2:4]
            or self.sources is not original[4]
            or self.sources.artifacts is not original[5]
            or self.sources.artifacts.blobs is not original[6]
            or self.sources.freshness is not original[7]
            or self.sources.artifacts.factory is not self.factory
            or self.recipe.model_dump_json() != original[8]
        ):
            raise ManagementDeniedError("Planning protected/native composition changed")

    def pending_owners(self) -> tuple[asyncio.Task[object], ...]:
        """Actual still-running/cancelled resource wrappers, not a caller-issued settled flag."""
        return tuple(task for task in self._owners if not task.done() or task.cancelled())

    async def _owned[T](self, value: Awaitable[T], end_us: int) -> T:
        try:
            require_time(end_us)
            self._composition()
            if self._stopped:
                raise ManagementDeniedError("Original prepared IO stopped admission")
            if len(self.pending_owners()) >= 32:
                raise ManagementDeniedError("Planning pending resource bound exceeded")
        except BaseException:
            if inspect.iscoroutine(value):
                value.close()
            raise
        task = asyncio.ensure_future(value)
        self._owners[:] = list(self.pending_owners())
        self._owners.append(cast(asyncio.Task[object], task))
        task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        try:
            async with asyncio.timeout(max(0, end_us - clock_us()) / 1_000_000):
                result = await asyncio.shield(task)
            require_time(end_us)
            self._composition()
            if self._stopped:
                raise ManagementDeniedError("Original prepared IO stopped admission")
            return result
        except BaseException as error:
            error.__dict__["_nexus_planning_prepared_pending"] = self.pending_owners()
            raise

    def _physical(
        self, reference: ArtifactRevisionRef, *, create: bool = False
    ) -> tuple[tuple[int, ...], ...]:
        path = self.blobs._path(reference)
        values: list[tuple[int, ...]] = []
        for directory in (self.blobs._root, path.parent.parent, path.parent):
            if create:
                directory.mkdir(mode=0o700, exist_ok=True)
            value = directory.stat(follow_symlinks=False)
            if (
                not stat.S_ISDIR(value.st_mode)
                or stat.S_IMODE(value.st_mode) != 0o700
                or value.st_uid != os.getuid()
                or directory.resolve() != directory
            ):
                raise ValueError("Planning preparation directories must remain private/owned")
            values.append((value.st_dev, value.st_ino, value.st_mode, value.st_uid))
        if not create:
            value = path.stat(follow_symlinks=False)
            if (
                not stat.S_ISREG(value.st_mode)
                or stat.S_IMODE(value.st_mode) != 0o400
                or value.st_uid != os.getuid()
                or value.st_nlink != 1
            ):
                raise ValueError("Planning preparation file is not immutable/private")
            values.append(
                (
                    value.st_dev,
                    value.st_ino,
                    value.st_mode,
                    value.st_uid,
                    value.st_nlink,
                    value.st_size,
                    value.st_mtime_ns,
                    value.st_ctime_ns,
                )
            )
        return tuple(values)

    async def _read(self, reference: ArtifactRevisionRef, end_us: int) -> bytes:
        before = await self._owned(asyncio.to_thread(self._physical, reference), end_us)
        raw = await self._owned(self.blobs.read(reference), end_us)
        after = await self._owned(asyncio.to_thread(self._physical, reference), end_us)
        if before != after:
            raise ValueError("Planning preparation changed during actual protected read")
        return raw

    async def _save(self, reference: ArtifactRevisionRef, raw: bytes, end_us: int) -> None:
        roots = await self._owned(asyncio.to_thread(self._physical, reference, create=True), end_us)
        await self._owned(self.blobs.save(reference, raw), end_us)
        if await self._read(reference, end_us) != raw:
            raise ValueError("Planning preparation complete readback differs")
        if (await self._owned(asyncio.to_thread(self._physical, reference), end_us))[:-1] != roots:
            raise ValueError("Planning preparation root changed during write/readback")

    async def _checked(
        self,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        header: PlanningPreparedDescriptor,
        lease: ExecutionLease | None,
        *,
        end_us: int,
        saving: bool = False,
        reader: Literal["owner", "actor", "worker"] = "owner",
        original_windows: tuple[datetime, ...] = (),
    ) -> tuple[NativePrepared, tuple[datetime, ...], int]:
        async with brain_transaction(self.factory, scope, identity, owner=reader == "owner") as (
            session,
            control,
            _,
        ):
            if saving and control.paused:
                raise ManagementDeniedError("Paused company cannot prepare new planning input")
            native = await native_prepared(
                session,
                control,
                scope,
                identity,
                header.task_id,
                header.action_id,
                self.recipe,
                lease=lease,
                reader=reader,
            )
            await require_native_header(session, native, header, self.recipe)
            if header.input_recipe_sha256 != canonical_sha256(self.recipe):
                raise ManagementDeniedError(
                    "Planning prepared recipe differs from configured recipe"
                )
            reference, _ = descriptor_reference(header)
            if native.proposal is None:
                if not saving:
                    raise ManagementDeniedError(
                        "Planning preparation has no actual native proposal"
                    )
            elif (
                prepared_reference(native.proposal) != reference
                or native.proposal.parameters != header.parameters.model_dump(mode="json")
                or native.proposal.resource != f"model:{header.parameters.registry_id}"
            ):
                raise ManagementDeniedError("Planning native request/hash/preparation differs")
            deadlines = await source_read(session, control, scope, identity, header, self.sources)
            final = await native_prepared(
                session,
                control,
                scope,
                identity,
                header.task_id,
                header.action_id,
                self.recipe,
                lease=lease,
                reader=reader,
            )
            await require_native_header(session, final, header, self.recipe)
            if final != native:
                raise ManagementDeniedError(
                    "Planning native fields changed during source validation"
                )
            before_clock = clock_us()
            now = await db_clock(session)
            windows = (
                *deadlines,
                *original_windows,
                *((lease.expires_at,) if lease is not None else ()),
            )
            if any(end <= now for end in windows):
                raise ManagementDeniedError(
                    "Planning source or acquired lease window expired before return"
                )
            # Pin conservatively before the actual SQL clock await. Transaction exit,
            # shield resumption and all later I/O share this cutoff; never reset it.
            final_end = min(
                (
                    end_us,
                    *(before_clock + (end - now) // timedelta(microseconds=1) for end in windows),
                )
            )
        require_time(final_end)
        return native, deadlines, final_end

    async def save(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        prepared: PreparedPlanningRequest,
        *,
        end_us: int,
    ) -> PlanningPreparedRef:
        """Persist before Root submits the pending proposal; failure leaves no effect authority."""
        return await self._persist(
            owner_brain_scope(scope, identity), identity, prepared, None, "owner", end_us
        )

    async def save_worker(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        prepared: PreparedPlanningRequest,
        *,
        end_us: int,
    ) -> PlanningPreparedRef:
        """Persist using the genuine actor's already-held preparation lease; no journal mutation."""
        return await self._persist(prepared.scope, identity, prepared, lease, "worker", end_us)

    async def _persist(
        self,
        brain: BrainReadScope,
        identity: VerifiedIdentity,
        prepared: PreparedPlanningRequest,
        lease: ExecutionLease | None,
        reader: Literal["owner", "actor", "worker"],
        end_us: int,
    ) -> PlanningPreparedRef:
        end_us = read_end(end_us)
        prepared = PreparedPlanningRequest.model_validate_json(
            prepared.model_dump_json(by_alias=True)
        )
        if prepared.input_recipe != self.recipe or prepared.request.company_id != brain.company_id:
            raise ManagementDeniedError(
                "Planning preparation differs from configured recipe/company"
            )
        raw, body = encode_prepared(prepared)

        async def first() -> PlanningPreparedDescriptor:
            async with brain_transaction(
                self.factory, brain, identity, owner=reader == "owner"
            ) as (session, control, _):
                native = await native_prepared(
                    session,
                    control,
                    brain,
                    identity,
                    prepared.request.task_id,
                    prepared.request.action_id,
                    self.recipe,
                    lease=lease,
                    reader=reader,
                )
                return descriptor_for(
                    prepared,
                    body,
                    run_id=native.run_id,
                    registration_sha256=native.registration_sha256,
                    owner_id=native.owner_id,
                )

        header = await self._owned(first(), end_us)
        initial, windows, source_end = await self._owned(
            self._checked(
                brain, identity, header, lease, end_us=end_us, saving=True, reader=reader
            ),
            end_us,
        )
        end_us = min(end_us, source_end)
        require_time(end_us)
        reference, metadata = descriptor_reference(header)
        await self._save(body, raw, end_us)
        await self._save(reference.descriptor, metadata, end_us)
        final, _, source_end = await self._owned(
            self._checked(
                brain,
                identity,
                header,
                lease,
                end_us=end_us,
                saving=True,
                reader=reader,
                original_windows=windows,
            ),
            end_us,
        )
        end_us = min(end_us, source_end)
        if final != initial:
            raise ManagementDeniedError("Planning native preparation changed during persistence")
        require_time(end_us)
        return reference

    async def load_owner(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        action_id: UUID,
        *,
        end_us: int,
    ) -> StoredPlanningRequest:
        """Disclose exact stored input only under this actual current owner's source READ."""
        return await self._load(
            owner_brain_scope(scope, identity), identity, action_id, None, "owner", end_us
        )

    async def load_actor(
        self, scope: BrainReadScope, identity: VerifiedIdentity, action_id: UUID, *, end_us: int
    ) -> StoredPlanningRequest:
        """Current registered actor READ before authorization; no lease/hold/SDK permission."""
        return await self._load(scope, identity, action_id, None, "actor", end_us)

    async def load_worker(
        self, lease: ExecutionLease, identity: VerifiedIdentity, action_id: UUID, *, end_us: int
    ) -> StoredPlanningRequest:
        """Use an already-acquired actual actor lease; no identity manufacture, claim or renewal."""
        scope = BrainReadScope(
            company_id=lease.company_id,
            workspace_id=identity.workspace_id,
            principal_id=identity.principal_id,
            operation_id=uuid5(action_id, "planning-prepared-read:v1"),
            trace_id=lease.trace_id,
            task_id=lease.task_id,
            task_trace_id=lease.trace_id,
            actor_id=lease.actor_id,
        )
        return await self._load(scope, identity, action_id, lease, "worker", end_us)

    async def _load(
        self,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        action_id: UUID,
        lease: ExecutionLease | None,
        reader: Literal["owner", "actor", "worker"],
        end_us: int,
    ) -> StoredPlanningRequest:
        end_us = read_end(end_us)

        async def select_reference() -> tuple[NativePrepared, PlanningPreparedRef]:
            async with brain_transaction(
                self.factory, scope, identity, owner=reader == "owner"
            ) as (session, control, _):
                row = await session.get(JournalAction, action_id)
                if row is None or row.company_id != scope.company_id:
                    raise ManagementDeniedError("Planning native proposal is unavailable")
                native = await native_prepared(
                    session,
                    control,
                    scope,
                    identity,
                    row.task_id,
                    action_id,
                    self.recipe,
                    lease=lease,
                    reader=reader,
                )
                if native.proposal is None:
                    raise ManagementDeniedError("Planning input requires actual native proposal")
                return native, prepared_reference(native.proposal)

        selected, reference = await self._owned(select_reference(), end_us)
        header = decode_descriptor(await self._read(reference.descriptor, end_us), reference)
        initial, windows, source_end = await self._owned(
            self._checked(scope, identity, header, lease, end_us=end_us, reader=reader), end_us
        )
        end_us = min(end_us, source_end)
        require_time(end_us)
        if selected != initial:
            raise ManagementDeniedError("Planning native selection changed during metadata read")
        prepared = require_body(header, await self._read(header.body, end_us))
        if initial.proposal is None or initial.proposal.parameters != model_action_parameters(
            prepared.request, prepared.input_recipe
        ):
            raise ManagementDeniedError("Loaded planning request differs from actual exact action")
        final, _, source_end = await self._owned(
            self._checked(
                scope,
                identity,
                header,
                lease,
                end_us=end_us,
                reader=reader,
                original_windows=windows,
            ),
            end_us,
        )
        end_us = min(end_us, source_end)
        if final != initial:
            raise ManagementDeniedError("Planning native/source request changed during body read")
        result = StoredPlanningRequest(prepared, reference, end_us)
        require_time(end_us)
        self._composition()
        return result

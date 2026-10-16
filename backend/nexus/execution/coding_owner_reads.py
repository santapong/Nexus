"""Current genuine-owner C input disclosure, never a C actor or execution capability.

Cohesion exception: the concrete read graph, actual task/store retention and final
complete serializers share the same first static/source/JWT cutoff. No public
marker, descriptor, ID or decoded identity can substitute for that read sequence.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope
from nexus.company.brain.base import SHA256, ValueContract
from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.base import USD
from nexus.company.management.action_review_coding import (
    CodingReviewSelection,
    select_coding_review,
    validate_coding_review,
)
from nexus.company.management.action_review_contracts import ActionReview, ExactActionDetail
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.coding_intent import PreparedCodingRequest, require_coding_registry
from nexus.company.management.coding_prepared_checks import shorten
from nexus.company.management.coding_prepared_contracts import (
    BODY_LIMIT,
    HEADER_LIMIT,
    CodingPreparedRef,
    StoredCodingRequest,
)
from nexus.company.management.coding_prepared_store import CodingPreparedStore
from nexus.company.management.control_support import db_clock
from nexus.company.management.owner_view_approvals import action_audit
from nexus.company.management.owner_view_contracts import ApprovalView
from nexus.company.management.plan_support import CurrentPlanBinding
from nexus.company.management.planning_native_facts import clock_us, read_end, require_time
from nexus.company.management.transactions import (
    ManagementDeniedError,
    management_owner_transaction,
)
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.core.llm.company_registry import ModelRegistration
from nexus.execution.coding_services import CodingServices
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.journal_models import CompanyControl

OWNER_INPUT_LIMIT = BODY_LIMIT + HEADER_LIMIT + 65_536


class CodingInputReview(ValueContract):
    """Full authorized saved input and native digest domains; none is an effect permit."""

    company_id: UUID
    action_id: UUID
    proposal_sha256: SHA256
    proposal: ActionProposal
    request_sha256: SHA256
    header_sha256: SHA256
    reference: CodingPreparedRef
    model: ModelRegistration
    maximum_reservation_usd: USD
    currency: Literal["USD"] = "USD"
    prepared: PreparedCodingRequest
    company_completed: Literal[False] = False
    execution_permitted: Literal[False] = False


@dataclass(frozen=True, slots=True)
class CodingOwnerRead:
    value: CodingInputReview
    read_end_us: int


@dataclass(frozen=True, slots=True)
class CodingActionReviewRead:
    value: ActionReview
    read_end_us: int


@dataclass(frozen=True, slots=True)
class _OwnerData:
    loaded: StoredCodingRequest
    proposal: ActionProposal
    audit: ApprovalView
    run_id: UUID
    observed_at: datetime
    read_end_us: int


class CodingOwnerReader:
    """Only the actual C graph can create per-read stores; never acquire C credentials.

    Cohesion exception: selection issuance, out-of-CC private IO, final same-CC
    proof and resource retirement are one fixed pipeline with no callback seam.
    """

    def __init__(self, services: CodingServices) -> None:
        if type(services) is not CodingServices:
            raise ValueError("Coding input requires its concrete original services")
        services.require_composition()
        self.services = services
        self._services_original = services
        self._original = (
            services,
            services.factory,
            services.management,
            services.management.catalog,
            services.contexts,
            services.prepared_blobs,
            services.source_views,
            canonical_sha256(services.management.catalog),
        )
        self._owners: list[asyncio.Task[object]] = []
        self._stores: list[CodingPreparedStore] = []
        self._active: set[int] = set()
        self._selected: dict[
            int, tuple[CodingReviewSelection, AuthenticatedWorkerIdentity, str]
        ] = {}
        self._stopped = False

    @property
    def factory(self) -> async_sessionmaker[AsyncSession]:
        return self.services.factory

    def require_composition(self) -> None:
        if self.services is not self._services_original:
            raise ManagementDeniedError("Original coding owner-read services changed")
        self.services.require_composition()
        actual = (
            self.services,
            self.services.factory,
            self.services.management,
            self.services.management.catalog,
            self.services.contexts,
            self.services.prepared_blobs,
            self.services.source_views,
            canonical_sha256(self.services.management.catalog),
        )
        if (
            any(a is not b for a, b in zip(self._original[:7], actual[:7], strict=True))
            or self._original[7:] != actual[7:]
        ):
            raise ManagementDeniedError("Original coding owner-read composition changed")

    def _current(self, owner: AuthenticatedWorkerIdentity, end: int) -> None:
        self.require_composition()
        require_time(end)
        if self._stopped or type(owner) is not AuthenticatedWorkerIdentity:
            raise ManagementDeniedError("Coding input requires its original authenticated owner")
        owner.require_time(datetime.now(UTC))

    def _end(self, scope: CompanyControlScope, owner: AuthenticatedWorkerIdentity, end: int) -> int:
        self._current(owner, end)
        if scope.principal_id != owner.identity.principal_id:
            raise ManagementDeniedError("Coding owner input identity differs")
        return shorten(read_end(end), clock_us(), datetime.now(UTC), (owner.expires_at,))

    def request_stop(self) -> None:
        self._stopped = True
        for store in self._stores:
            store.request_stop()

    def _retire(self, store: CodingPreparedStore) -> None:
        store.request_stop()
        if id(store) in self._active or store.pending_owners():
            return
        self._stores[:] = [value for value in self._stores if value is not store]
        # Remove ONLY this reader's settled actual store; never a worker store or
        # an unresolved owner. The shared services retain all still-live leaves.
        self.services._stores[:] = [value for value in self.services._stores if value is not store]

    def pending_owners(self) -> tuple[asyncio.Task[object], ...]:
        for store in tuple(self._stores):
            if id(store) not in self._active:
                self._retire(store)
        return tuple(
            dict.fromkeys(
                (
                    *(row for row in self._owners if not row.done() or row.cancelled()),
                    *(row for store in self._stores for row in store.pending_owners()),
                    *self.services.pending_owners(),
                )
            )
        )

    async def _owned[T](
        self, operation: Awaitable[T], owner: AuthenticatedWorkerIdentity, end: int
    ) -> T:
        try:
            self._current(owner, end)
            if len(self.pending_owners()) >= 32:
                raise ManagementDeniedError("Coding owner pending-resource bound exceeded")
        except BaseException:
            if inspect.iscoroutine(operation):
                operation.close()
            raise
        task = asyncio.ensure_future(operation)
        self._owners[:] = [row for row in self._owners if not row.done() or row.cancelled()]
        self._owners.append(cast(asyncio.Task[object], task))
        task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        try:
            async with asyncio.timeout(max(0, end - clock_us()) / 1_000_000):
                result = await asyncio.shield(task)
            self._current(owner, end)
            return result
        except BaseException as first:

            def discard(done: asyncio.Future[T]) -> None:
                if not done.cancelled() and done.exception() is None:
                    value = done.result()
                    if type(value) is CodingReviewSelection:
                        self._selected.pop(id(value), None)

            task.add_done_callback(discard)
            first.__dict__["_nexus_coding_owner_pending"] = self.pending_owners()
            first.__dict__["_nexus_coding_owner_reader"] = self
            raise

    async def select_locked(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: CompanyControlScope,
        owner: AuthenticatedWorkerIdentity,
        proposal: ActionProposal,
        work: ExecutionWork,
        binding: CurrentPlanBinding,
        *,
        end_us: int,
    ) -> CodingReviewSelection:
        self._current(owner, end_us)
        selected = await select_coding_review(
            self.services, session, control, scope, owner, proposal, work, binding, end_us=end_us
        )
        self._current(owner, selected.read_end_us)
        self._selected = {
            key: row for key, row in self._selected.items() if row[0].read_end_us > clock_us()
        }
        if len(self._selected) >= 32:
            raise ManagementDeniedError("Coding owner selection bound exceeded")
        self._selected[id(selected)] = (selected, owner, scope.model_dump_json())
        return selected

    def _selection(
        self,
        scope: CompanyControlScope,
        owner: AuthenticatedWorkerIdentity,
        selected: CodingReviewSelection,
        end: int,
    ) -> int:
        self._current(owner, min(end, selected.read_end_us))
        original = self._selected.get(id(selected))
        if (
            original is None
            or original[0] is not selected
            or original[1] is not owner
            or original[2] != scope.model_dump_json()
        ):
            raise ManagementDeniedError(
                "Coding input requires its original actual owner/static selection"
            )
        return min(end, selected.read_end_us)

    async def _select(
        self, scope: CompanyControlScope, owner: AuthenticatedWorkerIdentity, action: UUID, end: int
    ) -> CodingReviewSelection:
        from nexus.company.management.action_review_store import _row, current_review_work

        async with management_owner_transaction(
            self.services.factory, scope, owner.identity, allow_paused=True
        ) as (session, control, _):
            proposal, work, binding = await current_review_work(
                session, control, scope, await _row(session, scope, action)
            )
            selected = await self.select_locked(
                session, control, scope, owner, proposal, work, binding, end_us=end
            )
        self._current(owner, selected.read_end_us)
        return selected

    async def _final(
        self,
        scope: CompanyControlScope,
        owner: AuthenticatedWorkerIdentity,
        action: UUID,
        selected: CodingReviewSelection,
        store: CodingPreparedStore,
        loaded: StoredCodingRequest,
        end: int,
    ) -> _OwnerData:
        from nexus.company.management.action_review_store import _row, current_review_work

        end = self._selection(scope, owner, selected, min(end, loaded.read_end_us))
        async with management_owner_transaction(
            self.services.factory, scope, owner.identity, allow_paused=True
        ) as (session, control, _):
            row = await _row(session, scope, action)
            proposal, work, binding = await current_review_work(session, control, scope, row)
            end = await validate_coding_review(
                self.services,
                session,
                control,
                scope,
                owner,
                proposal,
                work,
                binding,
                selected,
                store,
                loaded,
                end_us=end,
            )
            audit = await action_audit(session, row)
            before, now = clock_us(), await db_clock(session)
            end = shorten(end, before, now, (owner.expires_at,))
            result = _OwnerData(loaded, proposal, audit, work.run_id, now, end)
        self._current(owner, end)
        return result

    @asynccontextmanager
    async def _loaded(
        self,
        scope: CompanyControlScope,
        owner: AuthenticatedWorkerIdentity,
        action: UUID,
        selected: CodingReviewSelection,
        end: int,
    ) -> AsyncIterator[_OwnerData]:
        end = self._selection(scope, owner, selected, end)
        store = self.services.create_prepared()
        self._stores.append(store)
        self._active.add(id(store))
        try:
            # H owns its individual private/SQL leaves. Do not shield a whole
            # pipeline that could issue the next private read after caller stop.
            loaded = await store.load_owner(scope, owner, action, end_us=end)
            end = min(end, loaded.read_end_us)
            self._current(owner, end)
            yield await self._owned(
                self._final(scope, owner, action, selected, store, loaded, end), owner, end
            )
        except BaseException as first:
            first.__dict__["_nexus_coding_owner_pending"] = self.pending_owners()
            first.__dict__["_nexus_coding_owner_reader"] = self
            raise
        finally:
            self._selected.pop(id(selected), None)
            self._active.discard(id(store))
            self._retire(store)

    async def read(
        self,
        scope: CompanyControlScope,
        owner: AuthenticatedWorkerIdentity,
        action_id: UUID,
        *,
        end_us: int,
    ) -> CodingOwnerRead:
        """Current owner data only; preserve full exact bytes and the first cutoffs."""
        end = self._end(scope, owner, end_us)
        selected = await self._owned(self._select(scope, owner, action_id, end), owner, end)
        async with self._loaded(
            scope, owner, action_id, selected, min(end, selected.read_end_us)
        ) as data:
            prepared = data.loaded.prepared
            model = require_coding_registry(prepared, self.services.management.catalog.models)
            value = CodingInputReview(
                company_id=scope.company_id,
                action_id=action_id,
                proposal_sha256=data.audit.proposal_sha256,
                proposal=data.proposal,
                request_sha256=prepared.request_sha256,
                header_sha256=data.loaded.reference.header.sha256,
                reference=data.loaded.reference,
                model=model,
                maximum_reservation_usd=data.proposal.estimated_cost_usd,
                prepared=prepared,
            )
            if len(value.model_dump_json(by_alias=True).encode()) > OWNER_INPUT_LIMIT:
                raise ManagementDeniedError("Complete coding input response exceeds its byte bound")
            self._current(owner, data.read_end_us)
            result = CodingOwnerRead(value, data.read_end_us)
        self._current(owner, result.read_end_us)
        return result

    async def review_selected(
        self,
        scope: CompanyControlScope,
        owner: AuthenticatedWorkerIdentity,
        action_id: UUID,
        selected: CodingReviewSelection,
        *,
        end_us: int,
    ) -> CodingActionReviewRead:
        """Complete first generic-review metadata before protected IO and final native proof."""
        end = self._selection(scope, owner, selected, end_us)
        async with self._loaded(scope, owner, action_id, selected, end) as data:
            value = ActionReview(
                company_id=scope.company_id,
                observed_at=data.observed_at,
                audit=data.audit,
                availability="available",
                detail=ExactActionDetail(
                    company_id=scope.company_id,
                    task_id=data.proposal.task_id,
                    trace_id=data.proposal.trace_id,
                    run_id=data.run_id,
                    proposal_sha256=data.audit.proposal_sha256,
                    proposal=data.proposal,
                ),
            )
            if len(value.model_dump_json(by_alias=True).encode()) > 65_536:
                raise ManagementDeniedError("Complete coding action review exceeds its byte bound")
            self._current(owner, data.read_end_us)
            result = CodingActionReviewRead(value, data.read_end_us)
        self._current(owner, result.read_end_us)
        return result

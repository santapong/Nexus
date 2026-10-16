"""Current owner historical C content after real H and native/model-wire joins; no publication."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from nexus.company.access import CompanyControlScope
from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.management.coding_content import CodeChangeContent, validate_code_change
from nexus.company.management.coding_prepared_contracts import StoredCodingRequest
from nexus.company.management.coding_prepared_store import CodingPreparedStore
from nexus.company.management.coding_sources import require_coding_sources
from nexus.company.management.cycle_cost_contracts import NativeCostSelection
from nexus.company.management.cycle_model_facts import join_cycle_model_fact
from nexus.company.management.cycle_model_native import native_model_artifact
from nexus.company.management.cycle_model_reader import native_cost_selection
from nexus.company.management.owner_view_sources import owner_brain_scope
from nexus.company.management.planning_native_facts import clock_us, require_time
from nexus.company.management.transactions import (
    ManagementDeniedError,
    management_owner_transaction,
)
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.coding_lifecycle_bindings import (
    approved_r2_locked,
    owner_locked,
    static_read_locked,
)
from nexus.execution.coding_lifecycle_contracts import CodingCandidateReview, CodingLifecycleRead
from nexus.execution.coding_owner_reads import CodingOwnerReader
from nexus.execution.coding_services import CodingServices
from nexus.execution.runtime_support import db_now


class CodingCandidateReader:
    """Actual input, source and model-file owners survive cancellation."""

    def __init__(self, services: CodingServices, inputs: CodingOwnerReader) -> None:
        if (
            type(services) is not CodingServices
            or type(inputs) is not CodingOwnerReader
            or inputs.services is not services
        ):
            raise ValueError("Coding candidate needs its real same-graph input reader")
        self.services, self.inputs = services, inputs
        self._original = (services, inputs, services.factory, services.evidence)
        self._stores: list[CodingPreparedStore] = []
        self._active: set[int] = set()
        self._owners: list[asyncio.Task[object]] = []
        self._stopped = False

    def require_composition(self) -> None:
        self.services.require_composition()
        self.inputs.require_composition()
        if any(
            a is not z
            for a, z in zip(
                (self.services, self.inputs, self.services.factory, self.services.evidence),
                self._original,
                strict=True,
            )
        ):
            raise ManagementDeniedError("Original coding candidate graph changed")

    def request_stop(self) -> None:
        self._stopped = True
        for store in self._stores:
            store.request_stop()

    def pending_owners(self) -> tuple[asyncio.Task[object], ...]:
        self._owners[:] = [task for task in self._owners if not task.done() or task.cancelled()]
        for store in tuple(self._stores):
            if id(store) not in self._active:
                self._retire(store)
        return tuple(
            dict.fromkeys(
                (
                    *(task for task in self._owners if not task.done() or task.cancelled()),
                    *(task for store in self._stores for task in store.pending_owners()),
                    *self.inputs.pending_owners(),
                    *self.services.evidence.pending_owners(),
                )
            )
        )

    def _retire(self, store: CodingPreparedStore) -> None:
        store.request_stop()
        if id(store) in self._active or store.pending_owners():
            return
        self._stores[:] = [value for value in self._stores if value is not store]
        self.services._stores[:] = [value for value in self.services._stores if value is not store]

    def _current(self, owner: AuthenticatedWorkerIdentity, end: int) -> None:
        self.require_composition()
        require_time(end)
        owner.require_time(datetime.now(UTC))
        admission = self.services.management.catalog.nexus_coding_admission
        assert admission is not None
        if (
            self._stopped
            or type(owner) is not AuthenticatedWorkerIdentity
            or (owner.identity.principal_id, owner.identity.workspace_id)
            != (admission.procedure.binding.actor_id, admission.procedure.binding.workspace_id)
        ):
            raise ManagementDeniedError("Coding candidate requires its current genuine owner")

    async def _owned[T](self, value: Awaitable[T], end: int) -> T:
        try:
            require_time(end)
            if len(self.pending_owners()) >= 32:
                raise ManagementDeniedError("Coding candidate pending-resource bound exceeded")
        except BaseException:
            if inspect.iscoroutine(value):
                value.close()
            elif isinstance(value, asyncio.Task):
                self._owners.append(cast(asyncio.Task[object], value))
            raise
        task = asyncio.ensure_future(value)
        self._owners.append(cast(asyncio.Task[object], task))
        task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        async with asyncio.timeout(max(0, end - clock_us()) / 1_000_000):
            return await asyncio.shield(task)

    async def _native(
        self,
        store: CodingPreparedStore,
        loaded: StoredCodingRequest,
        scope: CompanyControlScope,
        owner: AuthenticatedWorkerIdentity,
        head: UUID,
        end: int,
    ) -> tuple[NativeCostSelection, ArtifactRef, int]:
        """Cohesion exception: native/source/model anchors share the same owner transaction."""
        async with management_owner_transaction(
            self.services.factory, scope, owner.identity, allow_paused=True
        ) as (session, control, _):
            end = await owner_locked(self.services, session, control, scope, owner, end)
            bundle, end = await approved_r2_locked(
                self.services, session, control, scope, owner, end
            )
            if (
                bundle.plan.plan_revision_id != head
                or loaded.prepared.binding.plan != bundle.binding.plan
            ):
                raise ManagementDeniedError("Coding candidate current r2 head differs")
            end = min(
                end,
                await store.validate_loaded_locked(
                    session,
                    control,
                    owner_brain_scope(scope, owner.identity),
                    loaded,
                    owner,
                    None,
                    mode="owner",
                    now=await db_now(session),
                ),
            )
            selected = await native_cost_selection(
                session, scope.company_id, loaded.prepared.request.action_id
            )
            artifact = native_model_artifact(scope, selected, loaded.header.parameters)
            if (
                selected.action.proposal.parameters
                != loaded.header.parameters.model_dump(mode="json")
                or artifact is None
                or selected.intent is None
                or selected.intent.state != "succeeded"
            ):
                raise ManagementDeniedError(
                    "Coding candidate lacks its exact known native model anchor"
                )
            end = await static_read_locked(
                self.services, session, control, scope, owner, bundle.binding, selected.action, end
            )
            end = await owner_locked(self.services, session, control, scope, owner, end)
        self._current(owner, end)
        return selected, artifact, end

    async def read(
        self,
        scope: CompanyControlScope,
        owner: AuthenticatedWorkerIdentity,
        action_id: UUID,
        *,
        expected_current_revision_id: UUID,
        end_us: int,
    ) -> CodingLifecycleRead[CodingCandidateReview]:
        """Cohesion exception: original static/read/model/native ends bracket all protected IO."""
        self._current(owner, end_us)
        if (
            scope.company_id != self.services.management.catalog.company_id
            or scope.principal_id != owner.identity.principal_id
        ):
            raise ManagementDeniedError("Coding candidate scope differs")
        # The actual input reader establishes first static target/charter cutoffs.
        # Its returned DTO is not accepted as a proof: a new real H owner seal follows.
        # The concrete owner reader shields its actual leaves and stops only this
        # read's store on cancellation. Shielding that whole pipeline again would
        # let later private phases start after the original caller stopped.
        first = await self.inputs.read(scope, owner, action_id, end_us=end_us)
        end_us = min(end_us, first.read_end_us)
        self._current(owner, end_us)
        store = self.services.create_prepared()
        self._stores.append(store)
        self._active.add(id(store))
        try:
            loaded = await self._owned(
                store.load_owner(scope, owner, action_id, end_us=end_us), end_us
            )
            end_us = min(end_us, loaded.read_end_us)
            if loaded.reference != first.value.reference:
                raise ManagementDeniedError("Coding candidate prepared input changed")
            initial, artifact, end_us = await self._owned(
                self._native(store, loaded, scope, owner, expected_current_revision_id, end_us),
                end_us,
            )
            record = await self._owned(self.services.evidence.load_record(artifact), end_us)
            self._current(owner, end_us)
            final, current_artifact, end_us = await self._owned(
                self._native(store, loaded, scope, owner, expected_current_revision_id, end_us),
                end_us,
            )
            if final != initial or current_artifact != artifact:
                raise ManagementDeniedError("Coding native model proof changed during read")
            work = final.directory.work
            assert work is not None
            evidence = record.evidence
            prepared = loaded.prepared
            fact = join_cycle_model_fact(
                final.directory.directory_data(),
                work,
                final.action,
                prepared.request,
                prepared.input_recipe,
                self.services.management.catalog.models,
                attempt=final.attempt.native_data() if final.attempt else None,
                intent=final.intent,
                hold=final.hold.native_data() if final.hold else None,
                artifact=artifact,
                evidence=evidence,
                wire=record.wire,
            )
            if (
                fact.billing != "known"
                or evidence.request != prepared.request
                or evidence.input_estimate != prepared.input_estimate
                or evidence.result.status != "response"
                or evidence.result.text is None
            ):
                raise ManagementDeniedError(
                    "Coding protected model/native financial proof is unconfirmed"
                )
            assert prepared.request.output_schema is not None
            content = CodeChangeContent.model_validate_json(evidence.result.text)
            prepared.request.output_schema.validate_output(evidence.result.text)
            validate_code_change(
                content,
                prepared.binding,
                manifest=prepared.context.manifest,
                originals=require_coding_sources(
                    prepared.binding, prepared.context, prepared.sources
                ),
            )
            assert final.intent is not None and final.intent.receipt is not None
            value = CodingCandidateReview(
                company_id=scope.company_id,
                action_id=action_id,
                binding=prepared.binding,
                manifest=prepared.context.manifest,
                content=content,
                request_id=prepared.request.request_id,
                request_sha256=prepared.request_sha256,
                receipt_id=final.intent.receipt.receipt_id,
                artifact_id=artifact.artifact_id,
                artifact_sha256=artifact.sha256,
                recorded_at=evidence.checked_at,
            )
            value.model_dump_json(by_alias=True)
            self._current(owner, end_us)
            return CodingLifecycleRead(value, end_us)
        except BaseException:
            store.request_stop()
            raise
        finally:
            self._active.discard(id(store))
            self._retire(store)

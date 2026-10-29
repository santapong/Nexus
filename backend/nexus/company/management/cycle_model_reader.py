"""Current-owner historical model financial reads, with source authority before private I/O.

Cohesion exception: this common/L concrete native/source/descriptor/owned-file flow
exceeds400 lines so all actual original bindings and first/final cutoffs remain
adjacent. C uses its separate concrete history source and reader, never a fallback.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import stat
from collections.abc import Awaitable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope
from nexus.company.brain.access_support import require_resources
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.native_fact_inputs import source_artifact_reference
from nexus.company.brain.retrieval_records import heads, revision_ref
from nexus.company.brain.source_models import BrainSourceRevision
from nexus.company.contracts.actions import ResourceRevision
from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.contracts.work import WorkItem
from nexus.company.directory_models import RegisteredWork
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.cycle_cost_contracts import (
    DirectoryCostWork,
    HistoricalCostSources,
    ModelCostRead,
    ModelSourceProof,
    NativeCostAttempt,
    NativeCostHold,
    NativeCostSelection,
)
from nexus.company.management.cycle_model_facts import join_cycle_model_fact
from nexus.company.management.cycle_model_native import native_model_artifact
from nexus.company.management.nexus_coding_admission import (
    NexusCodingAdmission,
    select_nexus_coding_plan,
)
from nexus.company.management.nexus_coding_catalog import configured_nexus_admission
from nexus.company.management.owner_view_sources import owner_brain_scope
from nexus.company.management.plan_catalog import PlanAdmissionCatalog
from nexus.company.management.plan_models import ManagementOwnerDecision, ManagementPlanRevision
from nexus.company.management.plan_registration import registration
from nexus.company.management.planning_native_facts import clock_us, require_time
from nexus.company.management.planning_prepared_contracts import (
    PlanningModelParameters,
    PlanningPreparedDescriptor,
    decode_descriptor,
    prepared_reference,
)
from nexus.company.management.planning_prepared_store import PlanningPreparedStore
from nexus.company.management.revision_store import plan_record
from nexus.company.management.transactions import (
    ManagementDeniedError,
    management_owner_transaction,
)
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.effect_support import effect_record
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt, ExecutionWork
from nexus.execution.runtime_support import db_now, registration_digest, snapshot
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CompanyControl, CostHold, JournalAction
from nexus.harness.journal_submission import pending_action_record
from nexus.harness.model_evidence import FileModelEvidenceStore

if TYPE_CHECKING:
    from nexus.company.management.cycle_coding_sources import CodingCostSources


def cost_read_end(
    scope: CompanyControlScope, owner: AuthenticatedWorkerIdentity, end_us: int
) -> int:
    if type(owner) is not AuthenticatedWorkerIdentity or type(end_us) is not int:
        raise ManagementDeniedError("Financial read requires its original authenticated owner")
    before, now = clock_us(), datetime.now(UTC)
    owner.require_time(now)
    if scope.principal_id != owner.identity.principal_id:
        raise ManagementDeniedError("Financial read identity differs")
    end = min(
        end_us, before + 30_000_000, before + (owner.expires_at - now) // timedelta(microseconds=1)
    )
    require_time(end)
    return end


def directory_cost_work(row: RegisteredWork, work: ExecutionWork | None) -> DirectoryCostWork:
    return DirectoryCostWork(
        **{
            key: getattr(row, key)
            for key in DirectoryCostWork.model_fields
            if key not in {"work", "schema_version"}
        },
        work=snapshot(work) if work is not None else None,
    )


def native_hold(row: CostHold) -> NativeCostHold:
    return NativeCostHold(
        **{key: getattr(row, key) for key in NativeCostHold.model_fields if key != "schema_version"}
    )


async def native_cost_selection(
    session: AsyncSession, company: UUID, action_id: UUID
) -> NativeCostSelection:
    action = await session.get(JournalAction, action_id)
    if action is None or action.company_id != company:
        raise ManagementDeniedError("Financial native action is unavailable")
    directory = await session.get(RegisteredWork, (company, action.task_id))
    work = await session.get(ExecutionWork, (company, action.task_id))
    if directory is None:
        raise ManagementDeniedError("Financial native registration is unavailable")
    hold = await session.get(CostHold, action_id)
    if hold is not None and (hold.company_id, hold.task_id) != (company, action.task_id):
        raise ManagementDeniedError("Financial hold identity differs")
    intent = await session.get(EffectIntent, (company, action_id))
    attempt = await session.get(ExecutionAttempt, (company, action.task_id, action_id))
    return NativeCostSelection(
        directory=directory_cost_work(directory, work),
        action=pending_action_record(action),
        hold=native_hold(hold) if hold else None,
        intent=effect_record(intent) if intent else None,
        attempt=NativeCostAttempt(
            **{
                key: getattr(attempt, key)
                for key in NativeCostAttempt.model_fields
                if key != "schema_version"
            }
        )
        if attempt
        else None,
    )


async def stored_coding_profile(
    session: AsyncSession, admission: NexusCodingAdmission, *, works: tuple[WorkItem, ...] = ()
) -> bool:
    """Historical immutable approved payload, not current Goal/head/eligibility authority."""
    rows = tuple(
        (
            await session.scalars(
                select(ManagementPlanRevision)
                .where(
                    ManagementPlanRevision.company_id == admission.company_id,
                    ManagementPlanRevision.plan_id == admission.plan_id,
                )
                .order_by(ManagementPlanRevision.revision)
                .limit(3)
            )
        ).all()
    )
    if not rows or len(rows) > 2:
        return False
    bound = False
    for row in rows:
        value = plan_record(row)
        if (
            value.payload.coding_admission_sha256 != canonical_sha256(admission)
            or value.payload.procedure != admission.procedure
            or value.payload.goal != admission.goal
            or canonical_sha256(value.payload) != value.sha256
        ):
            return False
        approvals = tuple(
            (
                await session.scalars(
                    select(ManagementOwnerDecision)
                    .where(
                        ManagementOwnerDecision.company_id == admission.company_id,
                        ManagementOwnerDecision.plan_revision_id == row.plan_revision_id,
                        ManagementOwnerDecision.kind == "approve",
                        ManagementOwnerDecision.payload_sha256 == row.sha256,
                    )
                    .limit(2)
                )
            ).all()
        )
        select_nexus_coding_plan(admission, value.payload)
        approved = (
            bool(approvals)
            if not works
            else any(
                approval.owner_id == admission.procedure.binding.actor_id for approval in approvals
            )
        )
        bound = bound or (
            approved
            and (
                not works
                or (value.revision == 2 and all(work in value.payload.plan.items for work in works))
            )
        )
    return bound


class CycleModelReader:
    """Concrete sealed graph; no permissive callback or caller proof.

    Cohesion exception: this >300-line reader keeps its original object graph,
    actual owned IO and source/native revalidation together through cancellation.
    """

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        catalog: PlanAdmissionCatalog,
        evidence: FileModelEvidenceStore,
        planning: PlanningPreparedStore | None = None,
        *,
        coding: CodingCostSources | None = None,
    ) -> None:
        admission = configured_nexus_admission(catalog)
        if (
            type(admission) is not NexusCodingAdmission
            or type(evidence) is not FileModelEvidenceStore
            or (
                planning is not None
                and (
                    type(planning) is not PlanningPreparedStore
                    or planning.factory is not factory
                    or type(planning.sources.artifacts) is not BoundedArtifactReader
                    or type(planning.sources.freshness) is not RegisteredSourceFreshness
                    or planning.sources.freshness._factory is not factory
                )
            )
        ):
            raise ValueError("Family finance requires the concrete full-company profile/storage")
        self.factory, self.catalog, self.evidence, self.planning = (
            factory,
            catalog,
            evidence,
            planning,
        )
        self.admission = admission
        self.coding = self._original_coding = coding
        self._owners: list[asyncio.Task[object]] = []
        self._bound = self._composition_values()
        self.require_composition()

    def _composition_values(self) -> tuple[object, ...]:
        return (
            self.factory,
            self.catalog,
            self.evidence,
            self.evidence._root,
            self.planning,
            canonical_sha256(self.catalog),
            canonical_sha256(self.admission),
            self.coding,
        )

    def require_composition(self) -> None:
        current = self._composition_values()
        if (
            any(a is not b for a, b in zip(current[:3], self._bound[:3], strict=True))
            or current[3:] != self._bound[3:]
            or configured_nexus_admission(self.catalog) != self.admission
        ):
            raise ManagementDeniedError("Original financial reader composition changed")
        if self.planning is not None:
            self.planning._composition()
            if self.planning.factory is not self.factory:
                raise ManagementDeniedError("Financial preparation factory changed")
        if self.coding is not self._original_coding:
            raise ManagementDeniedError("Original coding financial sources changed")
        if self.coding is not None:
            from nexus.company.management.cycle_coding_sources import CodingCostSources

            if type(self.coding) is not CodingCostSources:
                raise ManagementDeniedError("Financial C sources must be concrete")
            self.coding.require_composition()
            services = self.coding.services
            if (
                services.factory is not self.factory
                or services.management.catalog is not self.catalog
                or services.evidence is not self.evidence
                or (
                    self.planning is not None
                    and (
                        services.source_views.artifacts is not self.planning.sources.artifacts
                        or services.source_views.freshness is not self.planning.sources.freshness
                    )
                )
            ):
                raise ManagementDeniedError(
                    "Financial C sources differ from original native stores"
                )

    def pending_owners(self) -> tuple[asyncio.Task[object], ...]:
        return tuple(
            dict.fromkeys(
                (
                    *(task for task in self._owners if not task.done() or task.cancelled()),
                    *self.evidence.pending_owners(),
                    *(self.planning.pending_owners() if self.planning else ()),
                    *(self.planning.blobs.pending_owners() if self.planning else ()),
                    *(self._original_coding.pending_owners() if self._original_coding else ()),
                )
            )
        )

    async def owned[T](self, value: Awaitable[T], end: int) -> T:
        try:
            self.require_composition()
            require_time(end)
            if len(self.pending_owners()) >= 32:
                raise ManagementDeniedError("Financial pending resource bound exceeded")
        except BaseException:
            if inspect.iscoroutine(value):
                value.close()
            raise
        task = asyncio.ensure_future(value)
        self._owners[:] = [row for row in self._owners if not row.done() or row.cancelled()]
        self._owners.append(cast(asyncio.Task[object], task))
        task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        try:
            async with asyncio.timeout(max(0, end - clock_us()) / 1_000_000):
                result = await asyncio.shield(task)
            require_time(end)
            self.require_composition()
            return result
        except BaseException as first:
            first.__dict__["_nexus_cycle_cost_pending"] = self.pending_owners()
            raise

    def _owner(
        self,
        scope: CompanyControlScope,
        owner: AuthenticatedWorkerIdentity,
        control: CompanyControl,
        end: int,
    ) -> None:
        self.require_composition()
        require_time(end)
        owner.require_time(datetime.now(UTC))
        if (
            scope.company_id != self.admission.company_id
            or (scope.principal_id, owner.identity.principal_id)
            != (control.owner_id, control.owner_id)
            or owner.identity.workspace_id != self.admission.procedure.binding.workspace_id
        ):
            raise ManagementDeniedError("Financial audit requires the actual current owner")

    async def _sources(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: CompanyControlScope,
        owner: AuthenticatedWorkerIdentity,
        selected: NativeCostSelection,
        header: PlanningPreparedDescriptor | None,
        end: int,
    ) -> tuple[str, int]:
        """Explicit history policy; actual original conditions are never filtered or guessed."""
        if self.planning is None:
            raise ValueError("Concrete planning source proof is unavailable")
        freshness = self.planning.sources.freshness
        if type(freshness) is not RegisteredSourceFreshness:
            raise ValueError("Financial source policy composition changed")
        action = selected.action.proposal
        reference = prepared_reference(action)
        resource_ids, refs = [], []
        for condition in action.preconditions:
            if condition == reference.condition:
                continue
            if condition.resource.startswith("brain.resource:"):
                resource = UUID(condition.resource.removeprefix("brain.resource:"))
                generation = int(condition.revision.removeprefix("acl:"))
                if (
                    condition
                    != ResourceRevision(
                        resource=f"brain.resource:{resource}", revision=f"acl:{generation}"
                    )
                    or generation < 1
                ):
                    raise ValueError("Financial resource condition is not canonical")
                resource_ids.append(resource)
            elif condition.resource.startswith("brain.source:"):
                source_id = UUID(condition.resource.removeprefix("brain.source:"))
                pieces = condition.revision.split(":")
                if len(pieces) != 3 or pieces[0] != "head" or not pieces[1].isdecimal():
                    raise ValueError("Financial source condition is unavailable")
                if int(pieces[1]) < 1 or condition != ResourceRevision(
                    resource=f"brain.source:{source_id}",
                    revision=f"head:{int(pieces[1])}:{UUID(pieces[2])}",
                ):
                    raise ValueError("Financial source condition is not canonical")
                source_revision = await session.get(
                    BrainSourceRevision, (scope.company_id, UUID(pieces[2]))
                )
                if source_revision is None or source_revision.source_id != source_id:
                    raise ValueError("Financial historical source is unavailable")
                refs.append(revision_ref(source_revision))
            else:
                raise ValueError("Unrecognized model source/preparation condition")
        if not 0 < len(resource_ids) <= 32 or not 0 < len(refs) <= 32:
            raise ValueError("Financial model source closure is incomplete")
        brain = owner_brain_scope(scope, owner.identity)
        grants = await require_resources(
            session, brain, tuple(sorted(resource_ids)), await db_now(session)
        )
        artifacts = []
        deadlines = [owner.expires_at]
        for source in refs:
            row = await session.get(
                BrainSourceRevision, (scope.company_id, source.source_revision_id)
            )
            if row is None:
                raise ValueError("Financial historical source disappeared")
            artifact = await source_artifact_reference(session, brain, row.artifact_revision_id)
            artifacts.append(artifact)
            deadlines.extend(
                await self.planning.sources.artifacts.revalidate_historical_artifact_reference(
                    session, control, brain, owner.identity, artifact, await db_now(session)
                )
            )
        deadlines.extend(
            await freshness.revalidate_historical_references(
                session, brain, tuple(artifacts), await db_now(session)
            )
        )
        current_heads = await heads(session, brain, tuple(refs))
        qualified = await freshness.capture_plan_heads_locked(
            session, brain, tuple(sorted(row.source_id for row in refs)), await db_now(session)
        )
        if header is not None:
            required = (
                tuple(
                    ResourceRevision(
                        resource=f"brain.resource:{row.resource_id}",
                        revision=f"acl:{row.generation}",
                    )
                    for row in header.contributors
                )
                + tuple(
                    ResourceRevision(
                        resource=f"brain.source:{row.source_id}",
                        revision=f"head:{row.generation}:{row.current.source_revision_id}",
                    )
                    for row in header.source_heads
                )
                + (reference.condition,)
            )
            work = selected.directory.work
            if (
                work is None
                or header.parameters.model_dump(mode="json") != action.parameters
                or header.company_id != scope.company_id
                or header.action_id != action.action_id
                or (header.task_id, header.trace_id, header.actor_id, header.workspace_id)
                != (
                    action.task_id,
                    action.trace_id,
                    action.actor_id,
                    selected.directory.workspace_id,
                )
                or header.run_id != work.registration.run_id
                or header.registration_sha256 != registration_digest(work.registration)
                or header.input_recipe_sha256 != canonical_sha256(self.planning.recipe)
                or selected.action.approval is None
                or header.owner_id != selected.action.approval.approver_id
                or header.goal != self.admission.goal
                or header.plan_id != self.admission.plan_id
                or required != action.preconditions
            ):
                raise ValueError("Financial saved header differs from exact native source closure")
        before = clock_us()
        final = await db_now(session)
        deadlines.extend(row.expires_at for row in grants if row.expires_at is not None)
        if any(value <= final for value in deadlines):
            raise ValueError("Financial source access expired")
        end = min(
            end, *(before + (value - final) // timedelta(microseconds=1) for value in deadlines)
        )
        self._owner(scope, owner, control, end)
        signature = canonical_sha256(
            HistoricalCostSources(
                grants=grants, heads=current_heads, policies=tuple(row.policy for row in qualified)
            )
        )
        return signature, end

    async def _gate(
        self,
        scope: CompanyControlScope,
        owner: AuthenticatedWorkerIdentity,
        action_id: UUID,
        header: PlanningPreparedDescriptor | None,
        end: int,
        expected: NativeCostSelection | None = None,
    ) -> tuple[NativeCostSelection, str | None, int]:
        async with management_owner_transaction(
            self.factory, scope, owner.identity, allow_paused=True
        ) as (session, control, _):
            self._owner(scope, owner, control, end)
            selected = await native_cost_selection(session, scope.company_id, action_id)
            slot = self.admission.slots[0]
            if (
                action_hash(selected.action.proposal) != selected.action.proposal_hash
                or selected.directory.task_id != slot.work.task_id
                or selected.directory.root_task_id != self.admission.procedure.binding.task_id
                or selected.directory.parent_task_id != self.admission.procedure.binding.task_id
                or selected.directory.work is None
                or selected.directory.work.registration
                != registration(slot.child.binding, slot.work, slot.child.quota)
                or not await stored_coding_profile(session, self.admission)
            ):
                return selected, None, end
            if expected is not None and selected != expected:
                raise ManagementDeniedError("Financial native model changed during protected read")
            try:
                signature, end = await self._sources(
                    session, control, scope, owner, selected, header, end
                )
            except ValueError:
                signature = None
            self._owner(scope, owner, control, end)
            return selected, signature, end

    def _physical(
        self, artifact: ArtifactRef, action_id: UUID, request_id: UUID
    ) -> tuple[tuple[int, ...], ...]:
        path = self.evidence._path(artifact.company_id, action_id, request_id)
        if Path(artifact.reference) != path:
            raise ValueError("Financial model artifact has another storage path")
        observed: list[tuple[int, ...]] = []
        for directory in (self.evidence._root, path.parent.parent, path.parent):
            row = directory.stat(follow_symlinks=False)
            if (
                not stat.S_ISDIR(row.st_mode)
                or stat.S_IMODE(row.st_mode) != 0o700
                or row.st_uid != os.getuid()
                or directory.resolve() != directory
            ):
                raise ValueError("Financial model root is not private/owned")
            observed.append((row.st_dev, row.st_ino, row.st_mode, row.st_uid))
        row = path.stat(follow_symlinks=False)
        if (
            not stat.S_ISREG(row.st_mode)
            or stat.S_IMODE(row.st_mode) != 0o400
            or row.st_uid != os.getuid()
            or row.st_nlink != 1
        ):
            raise ValueError("Financial model record is not immutable/private")
        observed.append(
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
        return tuple(observed)

    def _partial(self, owner: AuthenticatedWorkerIdentity, end: int, blocker: str) -> ModelCostRead:
        require_time(end)
        owner.require_time(datetime.now(UTC))
        self.require_composition()
        return ModelCostRead(None, (blocker,), end)

    async def read(
        self,
        scope: CompanyControlScope,
        owner: AuthenticatedWorkerIdentity,
        action_id: UUID,
        *,
        end_us: int,
    ) -> ModelCostRead:
        end = cost_read_end(scope, owner, end_us)
        selected, signature, end = await self.owned(
            self._gate(scope, owner, action_id, None, end), end
        )
        if (
            self.coding is not None
            and selected.directory.task_id == self.admission.slots[1].work.task_id
        ):
            from nexus.company.management.cycle_coding_reader import read_coding_cost

            return await read_coding_cost(self, scope, owner, selected, end_us=end)
        if signature is None or self.planning is None:
            return self._partial(owner, end, "source_proof_unavailable")
        action = selected.action.proposal
        try:
            parameters = PlanningModelParameters.model_validate_json(json.dumps(action.parameters))
        except ValueError:
            return self._partial(owner, end, "native_model_parameters_invalid")
        artifact = native_model_artifact(scope, selected, parameters)
        if artifact is None:
            return self._partial(owner, end, "model_record_not_readable")
        try:
            reference = prepared_reference(action)
            descriptor = await self.owned(self.planning._read(reference.descriptor, end), end)
            header = decode_descriptor(descriptor, reference)
            selected, second, end = await self.owned(
                self._gate(scope, owner, action_id, header, end, selected), end
            )
            if second is None or second != signature:
                return self._partial(owner, end, "source_read_changed")
            before = await self.owned(
                asyncio.to_thread(self._physical, artifact, action_id, parameters.request_id), end
            )
            record = await self.owned(self.evidence.load_record(artifact), end)
            evidence = record.evidence
            after = await self.owned(
                asyncio.to_thread(self._physical, artifact, action_id, parameters.request_id), end
            )
            if before != after:
                return self._partial(owner, end, "model_record_changed")
        except TimeoutError:
            # A timed-out owned read still has its actual task. It cannot be
            # converted into a late ordinary partial-result publication.
            raise
        except (ValueError, OSError):
            return self._partial(owner, end, "protected_record_unavailable")
        final, final_signature, end = await self.owned(
            self._gate(scope, owner, action_id, header, end, selected), end
        )
        if final_signature is None or final_signature != signature:
            return self._partial(owner, end, "source_read_changed")
        work = final.directory.work
        assert work is not None
        fact = join_cycle_model_fact(
            final.directory.directory_data(),
            work,
            final.action,
            evidence.request,
            self.planning.recipe,
            self.catalog.models,
            attempt=final.attempt.native_data() if final.attempt else None,
            intent=final.intent,
            hold=final.hold.native_data() if final.hold else None,
            artifact=artifact,
            evidence=evidence,
            wire=record.wire,
        )
        fact.model_dump_json()
        require_time(end)
        owner.require_time(datetime.now(UTC))
        self.require_composition()
        return ModelCostRead(
            fact, fact.blockers, end, signature, ModelSourceProof(final, header, signature)
        )

    async def revalidate_locked(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: CompanyControlScope,
        owner: AuthenticatedWorkerIdentity,
        result: ModelCostRead,
        end: int,
    ) -> ModelCostRead:
        """No private bytes; final native/source recheck in the snapshot's SAME CC transaction."""
        self._owner(scope, owner, control, end)
        if result.fact is None or result.proof is None:
            return result
        proof = result.proof
        if proof.coding is not None:
            if self.coding is None:
                return ModelCostRead(
                    None, ("source_proof_unavailable",), min(end, result.read_end_us)
                )
            signature, end = await self.coding.validate_locked(
                session,
                control,
                scope,
                owner,
                proof.coding,
                proof.selection,
                min(end, result.read_end_us),
            )
            self._owner(scope, owner, control, end)
            if signature is None or signature != proof.signature:
                return ModelCostRead(None, ("source_read_changed",), end)
            return ModelCostRead(result.fact, result.blockers, end, signature, proof)
        if proof.header is None:
            return ModelCostRead(None, ("source_proof_unavailable",), min(end, result.read_end_us))
        current = await native_cost_selection(
            session, scope.company_id, proof.selection.action.proposal.action_id
        )
        if current != proof.selection:
            raise ManagementDeniedError(
                "Financial native model changed before snapshot serialization"
            )
        try:
            signature, end = await self._sources(
                session, control, scope, owner, current, proof.header, min(end, result.read_end_us)
            )
        except ValueError:
            self._owner(scope, owner, control, end)
            return ModelCostRead(None, ("source_read_changed",), min(end, result.read_end_us))
        self._owner(scope, owner, control, end)
        if signature != proof.signature:
            return ModelCostRead(None, ("source_read_changed",), end)
        return ModelCostRead(result.fact, result.blockers, end, signature, proof)

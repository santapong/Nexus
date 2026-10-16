"""Actual owner plan approval and native registration share one company-first transaction."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management.cancellation_support import require_plan_not_cancelled
from nexus.company.management.control_support import ManagementConflictError, db_clock, require_cas
from nexus.company.management.cycle_admission_contracts import require_exact_cycle_quota
from nexus.company.management.cycle_catalog_checks import validate_cycle_catalog
from nexus.company.management.lifecycle import PlanRevision
from nexus.company.management.nexus_coding_catalog import configured_nexus_admission
from nexus.company.management.plan_models import (
    ManagementOwnerDecision,
    ManagementPlanHead,
    ManagementPlanRevision,
    ManagementPlanTask,
    ManagementProcedure,
)
from nexus.company.management.plan_registration import (
    ensure_procedure,
    register_children,
    require_native_task,
)
from nexus.company.management.plan_support import (
    CurrentPlanBinding,
    PlanAdmissionCatalog,
    PlanSourceFreshness,
    validate_plan,
)
from nexus.company.management.plan_transition_store import (
    approve_transition_locked,
    propose_transition_locked,
)
from nexus.company.management.plans import PlanPayload
from nexus.company.management.revision_store import (
    consume_revision,
    decision_locked,
    plan_record,
    plan_reference,
    propose_locked,
)
from nexus.company.management.strategy_transition import is_full_transition
from nexus.company.management.transactions import (
    ManagementDeniedError,
    management_owner_transaction,
)
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.journal_models import CompanyControl

if TYPE_CHECKING:
    from nexus.company.management.planning_source_reader import PlanningSourceReader
    from nexus.company.strategy.current_proof_reader import StrategyCurrentProofReader


# This cohesive >400-line store keeps both exact-origin checks adjacent to the
# existing atomic proposal/approval, permanent root and replay registration gates.
class ManagementPlanStore:
    """No intake endpoint, model invocation, dispatch or paid authority is installed here."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        catalog: PlanAdmissionCatalog,
        *,
        source_freshness: PlanSourceFreshness | None = None,
        strategy_proof_reader: StrategyCurrentProofReader | None = None,
        planning_reader: PlanningSourceReader | None = None,
    ) -> None:
        validate_cycle_catalog(catalog.cycle_admission, catalog)
        configured_nexus_admission(catalog)
        self.factory, self.catalog = (
            factory,
            PlanAdmissionCatalog.model_validate_json(catalog.model_dump_json()),
        )
        self.directory = PersistentCompanyDirectory(factory)
        self.source_freshness = source_freshness
        self.strategy_proof_reader = strategy_proof_reader
        self.planning_reader = planning_reader
        if planning_reader is not None:
            from nexus.company.management.planning_source_reader import PlanningSourceReader

            if (
                type(planning_reader) is not PlanningSourceReader
                or planning_reader.factory is not factory
                or planning_reader.template.configured_admission
                != configured_nexus_admission(self.catalog)
            ):
                raise ManagementDeniedError(
                    "Planning reader must share the exact PlanStore factory"
                )
        if strategy_proof_reader is not None:
            from nexus.company.strategy.current_proof_reader import StrategyCurrentProofReader

            if (
                not isinstance(strategy_proof_reader, StrategyCurrentProofReader)
                or strategy_proof_reader.reader.artifacts.factory is not factory
                or source_freshness is not strategy_proof_reader.reader.freshness
            ):
                raise ManagementDeniedError(
                    "Strategy reader must share the exact plan-store factory"
                )

    async def propose(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        payload: PlanPayload,
        *,
        expected_current_revision_id: UUID | None,
        credential: AuthenticatedWorkerIdentity | None = None,
        end_us: int | None = None,
    ) -> PlanRevision:
        """Save a fully validated immutable proposal without reserving any root or child."""
        from nexus.company.management.planning_native_facts import read_end

        origin_end = (
            read_end(end_us)
            if (
                payload.planning_origin is not None
                or configured_nexus_admission(self.catalog) is not None
            )
            else None
        )
        if payload.planning_origin is not None and (
            self.planning_reader is None or self.planning_reader.factory is not self.factory
        ):
            raise ManagementDeniedError("Planning origin requires its configured concrete reader")
        for quota in (payload.procedure.quota, *(row.quota for row in payload.children)):
            require_exact_cycle_quota(quota)
        payload = PlanPayload.model_validate(payload.model_dump(warnings=False))
        async with management_owner_transaction(self.factory, scope, identity) as (
            session,
            control,
            _,
        ):
            await require_plan_not_cancelled(session, scope.company_id, payload)
            from nexus.company.management.nexus_plan_admission import (
                capture_nexus_owner_locked,
                finish_nexus_owner_locked,
                require_nexus_exit,
            )

            first_nexus = await capture_nexus_owner_locked(
                self,
                session,
                control,
                scope,
                identity,
                payload,
                credential,
                end_us=origin_end if origin_end is not None else read_end(end_us),
            )
            if payload.planning_origin is not None:
                assert self.planning_reader is not None and origin_end is not None
                await self.planning_reader.revalidate_locked(
                    session,
                    control,
                    scope,
                    identity,
                    payload,
                    target_revision_id=None,
                    end_us=origin_end,
                )
            if is_full_transition(payload, self.catalog):
                return await propose_transition_locked(
                    self,
                    session,
                    control,
                    scope,
                    identity,
                    payload,
                    expected_current_revision_id,
                    credential,
                )
            await validate_plan(
                session, control, scope, identity, payload, self.catalog, self.source_freshness
            )
            record = await propose_locked(
                session, scope, payload, expected_current_revision_id, await db_clock(session)
            )
            await validate_plan(
                session, control, scope, identity, payload, self.catalog, self.source_freshness
            )
            if payload.planning_origin is not None:
                assert self.planning_reader is not None and origin_end is not None
                await self.planning_reader.revalidate_locked(
                    session,
                    control,
                    scope,
                    identity,
                    payload,
                    target_revision_id=record.plan_revision_id,
                    end_us=origin_end,
                )
            await finish_nexus_owner_locked(
                self, session, control, scope, identity, payload, credential, first_nexus
            )
        if origin_end is not None:
            from nexus.company.management.planning_native_facts import require_time

            require_time(origin_end)
        require_nexus_exit(first_nexus)
        return record

    async def approve_and_register(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        plan_revision_id: UUID,
        exact_hash: str,
        *,
        expected_current_revision_id: UUID | None,
        credential: AuthenticatedWorkerIdentity | None = None,
        end_us: int | None = None,
    ) -> PlanRevision:
        """Approve exact stored data and atomically delegate each existing/new M1 registration."""
        from nexus.company.management.planning_native_facts import read_end

        origin_end = read_end(end_us)
        async with management_owner_transaction(self.factory, scope, identity) as (
            session,
            control,
            _,
        ):
            record, head = await self._target(session, scope, plan_revision_id, exact_hash)
            from nexus.company.management.nexus_plan_admission import (
                capture_nexus_owner_locked,
                finish_nexus_owner_locked,
                require_nexus_exit,
            )

            first_nexus = await capture_nexus_owner_locked(
                self,
                session,
                control,
                scope,
                identity,
                record.payload,
                credential,
                end_us=origin_end,
            )
            if record.payload.planning_origin is not None:
                if self.planning_reader is None or self.planning_reader.factory is not self.factory:
                    raise ManagementDeniedError(
                        "Planning origin requires its configured concrete reader"
                    )
                await self.planning_reader.revalidate_locked(
                    session,
                    control,
                    scope,
                    identity,
                    record.payload,
                    target_revision_id=record.plan_revision_id,
                    end_us=origin_end,
                )
            await require_plan_not_cancelled(session, scope.company_id, record.payload)
            if is_full_transition(record.payload, self.catalog):
                return await approve_transition_locked(
                    self,
                    session,
                    control,
                    scope,
                    identity,
                    record,
                    head,
                    expected_current_revision_id,
                    credential,
                )
            charters = await validate_plan(
                session,
                control,
                scope,
                identity,
                record.payload,
                self.catalog,
                self.source_freshness,
            )
            already_approved = (
                head.state == "approved" and head.current_revision_id == record.plan_revision_id
            )
            if not already_approved:
                require_cas(head.current_revision_id, expected_current_revision_id)
                if head.state == "revoked" and head.current_revision_id == record.plan_revision_id:
                    raise ManagementDeniedError(
                        "A revoked plan needs an explicit new bounded revision"
                    )
                now = await db_clock(session)
                procedure = await ensure_procedure(
                    session, self.directory, scope, identity, record.payload, now
                )
                decision = await decision_locked(session, scope, record, "approve", now)
                await consume_revision(session, scope, record, procedure, decision.decision_id, now)
                await register_children(
                    session,
                    self.directory,
                    scope,
                    identity,
                    record.payload,
                    record.plan_revision_id,
                    charters,
                )
                head.current_revision_id, head.state = record.plan_revision_id, "approved"
                head.procedure_id, head.decision_id = procedure.procedure_id, decision.decision_id
                await session.flush()
                await validate_plan(
                    session,
                    control,
                    scope,
                    identity,
                    record.payload,
                    self.catalog,
                    self.source_freshness,
                )
            if record.payload.planning_origin is not None:
                assert self.planning_reader is not None
                await self.planning_reader.revalidate_locked(
                    session,
                    control,
                    scope,
                    identity,
                    record.payload,
                    target_revision_id=record.plan_revision_id,
                    end_us=origin_end,
                )
            await finish_nexus_owner_locked(
                self, session, control, scope, identity, record.payload, credential, first_nexus
            )
        if record.payload.planning_origin is not None or first_nexus is not None:
            from nexus.company.management.planning_native_facts import require_time

            require_time(origin_end)
        require_nexus_exit(first_nexus)
        return record

    async def revoke(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        plan_revision_id: UUID,
        exact_hash: str,
        *,
        expected_current_revision_id: UUID | None,
    ) -> PlanRevision:
        """Revoke its native head; no registered work/counter/hold is deleted or refunded."""
        async with management_owner_transaction(
            self.factory, scope, identity, allow_paused=True
        ) as (session, _, _):
            record, head = await self._target(session, scope, plan_revision_id, exact_hash)
            require_cas(head.current_revision_id, expected_current_revision_id)
            if head.current_revision_id != record.plan_revision_id or head.state == "proposed":
                raise ManagementDeniedError("Only the current approved/revoked plan can be revoked")
            if head.state == "revoked":
                return record
            decision = await decision_locked(
                session, scope, record, "revoke", await db_clock(session)
            )
            head.state, head.decision_id = "revoked", decision.decision_id
            await session.flush()
            return record

    @staticmethod
    async def _target(
        session: AsyncSession,
        scope: CompanyControlScope,
        revision_id: UUID,
        exact_hash: str,
    ) -> tuple[PlanRevision, ManagementPlanHead]:
        row = await session.get(ManagementPlanRevision, (scope.company_id, revision_id))
        if row is None:
            raise ManagementDeniedError("Exact management plan is unavailable")
        record = plan_record(row)
        head = await session.get(ManagementPlanHead, (scope.company_id, record.plan_id))
        if head is None or record.sha256 != exact_hash:
            raise ManagementConflictError("Exact management plan revision/hash differs")
        return record, head

    @staticmethod
    async def managed_kind(session: AsyncSession, company_id: UUID, task_id: UUID) -> str:
        """Distinguish permanent nonexecuting roots and historical managed work from M1 work."""
        parent = await session.scalar(
            select(ManagementProcedure).where(
                ManagementProcedure.company_id == company_id,
                ManagementProcedure.parent_task_id == task_id,
            )
        )
        if parent is not None:
            return "procedure"
        task = await session.scalar(
            select(ManagementPlanTask)
            .where(
                ManagementPlanTask.company_id == company_id, ManagementPlanTask.task_id == task_id
            )
            .limit(1)
        )
        return "managed" if task is not None else "unmanaged"

    @staticmethod
    async def current_binding(
        session: AsyncSession,
        company_id: UUID,
        task_id: UUID,
    ) -> CurrentPlanBinding | None:
        """Read the current approved child; missing binding never proves unmanaged work."""
        # Keep the >50-line latest-owner-decision and native head/task lookup adjacent.
        historical = await session.scalar(
            select(ManagementPlanTask)
            .where(
                ManagementPlanTask.company_id == company_id, ManagementPlanTask.task_id == task_id
            )
            .limit(1)
        )
        if historical is None:
            return None
        revision = await session.scalar(
            select(ManagementPlanRevision)
            .join(
                ManagementOwnerDecision,
                (ManagementOwnerDecision.company_id == ManagementPlanRevision.company_id)
                & (
                    ManagementOwnerDecision.plan_revision_id
                    == ManagementPlanRevision.plan_revision_id
                ),
            )
            .where(
                ManagementPlanRevision.company_id == company_id,
                ManagementPlanRevision.goal_id == historical.goal_id,
                ManagementOwnerDecision.kind == "approve",
            )
            .order_by(
                ManagementOwnerDecision.recorded_at.desc(),
                ManagementOwnerDecision.decision_id.desc(),
            )
            .limit(1)
        )
        if revision is None:
            return None
        head = await session.get(ManagementPlanHead, (company_id, revision.plan_id))
        if (
            head is None
            or head.state != "approved"
            or head.current_revision_id != revision.plan_revision_id
        ):
            return None
        decision = await session.get(ManagementOwnerDecision, (company_id, head.decision_id))
        control = await session.get(CompanyControl, company_id)
        if (
            decision is None
            or control is None
            or (
                decision.kind,
                decision.plan_revision_id,
                decision.payload_sha256,
                decision.owner_id,
            )
            != ("approve", revision.plan_revision_id, revision.sha256, control.owner_id)
        ):
            raise ManagementDeniedError("Current managed plan has no exact actual owner approval")
        row = await session.get(
            ManagementPlanTask, (company_id, revision.plan_revision_id, task_id)
        )
        if row is None:
            return None
        execution = await session.get(ExecutionWork, (company_id, task_id))
        if revision is None or execution is None or execution.registration_hash != row.work_sha256:
            raise ManagementDeniedError("Managed work has inconsistent immutable registration")
        record = plan_record(revision)
        child = next(value for value in record.payload.children if value.binding.task_id == task_id)
        item = next(value for value in record.payload.plan.items if value.task_id == task_id)
        require_native_task(row, execution, child, record.payload)
        return CurrentPlanBinding(
            company_id=company_id,
            plan=plan_reference(record),
            child=child,
            work=item,
            work_sha256=row.work_sha256,
            procedure_id=row.procedure_id,
        )

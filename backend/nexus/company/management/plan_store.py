"""Actual owner plan approval and native registration share one company-first transaction."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management.cancellation_support import require_plan_not_cancelled
from nexus.company.management.control_support import ManagementConflictError, db_clock, require_cas
from nexus.company.management.lifecycle import PlanRevision
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
from nexus.company.management.plans import PlanPayload
from nexus.company.management.revision_store import (
    consume_revision,
    decision_locked,
    plan_record,
    plan_reference,
    propose_locked,
)
from nexus.company.management.transactions import (
    ManagementDeniedError,
    management_owner_transaction,
)
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.journal_models import CompanyControl


class ManagementPlanStore:
    """No intake endpoint, model invocation, dispatch or paid authority is installed here."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        catalog: PlanAdmissionCatalog,
        *,
        source_freshness: PlanSourceFreshness | None = None,
    ) -> None:
        self.factory, self.catalog = (
            factory,
            PlanAdmissionCatalog.model_validate_json(catalog.model_dump_json()),
        )
        self.directory = PersistentCompanyDirectory(factory)
        self.source_freshness = source_freshness

    async def propose(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        payload: PlanPayload,
        *,
        expected_current_revision_id: UUID | None,
    ) -> PlanRevision:
        """Save a fully validated immutable proposal without reserving any root or child."""
        payload = PlanPayload.model_validate_json(payload.model_dump_json(by_alias=True))
        async with management_owner_transaction(self.factory, scope, identity) as (
            session,
            control,
            _,
        ):
            await require_plan_not_cancelled(session, scope.company_id, payload)
            await validate_plan(
                session, control, scope, identity, payload, self.catalog, self.source_freshness
            )
            record = await propose_locked(
                session, scope, payload, expected_current_revision_id, await db_clock(session)
            )
            await validate_plan(
                session, control, scope, identity, payload, self.catalog, self.source_freshness
            )
            return record

    async def approve_and_register(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        plan_revision_id: UUID,
        exact_hash: str,
        *,
        expected_current_revision_id: UUID | None,
    ) -> PlanRevision:
        """Approve exact stored data and atomically delegate each existing/new M1 registration."""
        async with management_owner_transaction(self.factory, scope, identity) as (
            session,
            control,
            _,
        ):
            record, head = await self._target(session, scope, plan_revision_id, exact_hash)
            await require_plan_not_cancelled(session, scope.company_id, record.payload)
            charters = await validate_plan(
                session,
                control,
                scope,
                identity,
                record.payload,
                self.catalog,
                self.source_freshness,
            )
            if head.state == "approved" and head.current_revision_id == record.plan_revision_id:
                return record
            require_cas(head.current_revision_id, expected_current_revision_id)
            if head.state == "revoked" and head.current_revision_id == record.plan_revision_id:
                raise ManagementDeniedError("A revoked plan needs an explicit new bounded revision")
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

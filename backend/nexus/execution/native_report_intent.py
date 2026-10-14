"""Complete native compilation and current resource checks before consuming an effect attempt."""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.access_contracts import ResourceGeneration
from nexus.company.brain.access_support import require_resources
from nexus.company.brain.source_models import BrainSourceHead
from nexus.company.contracts.actions import ActionProposal, ResourceRevision
from nexus.company.management.generated_artifact_contracts import GeneratedArtifactPayload
from nexus.company.management.generated_artifact_privacy import GeneratedProtection, protect_inputs
from nexus.company.management.generated_artifact_scope import action_expiry, generated_scope
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plan_support import validate_plan_profile
from nexus.company.management.plans import ChildAllocation
from nexus.company.management.report_inputs import native_author
from nexus.execution.native_report_context import NativeReportContext
from nexus.execution.runtime_contracts import ExecutionDeniedError
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import CompanyControl, JournalAction


class NativeReportIntent:
    """Server compiler recheck with a pure final-time boundary; no cached permission."""

    def __init__(
        self,
        context: NativeReportContext,
        prepared: GeneratedArtifactPayload,
        resources: tuple[ResourceRevision, ...],
    ) -> None:
        self.context, self.prepared, self.resources = context, prepared, resources
        self.grants: tuple[ResourceGeneration, ...] = ()
        self.deadlines: tuple[datetime, ...] = ()
        self.protection: GeneratedProtection | None = None
        self.child: ChildAllocation | None = None

    async def validate(
        self,
        session: AsyncSession,
        control: CompanyControl,
        work: ExecutionWork,
        action: JournalAction,
        now: datetime,
    ) -> None:
        """Compare full native facts and fresh actual resource revisions in this transaction."""
        context = self.context
        actual = ActionProposal.model_validate_json(action.proposal_json)
        if actual != context.action:
            raise ExecutionDeniedError("Native intent action differs from exact preparation")
        binding, _ = native_author(work)
        current_plan = await ManagementPlanStore.current_binding(
            session, work.company_id, work.task_id
        )
        if current_plan is None or current_plan.child.binding != binding:
            raise ExecutionDeniedError("Native intent current plan binding is unavailable")
        self.child = current_plan.child
        current = await context.services.resources.current(
            session, binding, actual, context.identity
        )
        if current != self.resources:
            raise ExecutionDeniedError("Native current resource conditions changed")
        scope = generated_scope(context.lease, actual.action_id)
        await context.services.publisher.validator.revalidate(
            session,
            control,
            scope,
            context.identity,
            context.lease,
            actual,
            self.prepared,
            now,
        )
        rule = context.services.publisher.rules.get(actual.tool)
        if rule is None:
            raise ExecutionDeniedError("Native intent output rule is unregistered")
        self.protection = await protect_inputs(
            session,
            control,
            scope,
            context.identity,
            self.prepared,
            rule,
            context.services.artifacts,
            context.services.publisher.freshness,
        )
        self.grants = await require_resources(
            session, scope, self.prepared.inputs.required_resource_ids, await db_now(session)
        )
        self.deadlines = (
            *await self.source_deadlines(session),
            await action_expiry(session, action),
        )
        self.validate_time(await db_now(session))

    def validate_time(self, now: datetime) -> None:
        """Refresh every prepared source/permission/lease deadline after all awaited checks."""
        if (
            not self.grants
            or not self.deadlines
            or any(value <= now for value in self.deadlines)
            or any(row.expires_at is not None and row.expires_at <= now for row in self.grants)
        ):
            raise ExecutionDeniedError("Native intent inputs or execute lease expired")
        if self.protection is None:
            raise ExecutionDeniedError("Native intent audience protection is unprepared")
        self.protection.require_time(now)
        if self.child is None:
            raise ExecutionDeniedError("Native intent profile qualification is unprepared")
        validate_plan_profile(self.context.services.publisher.catalog, self.child, now)

    async def source_deadlines(self, session: AsyncSession) -> tuple[datetime, ...]:
        """Capture actual bounded source windows for the pure final intent clock."""
        deadlines: list[datetime] = [self.context.lease.expires_at]
        for ref in self.prepared.inputs.contributors:
            head = await session.get(
                BrainSourceHead, (self.context.lease.company_id, ref.source_id)
            )
            if (
                head is None
                or head.current_revision_id != ref.source_revision_id
                or head.availability != "available"
            ):
                raise ExecutionDeniedError("Native intent source changed or is unavailable")
            if head.fresh_until is not None:
                deadlines.append(head.fresh_until)
        return tuple(deadlines)

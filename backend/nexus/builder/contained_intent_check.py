"""Current parent evidence participates in the same native intent transaction/final clock."""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.builder.contained_contracts import ParentObservation
from nexus.builder.contained_query import clock_us
from nexus.builder.contained_services import ContainmentServices
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.journal_models import CompanyControl, JournalAction


class ContainedParentIntentCheck:
    """Trusted read-only local parent check; the native store retains authority and one permit."""

    def __init__(self, services: ContainmentServices) -> None:
        self.services = services
        self.observed: ParentObservation | None = None

    async def validate(
        self,
        session: AsyncSession,
        control: CompanyControl,
        work: ExecutionWork,
        action: JournalAction,
        now: datetime,
    ) -> None:
        expected = self.services.expectation
        if (work.company_id, work.task_id, work.trace_id, work.run_id, action.id) != (
            expected.company_id,
            expected.task_id,
            expected.trace_id,
            expected.run_id,
            expected.action_id,
        ):
            raise ValueError("Contained parent intent binds another native job")
        self.observed = await self.services.observe()

    def validate_time(self, now: datetime) -> None:
        """Called after the actual final SQL clock; never reuse elapsed parent evidence."""
        if (
            self.observed is None
            or self.services.deadline is None
            or clock_us() >= min(self.observed.deadline_us, self.services.deadline.end_us)
        ):
            raise ValueError("Contained parent expired before native intent commit")

"""Current signed-owner audit views are available paused and create no execution authority."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.management.control_support import db_clock
from nexus.company.management.operation_models import (
    ManagementCommitmentHead,
    ManagementCommitmentRevision,
)
from nexus.company.management.owner_view_approvals import approvals_page
from nexus.company.management.owner_view_budget import company_budget
from nexus.company.management.owner_view_contracts import (
    ApprovalPage,
    CommitmentView,
    CompanyView,
    OwnerViewPage,
    PlanView,
    TodayView,
    WorkView,
)
from nexus.company.management.owner_view_governance import observe_commitment, observe_goal
from nexus.company.management.owner_view_plan import observe_plan, selected_revision
from nexus.company.management.owner_view_queries import (
    charter_page,
    commitment_page,
    goal_page,
    mandate_view,
    plan_page,
)
from nexus.company.management.owner_view_sources import OwnerViewSources
from nexus.company.management.owner_view_work import observe_work
from nexus.company.management.transactions import (
    ManagementDeniedError,
    management_owner_transaction,
)
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.journal_models import CompanyControl

DEFAULT_PAGE = OwnerViewPage()


class ManagementOwnerViews:
    def __init__(
        self, factory: async_sessionmaker[AsyncSession], sources: OwnerViewSources | None = None
    ) -> None:
        self.factory, self.sources = factory, sources

    async def company(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        *,
        page: OwnerViewPage = DEFAULT_PAGE,
    ) -> CompanyView:
        page = OwnerViewPage.model_validate_json(page.model_dump_json())
        async with management_owner_transaction(
            self.factory, scope, identity, allow_paused=True
        ) as (
            session,
            control,
            _,
        ):
            mandate = await mandate_view(session, scope.company_id)
            charters, next_charter = await charter_page(session, scope.company_id, page)
            goals, next_goal = await goal_page(session, scope.company_id, page)
            observations = tuple(
                [
                    await observe_goal(session, control, scope, identity, row, active, self.sources)
                    for row, active in goals
                ]
            )
            plans, next_plan = await plan_page(session, scope.company_id, page)
            declarations, next_commitment = await commitment_page(session, scope.company_id, page)
            commitments = tuple(
                [await observe_commitment(session, control, scope, row) for row in declarations]
            )
            budget = await company_budget(session, control)
            now = await db_clock(session)
            return CompanyView(
                company_id=scope.company_id,
                observed_at=now,
                owner_id=control.owner_id,
                paused=control.paused,
                budget=budget,
                mandate=mandate,
                charters=charters,
                goals=tuple(row.render(now) for row in observations),
                plans=plans,
                commitments=commitments,
                next_charter_after_id=next_charter,
                next_goal_after_id=next_goal,
                next_plan_after_id=next_plan,
                next_commitment_after_id=next_commitment,
            )

    async def today(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        *,
        page: OwnerViewPage = DEFAULT_PAGE,
    ) -> TodayView:
        page = OwnerViewPage.model_validate_json(page.model_dump_json())
        async with management_owner_transaction(
            self.factory, scope, identity, allow_paused=True
        ) as (
            session,
            control,
            _,
        ):
            due, next_due = await due_commitments(
                session, control, scope, page, await db_clock(session)
            )
            decisions = await approvals_page(session, control, page, pending_only=True)
            budget = await company_budget(session, control)
            return TodayView(
                company_id=scope.company_id,
                observed_at=await db_clock(session),
                paused=control.paused,
                budget=budget,
                due=due,
                decisions=decisions,
                next_due_after_id=next_due,
            )

    async def plan(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        plan_id: UUID,
        *,
        revision_id: UUID | None = None,
    ) -> PlanView:
        async with management_owner_transaction(
            self.factory, scope, identity, allow_paused=True
        ) as (
            session,
            control,
            _,
        ):
            row, head = await selected_revision(session, scope.company_id, plan_id, revision_id)
            observed = await observe_plan(
                session, control, scope, identity, row, head, self.sources, await db_clock(session)
            )
            return observed.render(await db_clock(session))

    async def work(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        task_id: UUID,
    ) -> WorkView:
        async with management_owner_transaction(
            self.factory, scope, identity, allow_paused=True
        ) as (
            session,
            control,
            _,
        ):
            row = await session.get(ExecutionWork, (scope.company_id, task_id))
            if row is None:
                raise ManagementDeniedError("Owner work view is unavailable")
            result = await observe_work(session, control, scope, identity, row, self.sources)
            return result.render(await db_clock(session))

    async def approvals(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        *,
        page: OwnerViewPage = DEFAULT_PAGE,
    ) -> ApprovalPage:
        page = OwnerViewPage.model_validate_json(page.model_dump_json())
        async with management_owner_transaction(
            self.factory, scope, identity, allow_paused=True
        ) as (
            session,
            control,
            _,
        ):
            return await approvals_page(session, control, page)


async def due_commitments(
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    page: OwnerViewPage,
    now: datetime,
) -> tuple[tuple[CommitmentView, ...], UUID | None]:
    bangkok = ZoneInfo("Asia/Bangkok")
    tomorrow = now.astimezone(bangkok).date() + timedelta(days=1)
    end = datetime.combine(tomorrow, time(), bangkok)
    query = (
        select(ManagementCommitmentRevision)
        .join(
            ManagementCommitmentHead,
            (ManagementCommitmentHead.company_id == ManagementCommitmentRevision.company_id)
            & (
                ManagementCommitmentHead.current_revision_id
                == ManagementCommitmentRevision.revision_id
            ),
        )
        .where(
            ManagementCommitmentRevision.company_id == scope.company_id,
            ManagementCommitmentRevision.actionable_at.is_not(None),
            ManagementCommitmentRevision.actionable_at < end,
        )
    )
    if page.after_id is not None:
        query = query.where(ManagementCommitmentRevision.commitment_id > page.after_id)
    rows = tuple(
        (
            await session.scalars(
                query.order_by(ManagementCommitmentRevision.commitment_id).limit(page.limit + 1)
            )
        ).all()
    )
    values: tuple[CommitmentView, ...] = tuple(
        [await observe_commitment(session, control, scope, row) for row in rows[: page.limit]]
    )
    return values, rows[page.limit - 1].commitment_id if len(rows) > page.limit else None

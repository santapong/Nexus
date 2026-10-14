"""Actual normal013 FK, SQL NULL, forced tenant scope and append-only enforcement."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.management.governance_models import ManagementGoalRevision
from nexus.company.management.metric_models import ManagementMetricObservation
from nexus.company.management.plans import PlanPayload
from nexus.tests.integration.test_company_directory import COMPANY, OWNER
from nexus.tests.metric_plan_fixture import declared_metric_plan
from nexus.tests.metric_schema_support import metric_schema_factory as metric_schema_factory


def schema_row(payload: PlanPayload, plan_revision_id: UUID) -> ManagementMetricObservation:
    """Schema-only row; this placeholder envelope is never business observation evidence."""
    return ManagementMetricObservation(
        company_id=COMPANY,
        observation_id=uuid4(),
        goal_id=payload.goal.goal_id,
        goal_revision_id=payload.goal.revision_id,
        plan_id=payload.plan.plan_id,
        plan_revision_id=plan_revision_id,
        metric_id="schema.fixture",
        recipe="schema-only",
        selection_count=1,
        value_kind="known",
        count_value=0,
        request_sha256="a" * 64,
        snapshot_sha256="b" * 64,
        record_sha256="c" * 64,
        request_json="{}",
        record_json="{}",
        recorded_by=OWNER,
        operation_id=uuid4(),
        audit_trace_id=uuid4(),
        observed_at=datetime.now(UTC),
    )


@pytest.mark.parametrize(
    ("failure", "constraint"),
    [
        ("old_goal", "fk_management_metric_plan"),
        ("missing_plan", "fk_management_metric_plan"),
        ("owner", "fk_management_metric_owner"),
        ("known_null", "ck_management_metric_value"),
        ("unknown_count", "ck_management_metric_value"),
        ("foreign_company", "row-level security"),
    ],
)
async def test_restricted_insert_rejects_wrong_exact_scope_or_nullable_known_count(
    metric_schema_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    failure: str,
    constraint: str,
) -> None:
    _, payload, _, _, _, _, plan = await declared_metric_plan(metric_schema_factory, tmp_path)
    row = schema_row(payload, plan.plan_revision_id)
    if failure == "old_goal":
        async with metric_schema_factory() as session, session.begin():
            await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
            old = await session.scalar(
                select(ManagementGoalRevision.revision_id).where(
                    ManagementGoalRevision.goal_id == payload.goal.goal_id,
                    ManagementGoalRevision.revision_id != payload.goal.revision_id,
                )
            )
            assert old is not None
            row.goal_revision_id = old
    elif failure == "missing_plan":
        row.plan_revision_id = uuid4()
    elif failure == "owner":
        row.recorded_by = uuid4()
    elif failure == "known_null":
        row.count_value = None
    elif failure == "foreign_company":
        row.company_id = uuid4()
    else:
        row.value_kind = "unknown"
    with pytest.raises(DBAPIError, match=constraint):
        async with metric_schema_factory() as session, session.begin():
            await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
            session.add(row)
            await session.flush()


async def test_native_metric_is_forced_scoped_immutable_and_query_indexed(
    metric_schema_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    _, payload, _, _, _, _, plan = await declared_metric_plan(metric_schema_factory, tmp_path)
    row = schema_row(payload, plan.plan_revision_id)
    async with metric_schema_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        session.add(row)
    for scope in (None, uuid4()):
        async with metric_schema_factory() as session, session.begin():
            if scope is not None:
                await session.execute(select(func.set_config("nexus.company_id", str(scope), True)))
            assert (await session.scalars(select(ManagementMetricObservation))).all() == []
    for statement in (
        update(ManagementMetricObservation).values(count_value=1),
        delete(ManagementMetricObservation),
    ):
        with pytest.raises(DBAPIError, match="Management history is immutable"):
            async with metric_schema_factory() as session, session.begin():
                await session.execute(
                    select(func.set_config("nexus.company_id", str(COMPANY), True))
                )
                await session.execute(statement)
    async with metric_schema_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        flags = (
            await session.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE oid = 'company_management_metric_observations'::regclass"
                )
            )
        ).one()
        assert flags == (True, True)
        await session.execute(text("SET LOCAL enable_seqscan = off"))
        result = await session.execute(
            text(
                "EXPLAIN SELECT observation_id FROM company_management_metric_observations "
                "WHERE company_id=:company AND goal_id=:goal AND metric_id=:metric "
                "ORDER BY observed_at, observation_id"
            ),
            {"company": COMPANY, "goal": payload.goal.goal_id, "metric": row.metric_id},
        )
        assert "ix_management_metric_goal" in "\n".join(str(value[0]) for value in result)

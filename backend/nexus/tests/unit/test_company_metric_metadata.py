"""Native observation metadata binds the exact goal revision chosen by the exact plan."""

from sqlalchemy import UniqueConstraint

from nexus.company.management.metric_models import ManagementMetricObservation
from nexus.company.management.model_base import ManagementBase
from nexus.company.management.plan_models import ManagementPlanRevision


def test_metric_plan_fk_cannot_splice_another_revision_of_the_same_goal() -> None:
    exact = ("company_id", "plan_id", "plan_revision_id", "goal_id", "goal_revision_id")
    metric = ManagementBase.metadata.tables[ManagementMetricObservation.__tablename__]
    plan = ManagementBase.metadata.tables[ManagementPlanRevision.__tablename__]
    constraints = metric.foreign_key_constraints
    native = next(row for row in constraints if row.name == "fk_management_metric_plan")
    assert tuple(native.column_keys) == exact
    assert tuple(item.column.name for item in native.elements) == exact
    assert exact in {
        tuple(column.name for column in row.columns)
        for row in plan.constraints
        if isinstance(row, UniqueConstraint)
    }


def test_metric_observation_queries_have_scoped_goal_and_plan_indexes() -> None:
    indexes = {
        tuple(column.name for column in index.columns)
        for index in ManagementBase.metadata.tables[
            ManagementMetricObservation.__tablename__
        ].indexes
    }
    assert ("company_id", "goal_id", "metric_id", "observed_at", "observation_id") in indexes
    assert any(columns[:3] == ("company_id", "plan_id", "plan_revision_id") for columns in indexes)

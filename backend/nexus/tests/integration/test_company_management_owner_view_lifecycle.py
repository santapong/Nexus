"""Explicit due instants and native cancellation remain distinct from declarations/activity."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from nexus.company.management.base import SourceTime
from nexus.company.management.cancellation_contracts import CancellationCommand
from nexus.company.management.cancellation_store import WorkCancellationStore
from nexus.company.management.control_support import db_clock
from nexus.company.management.goals import DueIntent
from nexus.company.management.operations import CommitmentDefinition
from nexus.tests.integration.test_company_directory import OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_management_acceptance import saved_m1
from nexus.tests.management_views_support import ViewsDatabase, configured_views
from nexus.tests.management_views_support import views_database as views_database


async def test_today_requires_operator_instant_and_selects_only_current_commitment_revision(
    views_database: ViewsDatabase,
    tmp_path: Path,
) -> None:
    views, store, _, _, definition = await configured_views(views_database, tmp_path)
    first = await store.publish(
        control(), identity(OWNER), definition, version="v1", expected_revision_id=None
    )
    assert (await views.today(control(), identity(OWNER))).due == ()
    async with views_database.admin() as session:
        now = await db_clock(session)
    changed = CommitmentDefinition.model_validate_json(
        definition.model_copy(
            update={
                "due": DueIntent(
                    source_time=SourceTime(
                        precision="unknown",
                        value=None,
                        basis="Owner supplied an actionable instant independently",
                    ),
                    actionable_at=now - timedelta(minutes=1),
                    actionable_basis="operator_explicit",
                ),
            }
        ).model_dump_json()
    )
    second = await store.publish(
        control(), identity(OWNER), changed, version="v2", expected_revision_id=first.revision_id
    )
    today = await views.today(control(), identity(OWNER))
    assert tuple(item.revision.revision_id for item in today.due) == (second.revision_id,)
    assert today.due[0].revision.definition.due.source_time.precision == "unknown"
    assert today.budget.daily.day == now.astimezone(ZoneInfo("Asia/Bangkok")).date()


async def test_explicit_cancellation_is_reported_without_activity_or_m1_fact_rewrite(
    views_database: ViewsDatabase,
    tmp_path: Path,
) -> None:
    views, _, _, payload, _ = await configured_views(views_database, tmp_path)
    stopped = await WorkCancellationStore(views_database.app).cancel(
        control().model_copy(update={"operation_id": uuid4()}),
        identity(OWNER),
        CancellationCommand(
            company_id=payload.company_id,
            target=payload.procedure.binding,
            reason="Owner stopped this exact goal procedure",
        ),
    )
    before = await saved_m1(views_database.app)
    child = await views.work(control(), identity(OWNER), payload.children[0].binding.task_id)
    assert child.registered_active and child.lineage_active
    assert child.cancellation is not None and child.cancellation.inherited
    assert child.cancellation.cancellation == stopped
    assert child.execution_state == "eligible"
    assert await saved_m1(views_database.app) == before

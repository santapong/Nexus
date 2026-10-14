"""Real immutable owner commitments bind native approval and preserve unknown source dates."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from nexus.company.management.base import SourceTime
from nexus.company.management.control_support import ManagementConflictError
from nexus.company.management.goals import DueIntent
from nexus.company.management.operations import CommitmentDefinition
from nexus.company.management.transactions import ManagementDeniedError
from nexus.tests.integration.test_company_directory import OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_management_acceptance import saved_m1
from nexus.tests.management_views_support import ViewsDatabase, configured_views
from nexus.tests.management_views_support import views_database as views_database


async def test_exact_commitment_replay_and_cas_preserve_current_head_and_m1(
    views_database: ViewsDatabase,
    tmp_path: Path,
) -> None:
    views, store, _, _, definition = await configured_views(views_database, tmp_path)
    before = await saved_m1(views_database.app)
    first = await store.publish(
        control(), identity(OWNER), definition, version="v1", expected_revision_id=None
    )
    changed = CommitmentDefinition.model_validate_json(
        definition.model_copy(
            update={
                "due": DueIntent(
                    source_time=SourceTime(
                        precision="day", value="2026-10-31", basis="Partial owner-supplied date"
                    )
                ),
            }
        ).model_dump_json()
    )
    with pytest.raises(ManagementConflictError):
        await store.publish(
            control(), identity(OWNER), changed, version="v2", expected_revision_id=None
        )
    second = await store.publish(
        control(), identity(OWNER), changed, version="v2", expected_revision_id=first.revision_id
    )
    replay = await store.publish(
        control(), identity(OWNER), definition, version="v1", expected_revision_id=uuid4()
    )
    assert (
        replay == first
        and await store.current(control(), identity(OWNER), definition.commitment_id) == second
    )
    assert second.definition.due.actionable_at is None
    assert second.definition.due.source_time.precision == "day"
    assert not (await views.today(control(), identity(OWNER))).due
    assert len(await store.history(control(), identity(OWNER), definition.commitment_id)) == 2
    assert await saved_m1(views_database.app) == before


async def test_changed_exact_work_or_unknown_responsible_cannot_create_commitment(
    views_database: ViewsDatabase,
    tmp_path: Path,
) -> None:
    _, store, _, _, definition = await configured_views(views_database, tmp_path)
    invalid = [
        definition.model_copy(update={"responsible_id": uuid4()}),
        definition.model_copy(
            update={"work": (definition.work[0].model_copy(update={"trace_id": uuid4()}),)}
        ),
    ]
    for value in invalid:
        with pytest.raises(ManagementDeniedError):
            await store.publish(
                control(), identity(OWNER), value, version="v1", expected_revision_id=None
            )
    assert await store.history(control(), identity(OWNER), definition.commitment_id) == ()


async def test_revoked_plan_blocks_new_commitment_but_preserves_owner_declaration_history(
    views_database: ViewsDatabase,
    tmp_path: Path,
) -> None:
    views, store, plans, _, definition = await configured_views(views_database, tmp_path)
    first = await store.publish(
        control(), identity(OWNER), definition, version="v1", expected_revision_id=None
    )
    await plans.revoke(
        control(),
        identity(OWNER),
        definition.plan.plan_revision_id,
        definition.plan.sha256,
        expected_current_revision_id=definition.plan.plan_revision_id,
    )
    with pytest.raises(ManagementDeniedError):
        await store.publish(
            control(),
            identity(OWNER),
            definition,
            version="v2",
            expected_revision_id=first.revision_id,
        )
    assert await store.current(control(), identity(OWNER), definition.commitment_id) == first
    company = await views.company(control(), identity(OWNER))
    assert company.commitments[0].binding_state == "stale"
    assert company.plans[0].state == "revoked"

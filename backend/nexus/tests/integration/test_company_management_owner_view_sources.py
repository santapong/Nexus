"""Actual private baseline permission and expiry guards omit data, not hidden-source counts."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.brain.access_models import BrainResource
from nexus.company.brain.evidence_models import BrainEvidence
from nexus.company.brain.retrieval import RetrievalLimits
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.brain.sources import EvidenceRef
from nexus.company.management.base import SourceTime
from nexus.company.management.goal_store import GoalStore
from nexus.company.management.goals import GoalDefinition, GoalRevisionRef, KnownBaseline
from nexus.company.management.governance_models import ManagementGoalRevision
from nexus.company.management.owner_view_contracts import CompanyBudget
from nexus.company.management.owner_view_governance import GoalObservation
from nexus.company.management.owner_view_sources import OwnerViewSources
from nexus.company.management.owner_view_store import ManagementOwnerViews
from nexus.harness.journal_models import CompanyControl
from nexus.tests.integration.test_company_brain_ingestion import owner_scope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.management_views_support import ViewsDatabase, configured_views
from nexus.tests.management_views_support import views_database as views_database


async def baseline_fixture(
    database: ViewsDatabase,
    root: Path,
) -> tuple[ManagementOwnerViews, GoalRevisionRef, ResourceRef]:
    views, _, plans, payload, _ = await configured_views(database, root)
    async with database.admin() as session:
        key = await session.scalar(select(BrainEvidence.evidence_id))
        from nexus.company.management.governance_models import ManagementGoalRevision

        row = await session.get(ManagementGoalRevision, (COMPANY, payload.goal.revision_id))
        assert key is not None and row is not None
        data = GoalDefinition.model_validate_json(row.payload_json)
    baseline = KnownBaseline(
        value=Decimal("994245"),
        observed_at=SourceTime(
            precision="day", value="2026-10-13", basis="PRIVATE_BASELINE_SOURCE"
        ),
        evidence=(EvidenceRef(company_id=COMPANY, evidence_id=key),),
    )
    changed = GoalDefinition.model_validate_json(
        data.model_copy(
            update={"metrics": (data.metrics[0].model_copy(update={"baseline": baseline}),)}
        ).model_dump_json()
    )
    assert views.sources is not None
    result = await GoalStore(
        database.app,
        PersistentBrainRetriever(
            database.app, views.sources.artifacts.blobs, limits=RetrievalLimits()
        ),
    ).publish(
        control(),
        identity(OWNER),
        changed,
        version="v2",
        expected_revision_id=payload.goal.revision_id,
    )
    reference = GoalRevisionRef.model_validate_json(
        result.model_dump_json(include=set(GoalRevisionRef.model_fields))
    )
    return views, reference, plans.catalog.resources[0].resource


async def test_private_baseline_disappears_when_actual_owner_source_read_is_revoked(
    views_database: ViewsDatabase,
    tmp_path: Path,
) -> None:
    views, _, resource = await baseline_fixture(views_database, tmp_path)
    first = await views.company(control(), identity(OWNER))
    assert first.goals[0].metrics[0].baseline is not None
    assert "PRIVATE_BASELINE_SOURCE" in first.model_dump_json()
    async with views_database.admin() as session:
        native = await session.get(BrainResource, (COMPANY, resource.resource_id))
        assert native is not None
    await ResourceAccessStore(views_database.app).change(
        owner_scope(),
        identity(OWNER),
        ResourceAccessChange(
            company_id=COMPANY,
            resource=resource,
            principal_id=OWNER,
            active=False,
            expected_generation=native.acl_generation,
        ),
    )
    hidden = await views.company(control(), identity(OWNER))
    assert hidden.goals[0].metrics[0].baseline is None
    assert "PRIVATE_BASELINE_SOURCE" not in hidden.model_dump_json()
    assert "994245" not in hidden.model_dump_json()


async def test_expiry_during_later_budget_queries_redacts_earlier_admitted_baseline(
    views_database: ViewsDatabase,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.company.management import owner_view_store
    from nexus.company.management.control_support import db_clock

    views, _, resource = await baseline_fixture(views_database, tmp_path)
    async with views_database.admin() as session:
        native = await session.get(BrainResource, (COMPANY, resource.resource_id))
        assert native is not None
        now = await db_clock(session)
    await ResourceAccessStore(views_database.app).change(
        owner_scope(),
        identity(OWNER),
        ResourceAccessChange(
            company_id=COMPANY,
            resource=resource,
            principal_id=OWNER,
            active=True,
            expected_generation=native.acl_generation,
            expires_at=now + timedelta(seconds=1.2),
        ),
    )
    from nexus.company.management.owner_view_budget import company_budget as budget
    from nexus.company.management.owner_view_governance import observe_goal as observe

    admitted = False

    async def admitted_goal(
        session: AsyncSession,
        current: CompanyControl,
        scope: CompanyControlScope,
        signed: VerifiedIdentity,
        row: ManagementGoalRevision,
        active: bool,
        sources: OwnerViewSources | None,
    ) -> GoalObservation:
        nonlocal admitted
        result = await observe(session, current, scope, signed, row, active, sources)
        admitted = result.value.metrics[0].baseline is not None
        return result

    monkeypatch.setattr(owner_view_store, "observe_goal", admitted_goal)

    async def delayed(session: AsyncSession, current: CompanyControl) -> CompanyBudget:
        assert admitted, "Baseline must be admitted before the deliberate expiry delay"
        await session.execute(select(func.pg_sleep(1.4)))
        return await budget(session, current)

    monkeypatch.setattr(owner_view_store, "company_budget", delayed)
    hidden = await views.company(control(), identity(OWNER))
    assert hidden.goals[0].metrics[0].baseline is None
    assert "PRIVATE_BASELINE_SOURCE" not in hidden.model_dump_json()

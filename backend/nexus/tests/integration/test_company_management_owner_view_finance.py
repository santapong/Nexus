"""Real once-per-action financial totals and private-proof redaction preserve issued history."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.brain.access_models import BrainResource
from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.management.owner_view_sources import OwnerViewSources
from nexus.company.management.owner_view_store import ManagementOwnerViews
from nexus.tests.integration.management_acceptance_fixture import (
    configured_acceptance,
    issue_accepted_report_fixture,
)
from nexus.tests.integration.test_company_brain_ingestion import owner_scope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_management_acceptance import saved_m1
from nexus.tests.management_views_support import ViewsDatabase
from nexus.tests.management_views_support import views_database as views_database


async def test_actual_bill_is_counted_once_with_per_task_parent_ledger_and_private_proof_redacted(
    views_database: ViewsDatabase,
    tmp_path: Path,
) -> None:
    scenario, acceptance = await issue_accepted_report_fixture(views_database.app, tmp_path)
    views = ManagementOwnerViews(
        views_database.app, OwnerViewSources(scenario.artifacts, scenario.freshness)
    )
    before = await saved_m1(views_database.app)
    company = await views.company(control(), identity(OWNER))
    assert company.budget.known_spent_usd == company.budget.daily.spent_usd == Decimal("0.025000")
    assert company.budget.actual_total_usd == Decimal("0.025000")
    assert company.budget.root_lifetime_allocated_usd == Decimal(1)
    author = await views.work(control(), identity(OWNER), acceptance.target.author.task_id)
    parent = await views.work(
        control(), identity(OWNER), scenario.payload.procedure.binding.task_id
    )
    assert author.execution_state == "verifying"
    assert author.independent_acceptance.current_confirmed
    assert author.independent_acceptance.authorized_proofs
    assert parent.lifetime.own_ledger_spent_usd == 0
    assert author.lifetime.own_ledger_spent_usd == Decimal("0.025000")
    assert parent.lifetime.own_known_spent_usd == 0
    assert await saved_m1(views_database.app) == before
    async with views_database.admin() as session:
        artifact = await session.get(
            BrainArtifactRevision, (COMPANY, scenario.protected_result.artifact_revision_id)
        )
        assert artifact is not None
        resource = await session.get(BrainResource, (COMPANY, artifact.resource_id))
        assert resource is not None
    await ResourceAccessStore(views_database.app).change(
        owner_scope(),
        identity(OWNER),
        ResourceAccessChange(
            company_id=COMPANY,
            resource=ResourceRef(company_id=COMPANY, resource_id=resource.resource_id),
            principal_id=OWNER,
            active=False,
            expected_generation=resource.acl_generation,
        ),
    )
    after = await saved_m1(views_database.app)
    hidden = await views.work(control(), identity(OWNER), acceptance.target.author.task_id)
    assert hidden.independent_acceptance.historical_verdict == "pass"
    assert not hidden.independent_acceptance.current_confirmed
    assert hidden.independent_acceptance.authorized_proofs is None
    assert str(scenario.protected_result.artifact_revision_id) not in hidden.model_dump_json()
    assert hidden.lifetime.own_actual_total_usd == Decimal("0.025000")
    assert await saved_m1(views_database.app) == after


async def test_unknown_issued_bill_stays_null_while_native_hold_and_known_receipt_remain_visible(
    views_database: ViewsDatabase,
    tmp_path: Path,
) -> None:
    scenario = await configured_acceptance(views_database.app, tmp_path, actual_usd=None)
    views = ManagementOwnerViews(
        views_database.app, OwnerViewSources(scenario.artifacts, scenario.freshness)
    )
    before = await saved_m1(views_database.app)
    company = await views.company(control(), identity(OWNER))
    assert company.budget.billing_unconfirmed and company.budget.actual_total_usd is None
    assert (
        company.budget.reserved_any_day_usd == company.budget.daily.held_usd == Decimal("0.030000")
    )
    assert company.budget.known_spent_usd == 0
    author = await views.work(
        control(), identity(OWNER), scenario.payload.children[0].binding.task_id
    )
    assert author.execution_state == "verifying"
    assert author.lifetime.own_billing_unconfirmed and author.lifetime.own_actual_total_usd is None
    assert author.receipts[0].state == "succeeded" and author.receipts[0].billing == "unconfirmed"
    assert author.receipts[0].known_cost_usd is None
    assert author.independent_acceptance.acceptance_id is None
    assert await saved_m1(views_database.app) == before

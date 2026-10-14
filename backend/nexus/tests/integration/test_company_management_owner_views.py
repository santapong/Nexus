"""Actual signed-owner native views show decisions without changing M1 or exposing tool inputs."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.actions import ActionProposal
from nexus.company.directory_contracts import MembershipChange
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management.owner_view_contracts import OwnerViewPage
from nexus.company.management.plans import PlanPayload
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import CompanyControl
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_management_acceptance import saved_m1
from nexus.tests.management_views_support import ViewsDatabase, configured_views
from nexus.tests.management_views_support import views_database as views_database


async def test_owner_views_remain_available_paused_and_deny_signed_scope_splices(
    views_database: ViewsDatabase,
    tmp_path: Path,
) -> None:
    views, _, _, payload, _ = await configured_views(views_database, tmp_path)
    before = await saved_m1(views_database.app)
    async with views_database.app() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        row = await session.get(CompanyControl, COMPANY)
        assert row is not None
        row.paused = True
    company = await views.company(control(), identity(OWNER))
    assert company.paused and company.budget.daily.cap_usd == Decimal(5)
    assert company.budget.root_lifetime_allocated_usd == Decimal(1)
    assert len((await views.plan(control(), identity(OWNER), payload.plan.plan_id)).work) == 2
    assert (
        await views.work(control(), identity(OWNER), payload.children[0].binding.task_id)
    ).cancellation is None
    assert await saved_m1(views_database.app) == before
    for signed in (identity(ACTOR), VerifiedIdentity(principal_id=OWNER, workspace_id=uuid4())):
        with pytest.raises(ValueError):
            await views.company(control(), signed)


async def test_pending_revision_can_be_inspected_without_replacing_operative_head(
    views_database: ViewsDatabase,
    tmp_path: Path,
) -> None:
    views, _, store, payload, _ = await configured_views(views_database, tmp_path)
    proposal = PlanPayload.model_validate_json(
        payload.model_copy(
            update={
                "plan": payload.plan.model_copy(update={"revision": 2}),
            }
        ).model_dump_json()
    )
    current = (await views.company(control(), identity(OWNER))).plans[0].reference
    second = await store.propose(
        control(), identity(OWNER), proposal, expected_current_revision_id=current.plan_revision_id
    )
    page = await views.approvals(control(), identity(OWNER))
    assert tuple(row.plan_revision_id for row in page.pending_plans) == (second.plan_revision_id,)
    candidate = await views.plan(
        control(), identity(OWNER), payload.plan.plan_id, revision_id=second.plan_revision_id
    )
    assert candidate.state == "proposed" and not candidate.is_current_head and candidate.work == ()
    assert (await views.plan(control(), identity(OWNER), payload.plan.plan_id)).reference == current


async def test_action_audit_retains_exact_hash_and_omits_source_bearing_parameters(
    views_database: ViewsDatabase,
    tmp_path: Path,
) -> None:
    views, _, _, payload, _ = await configured_views(views_database, tmp_path)
    author = payload.children[0].binding
    proposal = ActionProposal(
        company_id=COMPANY,
        action_id=uuid4(),
        task_id=author.task_id,
        trace_id=author.trace_id,
        actor_id=ACTOR,
        revision=1,
        tool="fake.internal.read.v1",
        tool_version="v1",
        resource="company.report",
        parameters={"private": "PRIVATE_SOURCE_PAYLOAD"},
        policy_version="fixture-policy",
        price_version="fixture-prices",
        estimated_cost_usd=Decimal("0.03"),
    )
    scope = LedgerScope(
        company_id=COMPANY, principal_id=ACTOR, task_id=author.task_id, trace_id=author.trace_id
    )
    journal = CompanyJournal(views_database.app)
    submitted = await journal.submit(proposal, scope)
    await journal.approve_registered(
        scope.model_copy(update={"principal_id": OWNER}),
        proposal.action_id,
        submitted.proposal_hash,
        datetime.now(UTC),
        identity=identity(OWNER),
    )
    before = await saved_m1(views_database.app)
    page = await views.approvals(control(), identity(OWNER), page=OwnerViewPage(limit=1))
    assert page.approvals[0].proposal_sha256 == submitted.proposal_hash
    assert page.approvals[0].owner_decision is not None
    assert page.approvals[0].authority_observation == "exact_recorded"
    assert "PRIVATE_SOURCE_PAYLOAD" not in page.model_dump_json()
    assert await saved_m1(views_database.app) == before


async def test_cached_signed_owner_cannot_read_after_actual_membership_revocation(
    views_database: ViewsDatabase,
    tmp_path: Path,
) -> None:
    views, _, _, _, _ = await configured_views(views_database, tmp_path)
    signed = identity(OWNER)
    assert (await views.company(control(), signed)).owner_id == OWNER
    await PersistentCompanyDirectory(views_database.app).set_membership(
        MembershipChange(
            company_id=COMPANY, principal_id=OWNER, role="owner", membership_active=False
        ),
        control(),
    )
    with pytest.raises(ValueError):
        await views.today(control(), signed)

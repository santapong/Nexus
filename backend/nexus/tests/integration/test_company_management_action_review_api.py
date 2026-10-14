"""Real complete owner READ gates exact review before M1 decision, with no enqueue."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from litestar.testing import AsyncTestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.brain.access_models import BrainResource
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.control_support import db_clock
from nexus.company.management.plans import RunBinding
from nexus.execution.dispatch_models import SegmentDispatch
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import CompanyControl
from nexus.tests.integration.test_company_api import headers
from nexus.tests.integration.test_company_brain_ingestion import RESOURCE, owner_scope
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.management_views_api_support import configured_api
from nexus.tests.management_views_api_support import views_api_database as views_api_database
from nexus.tests.management_views_support import ViewsDatabase

BASE = f"/api/v2/companies/{COMPANY}/management"


async def pending(database: ViewsDatabase, bound: RunBinding) -> ActionProposal:
    proposal = ActionProposal(
        company_id=COMPANY,
        action_id=uuid4(),
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        actor_id=bound.actor_id,
        revision=1,
        tool="fake.internal.read.v1",
        tool_version="v1",
        resource="company.report",
        parameters={"operation": "read", "note": "PRIVATE_EXACT_ACTION_ARGUMENT"},
        policy_version="fixture-policy",
        price_version="fixture-prices",
        estimated_cost_usd=Decimal("0.03"),
    )
    await CompanyJournal(database.app).submit(
        proposal,
        LedgerScope(
            company_id=COMPANY, principal_id=ACTOR, task_id=bound.task_id, trace_id=bound.trace_id
        ),
    )
    return proposal


async def test_actual_native_review_then_exact_m1_decision_without_dispatch(
    views_api_database: ViewsDatabase,
    tmp_path: Path,
) -> None:
    app, payload, _ = await configured_api(views_api_database, tmp_path)
    action = await pending(views_api_database, payload.children[0].binding)
    async with AsyncTestClient(app) as client:
        review = await client.get(
            BASE + f"/actions/{action.action_id}/review", headers=headers(OWNER)
        )
        assert review.status_code == 200 and review.json()["availability"] == "available", (
            review.text
        )
        detail = review.json()["detail"]
        assert detail["trace_id"] == str(action.trace_id)
        assert detail["proposal"]["parameters"]["note"] == "PRIVATE_EXACT_ACTION_ARGUMENT"
        decided = await client.post(
            f"/api/v2/companies/{COMPANY}/work/{action.task_id}/actions/{action.action_id}/decision",
            headers=headers(OWNER),
            json={
                "trace_id": detail["trace_id"],
                "expected_hash": detail["proposal_sha256"],
                "approved": True,
            },
        )
        assert decided.status_code == 200 and decided.json()["status"] == "decision_saved"
        assert (
            await client.get(BASE + f"/actions/{action.action_id}/review", headers=headers(ACTOR))
        ).status_code == 403
    async with views_api_database.admin() as session:
        assert await session.scalar(select(func.count()).select_from(SegmentDispatch)) == 0


async def test_revoked_owner_source_read_hides_exact_parameters_but_keeps_native_audit(
    views_api_database: ViewsDatabase,
    tmp_path: Path,
) -> None:
    app, payload, _ = await configured_api(views_api_database, tmp_path)
    action = await pending(views_api_database, payload.children[0].binding)
    async with views_api_database.admin() as session:
        resource = await session.get(BrainResource, (COMPANY, RESOURCE))
        assert resource is not None
    await ResourceAccessStore(views_api_database.app).change(
        owner_scope(),
        identity(OWNER),
        ResourceAccessChange(
            company_id=COMPANY,
            resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
            principal_id=OWNER,
            active=False,
            expected_generation=resource.acl_generation,
        ),
    )
    async with AsyncTestClient(app) as client:
        response = await client.get(
            BASE + f"/actions/{action.action_id}/review", headers=headers(OWNER)
        )
        assert response.status_code == 200 and response.json()["availability"] == "unavailable"
        assert response.json()["detail"] is None
        assert response.json()["audit"]["action_id"] == str(action.action_id)
        assert "PRIVATE_EXACT_ACTION_ARGUMENT" not in response.text


async def test_source_expiry_after_real_review_reads_omits_parameters_at_final_boundary(
    views_api_database: ViewsDatabase,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.company.management import action_review_store

    app, payload, _ = await configured_api(views_api_database, tmp_path)
    action = await pending(views_api_database, payload.children[0].binding)
    async with views_api_database.admin() as session:
        resource = await session.get(BrainResource, (COMPANY, RESOURCE))
        assert resource is not None
        now = await db_clock(session)
    await ResourceAccessStore(views_api_database.app).change(
        owner_scope(),
        identity(OWNER),
        ResourceAccessChange(
            company_id=COMPANY,
            resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
            principal_id=OWNER,
            active=True,
            expected_generation=resource.acl_generation,
            expires_at=now + timedelta(seconds=1.2),
        ),
    )
    admitted = False

    async def delayed(session: AsyncSession, current: CompanyControl, work: ExecutionWork) -> None:
        nonlocal admitted
        admitted = True
        await session.execute(select(func.pg_sleep(1.4)))

    monkeypatch.setattr(action_review_store, "_final_review_reads", delayed)
    async with AsyncTestClient(app) as client:
        response = await client.get(
            BASE + f"/actions/{action.action_id}/review", headers=headers(OWNER)
        )
        assert admitted and response.status_code == 200
        assert (
            response.json()["availability"] == "unavailable" and response.json()["detail"] is None
        )
        assert "PRIVATE_EXACT_ACTION_ARGUMENT" not in response.text

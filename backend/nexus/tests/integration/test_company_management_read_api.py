"""Actual signed owner GET/commitment HTTP; no intake or schema shortcuts."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import uuid4

from litestar.testing import AsyncTestClient
from sqlalchemy import func, select

from nexus.company.directory_contracts import MembershipChange
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.harness.journal_models import CompanyControl
from nexus.tests.integration.test_company_api import headers
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER, control
from nexus.tests.integration.test_company_management_acceptance import saved_m1
from nexus.tests.management_views_api_support import configured_api
from nexus.tests.management_views_api_support import views_api_database as views_api_database
from nexus.tests.management_views_support import ViewsDatabase

BASE = f"/api/v2/companies/{COMPANY}/management"


async def test_optional_reads_are_owner_only_paused_safe_and_use_actual_source_shapes(
    views_api_database: ViewsDatabase,
    tmp_path: Path,
) -> None:
    app, payload, _ = await configured_api(views_api_database, tmp_path)
    before = await saved_m1(views_api_database.app)
    async with AsyncTestClient(app) as client:
        for path in (
            "/company",
            "/today",
            "/approvals",
            f"/plans/{payload.plan.plan_id}",
            f"/work/{payload.children[0].binding.task_id}",
        ):
            owner = await client.get(BASE + path, headers=headers(OWNER))
            assert owner.status_code == 200, owner.text
            assert (await client.get(BASE + path, headers=headers(ACTOR))).status_code == 403
            assert (await client.get(BASE + path)).status_code == 401
        async with views_api_database.app() as session, session.begin():
            await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
            native = await session.get(CompanyControl, COMPANY)
            assert native is not None
            native.paused = True
        owner = await client.get(BASE + "/company", headers=headers(OWNER))
        assert owner.status_code == 200 and owner.json()["paused"] is True
        assert owner.json()["budget"]["actual_total_usd"] == "0"
        schema = await client.get("/schema/openapi.json")
        assert schema.status_code == 200
        await asyncio.to_thread(
            (tmp_path / "company-openapi.json").write_text, json.dumps(schema.json(), indent=2)
        )
    assert await saved_m1(views_api_database.app) == before


async def test_optional_service_absence_and_cached_signed_owner_revocation_deny(
    views_api_database: ViewsDatabase,
    tmp_path: Path,
) -> None:
    app, _, _ = await configured_api(views_api_database, tmp_path, read_enabled=False)
    async with AsyncTestClient(app) as client:
        assert (await client.get(BASE + "/company", headers=headers(OWNER))).status_code == 503
        assert (await client.get(BASE + "/company", headers=headers(ACTOR))).status_code == 403
        await PersistentCompanyDirectory(views_api_database.app).set_membership(
            MembershipChange(
                company_id=COMPANY, principal_id=OWNER, role="owner", membership_active=False
            ),
            control(),
        )
        assert (await client.get(BASE + "/company", headers=headers(OWNER))).status_code == 403


async def test_commitment_http_cas_immutability_history_and_literal_dates(
    views_api_database: ViewsDatabase,
    tmp_path: Path,
) -> None:
    app, _, definition = await configured_api(views_api_database, tmp_path)
    body = {
        "definition": definition.model_dump(mode="json"),
        "version": "v1",
        "expected_revision_id": None,
    }
    before = await saved_m1(views_api_database.app)
    async with AsyncTestClient(app) as client:
        first = await client.post(BASE + "/commitments", headers=headers(OWNER), json=body)
        assert first.status_code == 200, first.text
        assert (
            await client.post(BASE + "/commitments", headers=headers(OWNER), json=body)
        ).json() == first.json()
        changed = {**body, "version": "v2"}
        conflict = await client.post(BASE + "/commitments", headers=headers(OWNER), json=changed)
        assert conflict.status_code == 409
        current = await client.get(
            BASE + f"/commitments/{definition.commitment_id}", headers=headers(OWNER)
        )
        assert current.status_code == 200 and current.json() == first.json()
        history = await client.get(
            BASE + f"/commitments/{definition.commitment_id}/history", headers=headers(OWNER)
        )
        assert history.status_code == 200 and history.json() == [first.json()]
        malformed_definition = definition.model_dump(mode="json")
        malformed_definition["due"] = {
            **definition.due.model_dump(mode="json"),
            "actionable_at": "2026-10-14T00:00:00Z",
        }
        malformed = {**body, "definition": malformed_definition}
        assert (
            await client.post(BASE + "/commitments", headers=headers(OWNER), json=malformed)
        ).status_code == 422
        assert (
            await client.post(BASE + "/commitments", headers=headers(ACTOR), json=body)
        ).status_code == 403
        assert (
            await client.get(BASE + f"/commitments/{uuid4()}", headers=headers(OWNER))
        ).status_code == 403
    assert await saved_m1(views_api_database.app) == before

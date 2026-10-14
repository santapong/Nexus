"""Actual signed owner report selectors and pending preparation create no execution authority."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from litestar.testing import AsyncTestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.directory_contracts import MembershipChange
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.execution.dispatch_models import SegmentDispatch
from nexus.harness.journal_models import JournalAction
from nexus.tests.integration.test_company_api import headers
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER, control
from nexus.tests.integration.test_company_management_acceptance import saved_m1
from nexus.tests.native_report_api_support import configured_report_api
from nexus.tests.native_report_api_support import report_api_factory as report_api_factory

BASE = f"/api/v2/companies/{COMPANY}/management/reports"


async def test_owner_report_profile_and_exact_pending_author_leave_issued_facts_unchanged(
    report_api_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    app, case = await configured_report_api(report_api_factory, tmp_path)
    before = await saved_m1(report_api_factory)
    request = {
        "report_id": str(case.report_id),
        "commitment_id": str(case.commitment_id),
        "evidence_ids": [str(value) for value in case.evidence_ids],
    }
    async with AsyncTestClient(app) as client:
        saved = await client.get(BASE + f"/{case.report_id}", headers=headers(OWNER))
        assert saved.status_code == 200, saved.text
        profile = await client.post(BASE + "/profiles", json=request, headers=headers(OWNER))
        assert profile.status_code == 200, profile.text
        body = {"reference": profile.json()["reference"]}
        pending = await client.post(
            BASE + "/profiles/prepare-author", json=body, headers=headers(OWNER)
        )
        assert pending.status_code == 200, pending.text
        record = pending.json()
        assert record["action"]["state"] == "awaiting_approval"
        assert record["scheduled"] is False and record["executed"] is False
        assert record["model_requests"] == 0 and record["exact_approval_required"] is True
        assert (
            await client.post(BASE + "/profiles/prepare-author", json=body, headers=headers(OWNER))
        ).json() == record
        tampered = {"reference": profile.json()["reference"] | {"report_sha256": "f" * 64}}
        assert (
            await client.post(
                BASE + "/profiles/prepare-author", json=tampered, headers=headers(OWNER)
            )
        ).status_code == 403
        assert (await client.get(BASE + f"/{uuid4()}", headers=headers(OWNER))).status_code == 404
    assert await saved_m1(report_api_factory) == before
    async with report_api_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.scalar(select(func.count()).select_from(JournalAction)) == 1
        assert await session.scalar(select(func.count()).select_from(SegmentDispatch)) == 0


@pytest.mark.parametrize("failure", ["member", "foreign", "inactive", "signature", "disabled"])
async def test_report_profile_current_signed_owner_and_configuration_required(
    report_api_factory: async_sessionmaker[AsyncSession], tmp_path: Path, failure: str
) -> None:
    app, case = await configured_report_api(
        report_api_factory, tmp_path, enabled=failure != "disabled"
    )
    path, auth, expected = BASE, headers(OWNER), 403
    if failure == "member":
        auth = headers(ACTOR)
    elif failure == "foreign":
        path = path.replace(str(COMPANY), str(uuid4()))
    elif failure == "inactive":
        await PersistentCompanyDirectory(report_api_factory).set_membership(
            MembershipChange(
                company_id=COMPANY, principal_id=OWNER, role="owner", membership_active=False
            ),
            control(),
        )
    elif failure == "signature":
        auth, expected = (
            headers(OWNER, key="unrelated-key-with-at-least-thirty-two-characters"),
            401,
        )
    else:
        expected = 503
    before = await saved_m1(report_api_factory)
    async with AsyncTestClient(app) as client:
        response = await client.post(
            path + "/profiles",
            json={
                "report_id": str(case.report_id),
                "commitment_id": str(case.commitment_id),
                "evidence_ids": [str(value) for value in case.evidence_ids],
            },
            headers=auth,
        )
        assert response.status_code == expected, response.text
        assert (await client.get(path + f"/{case.report_id}", headers=auth)).status_code == expected
    assert await saved_m1(report_api_factory) == before


async def test_owner_explicit_new_snapshot_and_strict_selection_period_have_no_dispatch(
    report_api_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    app, case = await configured_report_api(report_api_factory, tmp_path)
    before = await saved_m1(report_api_factory)
    async with AsyncTestClient(app) as client:
        saved = (await client.get(BASE + f"/{case.report_id}", headers=headers(OWNER))).json()
        now = datetime.now(UTC)
        body = {
            "plan_revision_id": saved["selection"]["plan"]["plan_revision_id"],
            "author_task_id": saved["selection"]["author"]["task_id"],
            "selected_task_ids": [],
            "period_start": (now - timedelta(days=1)).isoformat(),
            "period_end": now.isoformat(),
        }
        response = await client.post(BASE, json=body, headers=headers(OWNER))
        assert response.status_code == 200, response.text
        assert response.json()["report_id"] != str(case.report_id)
        assert response.json()["created_by"] == str(OWNER)
        for altered in (
            body | {"period_end": body["period_start"]},
            body | {"owner": True},
            body | {"period_start": "2026-10-14"},
            body | {"selected_task_ids": [str(uuid4())]},
        ):
            denied = await client.post(BASE, json=altered, headers=headers(OWNER))
            assert denied.status_code in {403, 422}, denied.text
    assert await saved_m1(report_api_factory) == before

"""Actual owner metric HTTP cannot supply results or create work/effect authority."""

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest
from litestar.testing import AsyncTestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.directory_contracts import MembershipChange
from nexus.tests.integration.test_company_api import headers
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER, control
from nexus.tests.integration.test_company_management_acceptance import saved_m1
from nexus.tests.metric_api_support import configured_metric_api
from nexus.tests.metric_api_support import metric_api_factory as metric_api_factory
from nexus.tests.metric_fixture import MetricScenario, accept_report

BASE = f"/api/v2/companies/{COMPANY}/management/metrics/observations"


def observation_body(case: MetricScenario) -> dict[str, object]:
    return {
        "request": case.request.model_dump(mode="json"),
        "operation_id": str(uuid4()),
        "audit_trace_id": str(uuid4()),
    }


async def test_owner_native_observation_current_recorded_replay_preserves_all_issued_facts(
    metric_api_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    app, case = await configured_metric_api(metric_api_factory, tmp_path)
    accepted = await accept_report(metric_api_factory, case)
    before = await saved_m1(metric_api_factory)
    body = observation_body(case)
    async with AsyncTestClient(app) as client:
        paused = await client.post(
            f"/api/v2/companies/{COMPANY}/pause", json={"paused": True}, headers=headers(OWNER)
        )
        assert paused.status_code == 200
        response = await client.post(BASE, json=body, headers=headers(OWNER))
        assert response.status_code == 200, response.text
        record = response.json()
        assert record["snapshot"]["comparison"]["value"] == {
            "kind": "known",
            "unit": "count",
            "value": 1,
        }
        assert record["snapshot"]["comparison"]["baseline"]["kind"] == "unknown"
        assert record["snapshot"]["work"][0]["acceptance_id"] == str(accepted.acceptance_id)
        assert (await client.post(BASE, json=body, headers=headers(OWNER))).json() == record
        path = BASE + f"/{case.request.observation_id}"
        assert (await client.get(path + "/recorded", headers=headers(OWNER))).json() == record
        current = await client.get(path + "/current", headers=headers(OWNER))
        assert current.status_code == 200, current.text
        assert current.json()["comparison_result"] == "satisfied"
        assert current.json()["baseline_change"] is None
        assert current.json()["recorded_at"] == record["observed_at"]
        page = await client.get(
            BASE + f"?goal_id={case.request.goal.goal_id}", headers=headers(OWNER)
        )
        assert page.status_code == 200, page.text
        assert len(page.json()["observations"]) == 1
        assert page.json()["observations"][0]["comparison_result"] == "satisfied"
        assert page.json()["next_after_id"] is None
        plan = await client.get(
            f"/api/v2/companies/{COMPANY}/management/plans/{case.request.plan.plan_id}",
            headers=headers(OWNER),
        )
        company = await client.get(
            f"/api/v2/companies/{COMPANY}/management/company", headers=headers(OWNER)
        )
        assert plan.status_code == company.status_code == 200
        goal = next(
            item
            for item in company.json()["goals"]
            if item["reference"]["revision_id"] == str(case.request.goal.revision_id)
        )
        await asyncio.to_thread(
            (tmp_path / "metric-owner-ui-fixture.json").write_text,
            json.dumps(
                {
                    "scope": "synthetic restricted-PG HTTP only",
                    "recorded": record,
                    "current": current.json(),
                    "page": page.json(),
                    "plan": plan.json(),
                    "goal": goal,
                    "request": body,
                },
                indent=2,
            ),
        )
        assert (
            await client.get(BASE + f"/{uuid4()}/current", headers=headers(OWNER))
        ).status_code == 404
        assert (
            await client.post(path + "/complete", json={}, headers=headers(OWNER))
        ).status_code == 404
    assert await saved_m1(metric_api_factory) == before


@pytest.mark.parametrize("failure", ["member", "foreign", "inactive", "signature", "disabled"])
async def test_metric_http_requires_current_signed_owner_and_explicit_configuration(
    metric_api_factory: async_sessionmaker[AsyncSession], tmp_path: Path, failure: str
) -> None:
    app, case = await configured_metric_api(
        metric_api_factory, tmp_path, enabled=failure != "disabled"
    )
    auth = headers(OWNER)
    path = BASE
    expected = 403
    if failure == "member":
        auth = headers(ACTOR)
    elif failure == "foreign":
        path = path.replace(str(COMPANY), str(uuid4()))
    elif failure == "inactive":
        from nexus.company.directory_store import PersistentCompanyDirectory

        await PersistentCompanyDirectory(metric_api_factory).set_membership(
            MembershipChange(
                company_id=COMPANY, principal_id=OWNER, role="owner", membership_active=False
            ),
            control(),
        )
    elif failure == "signature":
        auth, expected = headers(OWNER, key="other-key-with-at-least-thirty-two-characters"), 401
    else:
        expected = 503
    before = await saved_m1(metric_api_factory)
    async with AsyncTestClient(app) as client:
        response = await client.post(path, json=observation_body(case), headers=auth)
        assert response.status_code == expected, response.text
        for endpoint in ("current", "recorded"):
            assert (
                await client.get(path + f"/{case.request.observation_id}/{endpoint}", headers=auth)
            ).status_code == expected
    assert await saved_m1(metric_api_factory) == before


@pytest.mark.parametrize("failure", ["value", "verdict", "owner", "company", "goal", "task"])
async def test_metric_wire_denies_invented_results_authority_or_native_scope(
    metric_api_factory: async_sessionmaker[AsyncSession], tmp_path: Path, failure: str
) -> None:
    app, case = await configured_metric_api(metric_api_factory, tmp_path)
    body = observation_body(case)
    request = case.request.model_dump(mode="json")
    expected = 422
    if failure in {"value", "verdict", "owner"}:
        request[failure] = 1 if failure == "value" else "pass" if failure == "verdict" else True
    elif failure == "company":
        request["company_id"] = str(uuid4())
    elif failure == "goal":
        request["goal"]["sha256"] = "f" * 64
        expected = 409
    else:
        request["task_ids"] = [str(uuid4())]
        expected = 409
    body["request"] = request
    before = await saved_m1(metric_api_factory)
    async with AsyncTestClient(app) as client:
        response = await client.post(BASE, json=body, headers=headers(OWNER))
        assert response.status_code == expected, response.text
    assert await saved_m1(metric_api_factory) == before

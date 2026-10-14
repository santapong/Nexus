"""Actual current-owner cancellation HTTP preserves M1 history and company pause semantics."""

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest
from litestar.testing import AsyncTestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.api.company_management_control_routes import WorkCancellationIntent
from nexus.company.directory_contracts import MembershipChange
from nexus.company.management.cancellation_contracts import CancellationCommand
from nexus.company.management.cancellation_models import WorkCancellation
from nexus.company.management.cancellation_support import cancellation_for_work
from nexus.company.management.plans import RunBinding
from nexus.tests.integration.test_company_api import headers
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER, control
from nexus.tests.integration.test_company_management_acceptance import saved_m1
from nexus.tests.management_control_api_support import configured_control_api
from nexus.tests.management_control_api_support import control_api_factory as control_api_factory

BASE = f"/api/v2/companies/{COMPANY}/management/control"


def intent(target: RunBinding) -> WorkCancellationIntent:
    return WorkCancellationIntent(
        intent="cancel_work_permanently",
        command=CancellationCommand(
            company_id=target.company_id, target=target, reason="Owner permanently stops this work"
        ),
        operation_id=uuid4(),
        audit_trace_id=uuid4(),
    )


async def test_signed_owner_exact_stop_replay_while_paused_and_resume_keeps_stop(
    control_api_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    scenario = await configured_control_api(control_api_factory, tmp_path)
    target = scenario.payload.procedure.binding
    command = intent(target)
    before = await saved_m1(control_api_factory)
    async with AsyncTestClient(scenario.app) as client:
        descriptor = await client.get(BASE, headers=headers(OWNER))
        assert descriptor.status_code == 200, descriptor.text
        values = descriptor.json()
        assert values["cancellation_is_permanent"] and values["resume_preserves_cancellation"]
        paused = await client.post(
            values["pause_endpoint"], json=values["pause_body"], headers=headers(OWNER)
        )
        assert paused.status_code == 200 and paused.json()["paused"] is True
        path = BASE + f"/work/{target.task_id}/cancel"
        response = await client.post(
            path, json=command.model_dump(mode="json"), headers=headers(OWNER)
        )
        assert response.status_code == 200, response.text
        assert response.json()["target"] == target.model_dump(mode="json")
        assert response.json()["registration_sha256"] and response.json()["owner_id"] == str(OWNER)
        assert (
            await client.post(path, json=command.model_dump(mode="json"), headers=headers(OWNER))
        ).json() == response.json()
        changed = command.model_copy(
            update={"command": command.command.model_copy(update={"reason": "Other reason"})}
        )
        assert (
            await client.post(path, json=changed.model_dump(mode="json"), headers=headers(OWNER))
        ).status_code == 409
        resumed = await client.post(
            values["pause_endpoint"], json=values["resume_body"], headers=headers(OWNER)
        )
        assert resumed.status_code == 200 and resumed.json()["paused"] is False
        assert (
            await client.post(path + "/uncancel", headers=headers(OWNER), json={})
        ).status_code == 404
        schema = await client.get("/schema/openapi.json")
        assert schema.status_code == 200
        await asyncio.to_thread(
            (tmp_path / "control-api-openapi.json").write_text, json.dumps(schema.json(), indent=2)
        )
    assert await saved_m1(control_api_factory) == before
    async with control_api_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        for child in scenario.payload.children:
            cancelled = await cancellation_for_work(session, COMPANY, child.binding.task_id)
            assert cancelled is not None and cancelled.inherited
            assert cancelled.cancellation.target == target
        assert await session.scalar(select(func.count()).select_from(WorkCancellation)) == 1


@pytest.mark.parametrize(
    "failure", ["missing", "signature", "member", "workspace", "foreign", "inactive"]
)
async def test_cancellation_requires_current_signed_owner_and_same_company(
    control_api_factory: async_sessionmaker[AsyncSession], tmp_path: Path, failure: str
) -> None:
    scenario = await configured_control_api(control_api_factory, tmp_path)
    target = scenario.payload.children[0].binding
    path = BASE + f"/work/{target.task_id}/cancel"
    expected = 403
    auth = headers(OWNER)
    if failure == "missing":
        auth, expected = {}, 401
    elif failure == "signature":
        auth, expected = headers(OWNER, key="other-fixture-key-with-at-least32-bytes"), 401
    elif failure == "member":
        auth = headers(ACTOR)
    elif failure == "workspace":
        auth = headers(OWNER, workspace=uuid4())
    elif failure == "foreign":
        path = path.replace(str(COMPANY), str(uuid4()))
    else:
        await scenario.directory.set_membership(
            MembershipChange(
                company_id=COMPANY, principal_id=OWNER, role="owner", membership_active=False
            ),
            control(),
        )
    before = await saved_m1(control_api_factory)
    async with AsyncTestClient(scenario.app) as client:
        response = await client.post(
            path, headers=auth, json=intent(target).model_dump(mode="json")
        )
        assert response.status_code == expected, response.text
        assert (await client.get(path.split("/work", 1)[0], headers=auth)).status_code == expected
    assert await saved_m1(control_api_factory) == before
    async with control_api_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.scalar(select(func.count()).select_from(WorkCancellation)) == 0


@pytest.mark.parametrize("field", ["task_id", "trace_id", "run_id", "actor_id", "model_profile"])
async def test_exact_native_target_mismatch_cannot_cancel_or_reset_work(
    control_api_factory: async_sessionmaker[AsyncSession], tmp_path: Path, field: str
) -> None:
    scenario = await configured_control_api(control_api_factory, tmp_path)
    target = scenario.payload.children[0].binding
    altered = target.model_copy(
        update={field: "unknown-profile" if field == "model_profile" else uuid4()}
    )
    before = await saved_m1(control_api_factory)
    async with AsyncTestClient(scenario.app) as client:
        response = await client.post(
            BASE + f"/work/{target.task_id}/cancel",
            headers=headers(OWNER),
            json=intent(altered).model_dump(mode="json"),
        )
        assert response.status_code == 403, response.text
    assert await saved_m1(control_api_factory) == before


async def test_optional_missing_service_and_literal_wire_validation_fail_closed(
    control_api_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    scenario = await configured_control_api(control_api_factory, tmp_path, enabled=False)
    target = scenario.payload.children[0].binding
    body = intent(target).model_dump(mode="json")
    path = BASE + f"/work/{target.task_id}/cancel"
    async with AsyncTestClient(scenario.app) as client:
        assert (await client.get(BASE, headers=headers(OWNER))).status_code == 503
        assert (await client.get(BASE, headers=headers(ACTOR))).status_code == 403
        assert (await client.post(path, json=body, headers=headers(OWNER))).status_code == 503
        for invalid in (True, "pause", "resume", "uncancel"):
            assert (
                await client.post(path, json={**body, "intent": invalid}, headers=headers(OWNER))
            ).status_code == 422
        assert (
            await client.post(path, json={**body, "actor_id": str(OWNER)}, headers=headers(OWNER))
        ).status_code == 422

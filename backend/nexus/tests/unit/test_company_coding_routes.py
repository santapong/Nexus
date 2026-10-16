"""Actual C owner controller schemas; absent C service preserves original profile.

Cohesion exception: the genuine signed bearer, real controller and final slow
serializer stay adjacent in the two full HTTP cutoff sequences.
"""

from pathlib import Path

import pytest

from nexus.execution.coding_application import coding_app
from nexus.tests.unit.coding_application_fixture import application
from nexus.tests.unit.test_planning_application import TEST_SIGNER


def test_coding_routes_are_closed_path_and_actual_shared_services(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nexus.settings import settings

    monkeypatch.setattr(settings, "jwt_secret_key", TEST_SIGNER)
    configured = application(tmp_path)
    app = coding_app(configured)
    schema = app.openapi_schema.to_schema()
    prefix = "/api/v2/companies/{company_id}/coding"
    assert prefix + "/actions/{action_id}/input" in schema["paths"]
    assert prefix + "/actions/{action_id}/candidate" in schema["paths"]
    assert prefix + "/goals/{goal_id}/prepare" in schema["paths"]
    assert "read_end_us" not in str(schema)


@pytest.mark.parametrize(
    "field", ["actor_id", "workspace_id", "model", "allocation_usd", "queue", "repository_path"]
)
async def test_real_http_cannot_post_role_or_authority_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    from litestar.testing import AsyncTestClient

    from nexus.settings import settings
    from nexus.tests.unit.coding_application_fixture import routed_application
    from nexus.tests.unit.test_company_planning_lifecycle_routes import lifecycle_headers

    monkeypatch.setattr(settings, "jwt_secret_key", TEST_SIGNER)
    value = await routed_application(tmp_path, monkeypatch)
    path = (
        f"/api/v2/companies/{value.config.goal.company_id}/coding"
        f"/goals/{value.config.goal.goal_id}/prepare"
    )
    async with AsyncTestClient(coding_app(value)) as client:
        response = await client.post(
            path,
            headers=lifecycle_headers(value.planning),
            json={
                "goal": value.config.goal.model_dump(mode="json"),
                "expected_current_revision_id": "00000000-0000-0000-0000-000000000222",
                field: "posted-authority",
            },
        )
        assert response.status_code == 422


async def test_status_forwards_original_signed_owner_and_complete_shortened_cutoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime
    from unittest.mock import AsyncMock

    from litestar.testing import AsyncTestClient

    from nexus.builder.contained_query import clock_us
    from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
    from nexus.execution.coding_lifecycle_contracts import (
        CodingLifecycleRead,
        CodingLifecycleStatus,
    )
    from nexus.settings import settings
    from nexus.tests.unit.coding_application_fixture import routed_application
    from nexus.tests.unit.test_company_planning_lifecycle_routes import lifecycle_headers

    monkeypatch.setattr(settings, "jwt_secret_key", TEST_SIGNER)
    value = await routed_application(tmp_path, monkeypatch)
    status = CodingLifecycleStatus(
        company_id=value.config.catalog.company_id,
        goal=value.config.goal,
        current=None,
        approved_r2=False,
        observed_at=datetime.now(UTC),
        action_id=None,
        proposal_sha256=None,
        action_state=None,
        work_state=None,
        workflow_id=None,
        native_state=None,
        resources_pending=False,
    )
    delivered = AsyncMock(return_value=CodingLifecycleRead(status, clock_us() + 5_000_000))
    monkeypatch.setattr(value.lifecycle, "status", delivered)
    path = (
        f"/api/v2/companies/{value.config.goal.company_id}/coding"
        f"/goals/{value.config.goal.goal_id}/status"
    )
    async with AsyncTestClient(coding_app(value)) as client:
        assert (await client.get(path)).status_code == 401
        response = await client.get(path, headers=lifecycle_headers(value.planning))
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        assert response.json()["company_completed"] is False
        args = delivered.await_args
        assert args is not None
        scope, witness, goal = args.args
        assert (
            type(witness) is AuthenticatedWorkerIdentity
            and scope.principal_id == witness.identity.principal_id
        )
        assert goal == value.config.goal.goal_id
        assert args.kwargs["end_us"] < clock_us() + 30_000_000


async def test_final_serialization_cannot_outlive_inner_c_source_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime
    from time import sleep

    from litestar.testing import AsyncTestClient

    from nexus.builder.contained_query import clock_us
    from nexus.execution.coding_lifecycle_contracts import (
        CodingLifecycleRead,
        CodingLifecycleStatus,
    )
    from nexus.settings import settings
    from nexus.tests.unit.coding_application_fixture import routed_application
    from nexus.tests.unit.test_company_planning_lifecycle_routes import lifecycle_headers

    monkeypatch.setattr(settings, "jwt_secret_key", TEST_SIGNER)
    value = await routed_application(tmp_path, monkeypatch)
    status = CodingLifecycleStatus(
        company_id=value.config.catalog.company_id,
        goal=value.config.goal,
        current=None,
        approved_r2=False,
        observed_at=datetime.now(UTC),
        action_id=None,
        proposal_sha256=None,
        action_state=None,
        work_state=None,
        workflow_id=None,
        native_state=None,
        resources_pending=False,
    )

    async def delivered(
        *args: object, **kwargs: object
    ) -> CodingLifecycleRead[CodingLifecycleStatus]:
        return CodingLifecycleRead(status, clock_us() + 50_000)

    monkeypatch.setattr(value.lifecycle, "status", delivered)
    original = CodingLifecycleStatus.model_dump_json

    def slow(self: CodingLifecycleStatus, *args: object, **kwargs: object) -> str:
        sleep(0.1)
        return original(self, by_alias=True)

    monkeypatch.setattr(CodingLifecycleStatus, "model_dump_json", slow)
    path = (
        f"/api/v2/companies/{value.config.goal.company_id}/coding"
        f"/goals/{value.config.goal.goal_id}/status"
    )
    async with AsyncTestClient(coding_app(value)) as client:
        response = await client.get(path, headers=lifecycle_headers(value.planning))
        assert response.status_code == 503 and "observed_at" not in response.json()

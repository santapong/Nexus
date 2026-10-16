"""Real HTTP/JWT/body boundaries with supplied native delivery, never model activation.

The concrete application fixture, all closed route forwards and original-window
controls stay together so each case exercises the same graph; cohesive test-size exception.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from time import sleep
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import jwt
import pytest
from litestar.testing import AsyncTestClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.api import company_planning_routes as routes
from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.directory_models import DirectoryCompany, DirectoryMembership
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.lifecycle import PlanRevision, PlanRevisionRef
from nexus.company.management.planning_native_facts import clock_us
from nexus.company.management.planning_prepared_contracts import StoredPlanningRequest
from nexus.company.management.transactions import ManagementDeniedError
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.company_app import create_company_app
from nexus.execution.planning_application import PlanningApplication, compose_planning_application
from nexus.execution.planning_lifecycle_contracts import (
    PlanningLifecycleRead,
    PlanningLifecycleStatus,
)
from nexus.execution.planning_owner_reads import PlanningInputReview
from nexus.harness.journal_models import CompanyControl
from nexus.harness.lifecycle import ActionState
from nexus.settings import settings
from nexus.tests.unit.planning_application_fixture import configuration
from nexus.tests.unit.test_company_auth import TEST_KEY
from nexus.tests.unit.test_company_planning_routes import routed_case
from nexus.tests.unit.test_planning_application import (
    TEST_SIGNER,
    SuppliedCredential,
    application_settings,
)
from nexus.tests.unit.test_planning_prepared_store import Fixture


@pytest.fixture(autouse=True)
def signing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "jwt_secret_key", TEST_KEY)
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256")


def headers(f: Fixture) -> dict[str, str]:
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(f.owner.principal_id),
            "workspace_id": str(f.owner.workspace_id),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
        },
        TEST_KEY,
        algorithm="HS256",
    )
    return {"Authorization": "Bearer " + token}


async def test_input_only_configuration_exposes_no_lifecycle_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f, api, common, _ = await routed_case(tmp_path, monkeypatch)
    goal = f.prepared.binding.goal
    base = f"/api/v2/companies/{f.scope.company_id}/planning"
    async with AsyncTestClient(create_company_app(common, planning_services=api)) as client:
        path = base + f"/goals/{goal.goal_id}/status"
        assert (await client.get(path)).status_code == 401
        response = await client.get(path, headers=headers(f))
        assert response.status_code == 503
        assert response.headers["cache-control"] == "no-store"
        assert "prepared" not in response.json()
        selection = {"goal": goal.model_dump(mode="json"), "expected_current_revision_id": None}
        response = await client.post(
            base + f"/goals/{goal.goal_id}/bootstrap", headers=headers(f), json=selection
        )
        assert response.status_code == 503


async def test_lifecycle_body_cannot_post_actor_or_allowance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f, api, common, _ = await routed_case(tmp_path, monkeypatch)
    goal = f.prepared.binding.goal
    path = f"/api/v2/companies/{f.scope.company_id}/planning/goals/{goal.goal_id}/bootstrap"
    async with AsyncTestClient(create_company_app(common, planning_services=api)) as client:
        response = await client.post(
            path,
            headers=headers(f),
            json={
                "goal": goal.model_dump(mode="json"),
                "expected_current_revision_id": None,
                "actor_id": str(f.owner.principal_id),
                "allocation_usd": "5",
            },
        )
        assert response.status_code == 422


async def lifecycle_app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> PlanningApplication:
    """Actual concrete application, supplied directory rows, no SQL/provider or worker session."""
    configured = configuration(tmp_path)
    value = compose_planning_application(
        async_sessionmaker[AsyncSession](),
        configured,
        application_settings(),
        SuppliedCredential(),
        SecretStr(TEST_SIGNER),
    )
    monkeypatch.setattr(settings, "jwt_secret_key", TEST_SIGNER)
    admission = configured.admission
    company = DirectoryCompany(
        company_id=admission.company_id,
        workspace_id=admission.procedure.binding.workspace_id,
        owner_id=admission.procedure.binding.actor_id,
        company_active=True,
        workspace_active=True,
    )
    member = DirectoryMembership(
        company_id=company.company_id,
        principal_id=company.owner_id,
        role="owner",
        principal_active=True,
        membership_active=True,
    )
    pair = MagicMock()
    pair.one_or_none.return_value = (company, member)
    delivered = AsyncMock(spec=AsyncSession)
    delivered.execute.return_value = pair
    control = CompanyControl(
        company_id=company.company_id,
        owner_id=company.owner_id,
        policy_version=configured.policy_version,
        price_version=configured.catalog.models.pricebook_version,
        daily_cap_usd=Decimal(5),
        work_cap_usd=Decimal(1),
        paused=False,
    )
    delivered.get.side_effect = lambda model, key: (
        control if model is CompanyControl and key == company.company_id else None
    )

    @asynccontextmanager
    async def session(*args: object, **kwargs: object) -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, delivered)

    for directory in (value.planning.directory, value.management.directory):
        monkeypatch.setattr(directory, "_session", session)
    return value


def lifecycle_headers(value: PlanningApplication, *, seconds: int = 300) -> dict[str, str]:
    now = datetime.now(UTC)
    binding = value.config.admission.procedure.binding
    token = jwt.encode(
        {
            "sub": str(binding.actor_id),
            "workspace_id": str(binding.workspace_id),
            "iat": int(now.timestamp()),
            "exp": int(now.timestamp()) + seconds,
        },
        TEST_SIGNER,
        algorithm="HS256",
    )
    return {"Authorization": "Bearer " + token}


def plan(value: PlanningApplication) -> PlanRevision:
    payload = value.config.admission.payload("planning")
    return PlanRevision(
        company_id=payload.company_id,
        plan_id=payload.plan.plan_id,
        plan_revision_id=UUID(int=700),
        revision=1,
        sha256=canonical_sha256(payload),
        payload=payload,
        proposed_by=payload.procedure.binding.actor_id,
        recorded_at=datetime.now(UTC),
    )


async def test_bootstrap_and_existing_approval_forward_true_owner_and_exact_goal_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = await lifecycle_app(tmp_path, monkeypatch)
    saved = plan(value)
    bootstrap = AsyncMock(return_value=PlanningLifecycleRead(saved, clock_us() + 20_000_000))
    approve = AsyncMock(return_value=PlanningLifecycleRead(saved, clock_us() + 20_000_000))
    monkeypatch.setattr(value.lifecycle, "bootstrap", bootstrap)
    monkeypatch.setattr(value.lifecycle, "approve", approve)
    app = create_company_app(
        value.base, management_services=value.management, planning_services=value.planning
    )
    base = f"/api/v2/companies/{value.config.goal.company_id}"
    async with AsyncTestClient(app) as client:
        response = await client.post(
            base + f"/planning/goals/{value.config.goal.goal_id}/bootstrap",
            headers=lifecycle_headers(value),
            json={
                "goal": value.config.goal.model_dump(mode="json"),
                "expected_current_revision_id": None,
            },
        )
        assert response.status_code == 200
        assert PlanRevision.model_validate_json(response.content) == saved
        assert response.headers["cache-control"] == "no-store"
        args = bootstrap.await_args
        assert args is not None
        scope, owner, goal, head = args.args
        assert type(owner) is AuthenticatedWorkerIdentity
        assert scope.principal_id == owner.identity.principal_id == saved.proposed_by
        assert goal == value.config.goal and head is None
        assert clock_us() < args.kwargs["end_us"] < clock_us() + 30_000_000
        response = await client.post(
            base + f"/management/plans/{saved.plan_revision_id}/approve",
            headers=lifecycle_headers(value),
            json={
                "exact_hash": saved.sha256,
                "expected_current_revision_id": str(saved.plan_revision_id),
            },
        )
        assert response.status_code == 200
        assert PlanRevision.model_validate_json(response.content) == saved
        args = approve.await_args
        assert args is not None and type(args.args[1]) is AuthenticatedWorkerIdentity
        assert args.args[2:] == (saved.plan_revision_id, saved.sha256, saved.plan_revision_id)


async def test_complete_serialization_cannot_cross_shortened_lifecycle_cutoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.company.management import planning_native_facts

    value = await lifecycle_app(tmp_path, monkeypatch)
    saved = plan(value)
    current = [1000]
    monkeypatch.setattr(routes, "clock_us", lambda: current[0])
    monkeypatch.setattr(planning_native_facts, "clock_us", lambda: current[0])
    native = AsyncMock(return_value=PlanningLifecycleRead(saved, 1010))
    monkeypatch.setattr(value.lifecycle, "bootstrap", native)
    original = PlanRevision.model_dump_json

    def late(self: PlanRevision, *, by_alias: bool | None = None) -> str:
        raw = original(self, by_alias=by_alias)
        current[0] = 1010
        return raw

    monkeypatch.setattr(PlanRevision, "model_dump_json", late)
    app = create_company_app(value.base, planning_services=value.planning)
    async with AsyncTestClient(app) as client:
        response = await client.post(
            f"/api/v2/companies/{value.config.goal.company_id}/planning/goals/{value.config.goal.goal_id}/bootstrap",
            headers=lifecycle_headers(value),
            json={
                "goal": value.config.goal.model_dump(mode="json"),
                "expected_current_revision_id": None,
            },
        )
        assert response.status_code == 503
        assert "payload" not in response.json()


async def test_status_is_metadata_only_and_invalid_candidate_head_is_denied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = await lifecycle_app(tmp_path, monkeypatch)
    saved = plan(value)
    reference = PlanRevisionRef.model_validate_json(
        saved.model_dump_json(include=set(PlanRevisionRef.model_fields))
    )
    status = PlanningLifecycleStatus(
        company_id=value.config.goal.company_id,
        goal=value.config.goal,
        plan_id=saved.plan_id,
        observed_at=datetime.now(UTC),
        bootstrap=reference,
        current=reference,
        current_state="approved",
        action_id=UUID(int=701),
        proposal_sha256="a" * 64,
        action_state=ActionState.AUTHORIZED,
        owner_decision="approved",
        owner_decision_expires_at=datetime.now(UTC) + timedelta(minutes=1),
        work_state="outcome_unknown",
        workflow_id="native-workflow",
        segment_id=UUID(int=702),
        native_state="outcome_unknown",
        formal_proposal=None,
        resources_pending=False,
    )
    read = AsyncMock(return_value=PlanningLifecycleRead(status, clock_us() + 20_000_000))
    candidate = AsyncMock()
    monkeypatch.setattr(value.lifecycle, "status", read)
    monkeypatch.setattr(value.lifecycle, "candidate", candidate)
    app = create_company_app(value.base, planning_services=value.planning)
    base = f"/api/v2/companies/{value.config.goal.company_id}/planning"
    async with AsyncTestClient(app) as client:
        response = await client.get(
            base + f"/goals/{value.config.goal.goal_id}/status", headers=lifecycle_headers(value)
        )
        assert response.status_code == 200
        assert response.json() == status.model_dump(mode="json")
        assert not {"prepared", "content", "manifest"} & response.json().keys()
        response = await client.get(
            base + f"/actions/{status.action_id}/candidate?expected_current_revision_id=invalid",
            headers=lifecycle_headers(value),
        )
        assert response.status_code == 422
        candidate.assert_not_awaited()


async def test_original_jwt_end_expires_during_directory_io_before_native_operation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = await lifecycle_app(tmp_path, monkeypatch)
    original = value.planning.directory._session
    native = AsyncMock()
    monkeypatch.setattr(value.lifecycle, "status", native)

    @asynccontextmanager
    async def delayed(
        company_id: UUID | None,
        principal_id: UUID,
        *,
        workspace_id: UUID | None,
        task_id: UUID,
        trace_id: UUID,
    ) -> AsyncIterator[AsyncSession]:
        await asyncio.sleep(2.2)
        async with original(
            company_id, principal_id, workspace_id=workspace_id, task_id=task_id, trace_id=trace_id
        ) as session:
            yield session

    monkeypatch.setattr(value.planning.directory, "_session", delayed)
    app = create_company_app(value.base, planning_services=value.planning)
    async with AsyncTestClient(app) as client:
        response = await client.get(
            f"/api/v2/companies/{value.config.goal.company_id}/planning/goals/{value.config.goal.goal_id}/status",
            headers=lifecycle_headers(value, seconds=2),
        )
        assert response.status_code == 503
        native.assert_not_awaited()


async def test_closed_action_routes_forward_owner_refs_hash_and_original_end_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = await lifecycle_app(tmp_path, monkeypatch)
    current = plan(value).plan_revision_id
    action, digest = UUID(int=701), "a" * 64
    selection = {
        "goal": value.config.goal.model_dump(mode="json"),
        "expected_current_revision_id": str(current),
    }
    path = f"/api/v2/companies/{value.config.goal.company_id}/planning"
    cases = [
        (
            "prepare",
            f"/goals/{value.config.goal.goal_id}/prepare",
            selection,
            (value.config.goal, current),
            {},
        ),
        (
            "dispatch",
            f"/actions/{action}/dispatch",
            {"expected_hash": digest},
            (action, digest),
            {},
        ),
        (
            "candidate",
            f"/actions/{action}/candidate?expected_current_revision_id={current}",
            None,
            (action, current),
            {},
        ),
        (
            "propose",
            f"/actions/{action}/proposal",
            selection,
            (action, value.config.goal, current),
            {},
        ),
        (
            "recover_wait",
            f"/actions/{action}/recover-wait",
            selection | {"expected_hash": digest},
            (action, digest),
            {"expected_goal": value.config.goal, "expected_head": current},
        ),
    ]
    app = create_company_app(value.base, planning_services=value.planning)
    async with AsyncTestClient(app) as client:
        for method, suffix, body, expected, keywords in cases:
            delivered = AsyncMock(
                side_effect=ManagementDeniedError("Supplied current native denial")
            )
            monkeypatch.setattr(value.lifecycle, method, delivered)
            if body is None:
                reply = await client.get(path + suffix, headers=lifecycle_headers(value))
            else:
                reply = await client.post(
                    path + suffix, headers=lifecycle_headers(value), json=body
                )
            assert reply.status_code == 403
            args = delivered.await_args
            assert args is not None and args.args[2:] == expected
            owner = args.args[1]
            assert type(owner) is AuthenticatedWorkerIdentity
            assert owner.identity.principal_id == value.config.admission.procedure.binding.actor_id
            assert {key: item for key, item in args.kwargs.items() if key != "end_us"} == keywords
            assert clock_us() < args.kwargs["end_us"] < clock_us() + 30_000_000
        for suffix in (
            f"/goals/{value.config.goal.goal_id}/prepare",
            f"/actions/{action}/proposal",
        ):
            reply = await client.post(
                path + suffix,
                headers=lifecycle_headers(value),
                json=selection
                | {
                    "expected_current_revision_id": None,
                },
            )
            assert reply.status_code == 422


async def test_input_response_preserves_actual_shortened_store_cutoff_through_serialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f, api, common, _ = await routed_case(tmp_path, monkeypatch)
    actual_read = f.store.load_owner

    async def shortened(
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        action_id: UUID,
        *,
        end_us: int,
    ) -> StoredPlanningRequest:
        loaded = await actual_read(scope, identity, action_id, end_us=end_us)
        return replace(loaded, read_end_us=min(end_us, clock_us() + 150_000))

    monkeypatch.setattr(f.store, "load_owner", shortened)
    original = PlanningInputReview.model_dump_json
    serializations = [0]

    def delayed(self: PlanningInputReview, *, by_alias: bool | None = None) -> str:
        raw = original(self, by_alias=by_alias)
        serializations[0] += 1
        if serializations[0] == 2:
            sleep(0.25)
        return raw

    monkeypatch.setattr(PlanningInputReview, "model_dump_json", delayed)
    app = create_company_app(common, planning_services=api)
    async with AsyncTestClient(app) as client:
        reply = await client.get(
            f"/api/v2/companies/{f.scope.company_id}/planning/actions/{f.prepared.request.action_id}/input",
            headers=headers(f),
        )
        assert serializations[0] == 2
        assert reply.status_code == 503
        assert "prepared" not in reply.json()

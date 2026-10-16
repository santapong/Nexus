"""Actual signed bearer and controller; only directory/store delivery is supplied."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest
from litestar.testing import AsyncTestClient

from nexus.company.access import CompanyControlScope
from nexus.company.management.api_contracts import PlanDecision, PlanPropose
from nexus.company.management.api_services import ManagementApiServices
from nexus.company.management.lifecycle import PlanRevision
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.planning_proposal_bridge import PlanningProposalBridge
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.company_app import create_company_app
from nexus.settings import settings
from nexus.tests.unit.nexus_cycle_fixture import base, case, key
from nexus.tests.unit.nexus_report_fixture import credentials
from nexus.tests.unit.test_company_api import services
from nexus.tests.unit.test_company_auth import TEST_KEY


@pytest.mark.parametrize("operation", ["propose", "approve"])
async def test_owner_http_passes_genuine_original_bearer_witness(
    monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    from nexus.api import company_management_routes as routes

    admission, catalog = case()
    payload, record = admission.payload("planning"), base(admission)
    identity = (await credentials(admission.procedure.binding).current()).identity
    scope = CompanyControlScope(
        company_id=admission.company_id,
        principal_id=identity.principal_id,
        operation_id=key("HTTP-operation"),
        trace_id=key("HTTP-trace"),
    )
    plans = ManagementPlanStore(MagicMock(), catalog)
    received: list[AuthenticatedWorkerIdentity] = []

    async def save(*args: object, **kwargs: object) -> PlanRevision:
        witness = kwargs.get("credential")
        assert isinstance(witness, AuthenticatedWorkerIdentity)
        assert witness.identity == identity
        received.append(witness)
        return record

    monkeypatch.setattr(plans, "propose", AsyncMock(side_effect=save))
    monkeypatch.setattr(plans, "approve_and_register", AsyncMock(side_effect=save))
    monkeypatch.setattr(routes, "resolve_company_control", AsyncMock(return_value=scope))
    monkeypatch.setattr(settings, "jwt_secret_key", TEST_KEY)
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256")
    now = datetime.now(UTC)
    expires = int((now + timedelta(seconds=90)).timestamp())
    token = jwt.encode(
        {
            "sub": str(identity.principal_id),
            "workspace_id": str(identity.workspace_id),
            "iat": int(now.timestamp()),
            "exp": expires,
        },
        TEST_KEY,
        algorithm="HS256",
    )
    api = ManagementApiServices(MagicMock(), MagicMock(), MagicMock(), plans)
    path = f"/api/v2/companies/{admission.company_id}/management/plans"
    body = PlanPropose(payload=payload, expected_current_revision_id=None).model_dump(mode="json")
    if operation == "approve":
        path += f"/{record.plan_revision_id}/approve"
        body = PlanDecision(
            exact_hash=record.sha256, expected_current_revision_id=record.plan_revision_id
        ).model_dump(mode="json")
    async with AsyncTestClient(
        create_company_app(services(), management_services=api), raise_server_exceptions=True
    ) as client:
        response = await client.post(path, headers={"Authorization": "Bearer " + token}, json=body)
    assert response.status_code == 200 and len(received) == 1
    assert int(received[0].expires_at.timestamp()) == expires


async def test_bridge_forwards_same_real_owner_credential_without_reminting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nexus.company.management.plan_catalog import PlanAdmissionCatalog
    from nexus.tests.unit.test_company_planning_consumer import planning_registry
    from nexus.tests.unit.test_planning_source_reader import recorded

    reader, native, saved = await recorded(tmp_path)
    source = reader._interpret(saved, native)
    plans = ManagementPlanStore(
        reader.factory,
        PlanAdmissionCatalog(
            company_id=source.origin.company_id,
            models=planning_registry("openai"),
            admitted_profiles=frozenset({"routine"}),
            check_recipes=frozenset(),
        ),
        planning_reader=reader,
    )
    bridge = PlanningProposalBridge(plans, reader)
    owner_binding = reader.template.base_plan.payload.procedure.binding
    witness = await credentials(owner_binding).current()
    scope = CompanyControlScope(
        company_id=owner_binding.company_id,
        principal_id=witness.identity.principal_id,
        operation_id=key("bridge-op"),
        trace_id=key("bridge-trace"),
    )
    monkeypatch.setattr(reader, "load", AsyncMock(return_value=source))
    proposed = AsyncMock(return_value=reader.template.base_plan)
    monkeypatch.setattr(plans, "propose", proposed)
    result = await bridge.propose(
        scope,
        witness.identity,
        native.proposal.action_id,
        expected_goal=reader.template.base_plan.payload.goal,
        expected_current_revision_id=reader.template.base_plan.plan_revision_id,
        end_us=__import__("time").monotonic_ns() // 1000 + 30_000_000,
        credential=witness,
    )
    assert result == reader.template.base_plan
    assert proposed.await_args is not None
    assert proposed.await_args.kwargs["credential"] is witness

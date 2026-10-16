"""Actual JWT/router/owner policy with explicit supplied SQL/native/queue delivery."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import jwt
import pytest
from litestar.testing import AsyncTestClient
from sqlalchemy import Select
from sqlalchemy.sql.elements import TextClause

from nexus.company.access import VerifiedIdentity
from nexus.company.control_store import CompanyControls
from nexus.company.directory_models import DirectoryCompany, DirectoryMembership
from nexus.company.services import CompanyServices
from nexus.company_app import create_company_app
from nexus.execution.qualification_dispatch import QualificationApiServices
from nexus.execution.qualification_reads import QualificationReader
from nexus.harness.journal import CompanyJournal
from nexus.settings import settings
from nexus.tests.unit.test_company_auth import TEST_KEY
from nexus.tests.unit.test_qualification_dispatch import case
from nexus.tests.unit.test_qualification_service import Rows


def directory_delivery(rows: Rows) -> None:
    """Supply the directory JOIN SQL result; actual current owner policy still runs."""

    async def execute(statement: Select[tuple[object]] | TextClause) -> MagicMock:
        value = MagicMock()
        value.one_or_none.return_value = (
            rows.rows[DirectoryCompany],
            rows.rows[DirectoryMembership],
        )
        return value

    cast(MagicMock, rows.session).execute = AsyncMock(side_effect=execute)


def token(identity: VerifiedIdentity) -> dict[str, str]:
    now = datetime.now(UTC)
    return {
        "Authorization": "Bearer "
        + jwt.encode(
            {
                "sub": str(identity.principal_id),
                "workspace_id": str(identity.workspace_id),
                "iat": int(now.timestamp()),
                "exp": int((now + timedelta(minutes=5)).timestamp()),
                "role": "owner",  # Ignored: actual current directory role is checked.
            },
            TEST_KEY,
            algorithm="HS256",
        )
    }


@pytest.fixture(autouse=True)
def signing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "jwt_secret_key", TEST_KEY)
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256")


async def test_default_mount_remains_inactive_without_worker_or_model_construction() -> None:
    from nexus.tests.unit.test_company_api import services

    async with AsyncTestClient(create_company_app(services())) as client:
        response = await client.get(f"/api/v2/companies/{UUID(int=1)}/model-qualification/recipes")
        assert response.status_code == 404


async def test_signed_owner_exact_recipe_review_dispatch_and_runtime_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows, ready, scope, identity, _, dispatch, calls = await case(monkeypatch)
    directory_delivery(rows)
    api = QualificationApiServices(
        dispatch.preparation, dispatch, QualificationReader(dispatch.preparation)
    )
    main = CompanyServices(
        api.directory, CompanyJournal(rows.factory), CompanyControls(rows.factory)
    )
    base = f"/api/v2/companies/{scope.company_id}/model-qualification"
    async with AsyncTestClient(create_company_app(main, qualification_services=api)) as client:
        headers = token(identity)
        listed = await client.get(base + "/recipes", headers=headers)
        assert listed.status_code == 200
        view = listed.json()[0]
        assert view["recipe_sha256"] == ready.recipe_sha256 and view["input_text"]
        repeated_prepare = await client.post(
            base + "/prepare", headers=headers, json={"recipe_id": view["recipe_id"]}
        )
        assert repeated_prepare.status_code == 200
        assert repeated_prepare.json()["action"]["proposal_hash"] == ready.action.proposal_hash
        status = await client.get(base + f"/actions/{ready.request.action_id}", headers=headers)
        assert status.status_code == 200
        assert status.json()["recipe"] == view
        assert (
            status.json()["action"]["proposal"]["parameters"]["recipe_sha256"]
            == view["recipe_sha256"]
        )
        assert "reference" not in str(status.json().get("effect"))
        response = await client.post(
            base + f"/actions/{ready.request.action_id}/dispatch",
            headers=headers,
            json={"expected_hash": ready.action.proposal_hash},
        )
        assert response.status_code == 200 and response.json()["disposition"] == "enqueued"
        duplicate = await client.post(
            base + f"/actions/{ready.request.action_id}/dispatch",
            headers=headers,
            json={"expected_hash": ready.action.proposal_hash},
        )
        assert duplicate.status_code == 200 and duplicate.json()["disposition"] == "existing"
        assert calls == {"claim": 1, "wait": 1, "release": 0, "enqueue": 1}
        result = await client.get(
            base + f"/actions/{ready.request.action_id}/result", headers=headers
        )
        assert result.status_code == 200 and result.json()["availability"] == "unavailable"
        schema = (await client.get("/schema/openapi.json")).json()["components"]["schemas"]
        assert "recipe_sha256" in schema["QualificationRecipeView"]["required"]
        assert (
            schema["QualificationResultView"]["properties"]["profile_quality_evaluated"]["const"]
            is False
        )
        assert schema["QualificationStatus"]["properties"]["recipe"]["$ref"].endswith(
            "/QualificationRecipeView"
        )


@pytest.mark.parametrize(
    "extra", ["target", "input_text", "allocation_usd", "credential", "workflow"]
)
async def test_prepare_accepts_recipe_id_only_and_guard_precedes_body(
    monkeypatch: pytest.MonkeyPatch,
    extra: str,
) -> None:
    rows, ready, scope, identity, _, dispatch, _ = await case(monkeypatch)
    directory_delivery(rows)
    api = QualificationApiServices(
        dispatch.preparation, dispatch, QualificationReader(dispatch.preparation)
    )
    main = CompanyServices(
        api.directory, CompanyJournal(rows.factory), CompanyControls(rows.factory)
    )
    path = f"/api/v2/companies/{scope.company_id}/model-qualification/prepare"
    async with AsyncTestClient(create_company_app(main, qualification_services=api)) as client:
        malformed = await client.post(path, json={"untrusted": True})
        assert malformed.status_code == 401
        bad = await client.post(
            path, headers=token(identity), json={"recipe_id": "public-sdk-probe", extra: "browser"}
        )
        assert bad.status_code in {400, 422}
        assert ready.work.counters.model_requests == 0
        cast(DirectoryMembership, rows.rows[DirectoryMembership]).role = "admin"
        denied = await client.post(
            path, headers=token(identity), json={"recipe_id": "public-sdk-probe"}
        )
        assert denied.status_code == 403


async def test_structured_schema_response_aliases_roundtrip_actual_router() -> None:
    """The public strict codec consumes emitted bytes, including nested request/schema models."""
    from pydantic import TypeAdapter

    from nexus.core.llm.company_adapter_contracts import JsonSchemaDocument
    from nexus.execution.qualification_dispatch import QualificationDispatchService
    from nexus.execution.qualification_read_contracts import (
        QualificationRecipeView,
        QualificationResultView,
        QualificationStatus,
    )
    from nexus.execution.qualification_service import (
        PreparedQualification,
        QualificationPreparationService,
    )
    from nexus.execution.runtime_store import ExecutionStore
    from nexus.tests.unit.test_qualification_service import delivery

    rows, recipe, scope, identity = await delivery()
    recipe = recipe.model_copy(
        update={
            "output_schema": JsonSchemaDocument(
                schema_json='{"type":"object","properties":{"ready":{"type":"boolean"}},"required":["ready"],"additionalProperties":false}'
            )
        }
    )
    preparation = QualificationPreparationService(rows.factory, (recipe,))
    directory_delivery(rows)
    api = QualificationApiServices(
        preparation,
        QualificationDispatchService(preparation, ExecutionStore(rows.factory)),
        QualificationReader(preparation),
    )
    main = CompanyServices(
        api.directory, CompanyJournal(rows.factory), CompanyControls(rows.factory)
    )
    base = f"/api/v2/companies/{scope.company_id}/model-qualification"
    async with AsyncTestClient(create_company_app(main, qualification_services=api)) as client:
        headers = token(identity)
        response = await client.post(
            base + "/prepare", headers=headers, json={"recipe_id": recipe.recipe_id}
        )
        assert response.status_code == 200
        ready = PreparedQualification.model_validate_json(response.content)
        assert ready.request.output_schema == recipe.output_schema
        assert response.json() == ready.model_dump(mode="json", by_alias=True)
        listed = await client.get(base + "/recipes", headers=headers)
        views = TypeAdapter(tuple[QualificationRecipeView, ...]).validate_json(listed.content)
        assert views[0].output_schema == recipe.output_schema
        status_response = await client.get(
            base + f"/actions/{ready.request.action_id}", headers=headers
        )
        status = QualificationStatus.model_validate_json(status_response.content)
        assert status.recipe.output_schema == recipe.output_schema
        unavailable = await client.get(
            base + f"/actions/{ready.request.action_id}/result", headers=headers
        )
        assert (
            QualificationResultView.model_validate_json(unavailable.content).availability
            == "unavailable"
        )
        schemas = (await client.get("/schema/openapi.json")).json()["components"]["schemas"]
        assert "schema_json" in schemas["JsonSchemaDocument"]["properties"]
        assert "document" not in schemas["JsonSchemaDocument"]["properties"]


async def test_safe_result_response_roundtrips_nested_provider_model(tmp_path: "Path") -> None:
    from nexus.execution.qualification_read_contracts import QualificationResultView
    from nexus.tests.unit.test_qualification_reads import saved_case

    rows, reader, scope, identity, action = await saved_case(tmp_path)
    directory_delivery(rows)
    from nexus.execution.qualification_dispatch import QualificationDispatchService
    from nexus.execution.runtime_store import ExecutionStore

    api = QualificationApiServices(
        reader.preparation,
        QualificationDispatchService(reader.preparation, ExecutionStore(rows.factory)),
        reader,
    )
    main = CompanyServices(
        api.directory, CompanyJournal(rows.factory), CompanyControls(rows.factory)
    )
    path = f"/api/v2/companies/{scope.company_id}/model-qualification/actions/{action}/result"
    async with AsyncTestClient(create_company_app(main, qualification_services=api)) as client:
        response = await client.get(path, headers=token(identity))
        assert response.status_code == 200
        value = QualificationResultView.model_validate_json(response.content)
        assert value.availability == "available" and value.provider_result is not None
        assert value.provider_result.text == "READY"
        assert response.json() == value.model_dump(mode="json", by_alias=True)
        assert str(tmp_path) not in response.text

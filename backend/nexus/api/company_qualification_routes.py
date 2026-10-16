"""Optional signed-owner fixed-recipe intake; no credential, target or budget authority in HTTP."""

import asyncio
from uuid import UUID

from litestar import Controller, get, post
from litestar.di import NamedDependency
from litestar.params import FromPath
from litestar.response import Response
from litestar.types import ExceptionHandlersMap
from pydantic import BaseModel, Field, ValidationError

from nexus.api.company_auth import require_company_identity, resolve_company_control
from nexus.api.company_management_routes import invalid, unavailable
from nexus.api.company_routes import ApiContract, ApiError, CompanyRequest, company_identity_guard
from nexus.builder.contained_query import clock_us
from nexus.company.access import (
    AccessDeniedError,
    Capability,
    CompanyControlScope,
    VerifiedIdentity,
)
from nexus.company.contracts.base import Name
from nexus.execution.qualification_dispatch import QualificationApiServices
from nexus.execution.qualification_read_contracts import (
    QualificationDispatchRecord,
    QualificationRecipeView,
    QualificationResultView,
    QualificationStatus,
)
from nexus.execution.qualification_service import PreparedQualification


class PrepareQualificationRequest(ApiContract):
    recipe_id: Name


class DispatchQualificationRequest(ApiContract):
    expected_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


async def _owner(
    request: CompanyRequest, services: QualificationApiServices, company_id: UUID
) -> tuple[CompanyControlScope, VerifiedIdentity]:
    signed = require_company_identity(request)
    scope = await resolve_company_control(
        request, services.directory, company_id=company_id, capability=Capability.GRANT
    )
    return scope, signed


def expired(_: CompanyRequest, __: TimeoutError) -> Response[ApiError]:
    return Response(
        ApiError(
            status_code=503, detail="Qualification request did not finish; inspect current status"
        ),
        status_code=503,
    )


def _response_json(value: BaseModel) -> object:
    """Use the strict public aliases for every nested model on this controller only."""
    return value.model_dump(mode="json", by_alias=True)


class CompanyQualificationController(Controller):
    path = "/api/v2/companies/{company_id:uuid}/model-qualification"
    guards = (company_identity_guard,)
    # Litestar's supported layer encoder overrides the default Pydantic no-alias dump.
    type_encoders = {BaseModel: _response_json}  # noqa: RUF012
    exception_handlers: ExceptionHandlersMap = {  # noqa: RUF012
        AccessDeniedError: unavailable,
        ValidationError: invalid,
        ValueError: invalid,
        TimeoutError: expired,
    }

    @get("/recipes")
    async def recipes(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        qualification_services: NamedDependency[QualificationApiServices],
    ) -> tuple[QualificationRecipeView, ...]:
        scope, signed = await _owner(request, qualification_services, company_id)
        async with asyncio.timeout(30):
            return await qualification_services.reads.recipes(scope, signed)

    @post("/prepare", status_code=200)
    async def prepare(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        data: PrepareQualificationRequest,
        qualification_services: NamedDependency[QualificationApiServices],
    ) -> PreparedQualification:
        scope, signed = await _owner(request, qualification_services, company_id)
        async with asyncio.timeout(30):
            return await qualification_services.preparation.prepare_qualification(
                scope, signed, data.recipe_id
            )

    @post("/actions/{action_id:uuid}/dispatch", status_code=200)
    async def dispatch(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        action_id: FromPath[UUID],
        data: DispatchQualificationRequest,
        qualification_services: NamedDependency[QualificationApiServices],
    ) -> QualificationDispatchRecord:
        scope, signed = await _owner(request, qualification_services, company_id)
        return await qualification_services.dispatch.dispatch(
            scope, signed, action_id, data.expected_hash, end_us=clock_us() + 30_000_000
        )

    @get("/actions/{action_id:uuid}")
    async def status(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        action_id: FromPath[UUID],
        qualification_services: NamedDependency[QualificationApiServices],
    ) -> QualificationStatus:
        scope, signed = await _owner(request, qualification_services, company_id)
        async with asyncio.timeout(30):
            return await qualification_services.reads.action_status(scope, signed, action_id)

    @get("/actions/{action_id:uuid}/result")
    async def result(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        action_id: FromPath[UUID],
        qualification_services: NamedDependency[QualificationApiServices],
    ) -> QualificationResultView:
        scope, signed = await _owner(request, qualification_services, company_id)
        return await qualification_services.reads.result(
            scope, signed, action_id, end_us=clock_us() + 30_000_000
        )

"""Optional current signed-owner exact planning input review; no execution endpoint."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

from litestar import Controller, get
from litestar.di import NamedDependency
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import FromPath
from litestar.response import Response
from litestar.types import ExceptionHandlersMap
from pydantic import BaseModel, ValidationError

from nexus.api.company_auth import (
    require_company_credential,
    require_company_identity,
    resolve_company_control,
)
from nexus.api.company_management_routes import invalid, unavailable
from nexus.api.company_routes import ApiError, CompanyRequest, company_identity_guard
from nexus.company.access import AccessDeniedError, Capability
from nexus.company.management.planning_native_facts import clock_us, require_time
from nexus.company.management.transactions import ManagementDeniedError
from nexus.execution.planning_owner_reads import PlanningApiServices, PlanningInputReview


def expired(_: CompanyRequest, __: TimeoutError) -> Response[ApiError]:
    return Response(
        ApiError(status_code=503, detail="Planning input review expired; refresh"), status_code=503
    )


def _response_json(value: BaseModel) -> object:
    """Keep all nested strict aliases local to this private-input controller."""
    return value.model_dump(mode="json", by_alias=True)


class CompanyPlanningController(Controller):
    path = "/api/v2/companies/{company_id:uuid}/planning"
    guards = (company_identity_guard,)
    type_encoders = {BaseModel: _response_json}  # noqa: RUF012
    exception_handlers: ExceptionHandlersMap = {  # noqa: RUF012
        AccessDeniedError: unavailable,
        ValidationError: invalid,
        ValueError: invalid,
        TimeoutError: expired,
    }

    @get(
        "/actions/{action_id:uuid}/input",
        response_headers={"Cache-Control": "no-store"},
        responses={200: ResponseSpec(data_container=PlanningInputReview, generate_examples=False)},
    )
    async def input(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        action_id: FromPath[UUID],
        planning_services: NamedDependency[PlanningApiServices],
    ) -> Response[bytes]:
        # Anchor before the verifier await. Directory latency cannot renew either window.
        before_us, before_utc = clock_us(), datetime.now(UTC)
        credential = await require_company_credential(request)
        end_us = min(
            before_us + 30_000_000,
            before_us + (credential.expires_at - before_utc) // timedelta(microseconds=1),
        )
        require_time(end_us)
        credential.require_time(datetime.now(UTC))
        async with asyncio.timeout(max(0, end_us - clock_us()) / 1_000_000):
            scope = await resolve_company_control(
                request,
                planning_services.directory,
                company_id=company_id,
                capability=Capability.GRANT,
            )
        if (
            scope.principal_id != credential.identity.principal_id
            or require_company_identity(request) != credential.identity
        ):
            raise ManagementDeniedError("Original planning review identity changed")
        require_time(end_us)
        credential.require_time(datetime.now(UTC))
        value = await planning_services.reads.input(
            scope, credential.identity, action_id, end_us=end_us
        )
        # Emit these exact alias-correct JSON bytes; no deferred/private re-encoding.
        raw = value.model_dump_json(by_alias=True).encode()
        credential.require_time(datetime.now(UTC))
        require_time(end_us)
        return Response(raw, media_type="application/json")

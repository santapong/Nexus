"""Signed current-owner native observation HTTP; no count, completion or execution authority."""

from uuid import UUID

from litestar import Controller, get, post
from litestar.di import NamedDependency
from litestar.exceptions import NotFoundException, ServiceUnavailableException, ValidationException
from litestar.params import FromPath, FromQuery
from litestar.response import Response
from litestar.types import ExceptionHandlersMap
from pydantic import ValidationError

from nexus.api.company_management_read_routes import owner_scope
from nexus.api.company_management_routes import conflict, invalid, unavailable
from nexus.api.company_routes import ApiError, CompanyRequest, company_identity_guard
from nexus.company.access import AccessDeniedError
from nexus.company.brain.scope_support import BrainConflictError, BrainDeniedError
from nexus.company.management.api_services import ManagementApiServices
from nexus.company.management.base import ValueContract
from nexus.company.management.control_support import ManagementConflictError
from nexus.company.management.metric_contracts import (
    MetricCurrentObservation,
    MetricObservationRecord,
    MetricObservationRequest,
)
from nexus.company.management.metric_query_contracts import MetricObservationPage
from nexus.company.management.metric_store import MetricStore
from nexus.execution.runtime_contracts import ExecutionDeniedError


class MetricObservationIntent(ValueContract):
    """Audit/replay IDs identify the append; live signed-owner checks supply authority."""

    request: MetricObservationRequest
    operation_id: UUID
    audit_trace_id: UUID


def configured_metrics(services: ManagementApiServices) -> MetricStore:
    """No default store or provider is created by mounting the routes."""
    if services.metrics is None:
        raise ServiceUnavailableException(detail="Company measurements are not configured")
    return services.metrics


def missing_observation(_: CompanyRequest, __: NotFoundException) -> Response[ApiError]:
    """Pinned Litestar NotFound is also ValueError; keep its specific HTTP status."""
    return Response(
        ApiError(status_code=404, detail="Metric observation unavailable"), status_code=404
    )


class CompanyMetricController(Controller):
    path = "/api/v2/companies/{company_id:uuid}/management/metrics/observations"
    guards = (company_identity_guard,)
    exception_handlers: ExceptionHandlersMap = {  # noqa: RUF012
        AccessDeniedError: unavailable,
        ExecutionDeniedError: unavailable,
        BrainDeniedError: unavailable,
        BrainConflictError: conflict,
        ManagementConflictError: conflict,
        ValidationError: invalid,
        ValidationException: invalid,
        ValueError: invalid,
        NotFoundException: missing_observation,
    }

    @get("/", status_code=200)
    async def current_page(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        goal_id: FromQuery[UUID],
        management_services: NamedDependency[ManagementApiServices],
        after_id: FromQuery[UUID | None] = None,
        limit: FromQuery[int] = 4,
    ) -> MetricObservationPage:
        """Discover bounded fresh facts under one actual owner/source deadline fence."""
        scope, signed = await owner_scope(request, management_services, company_id)
        queries = management_services.metric_queries
        if queries is None:
            raise ServiceUnavailableException(
                detail="Company measurement discovery is not configured"
            )
        return await queries.current_page(scope, signed, goal_id, after_id=after_id, limit=limit)

    @post("/", status_code=200)
    async def observe(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        data: MetricObservationIntent,
        management_services: NamedDependency[ManagementApiServices],
    ) -> MetricObservationRecord:
        """Resolve actual owner and append a native measurement without issuing company work."""
        scope, signed = await owner_scope(request, management_services, company_id)
        if data.request.company_id != company_id:
            raise AccessDeniedError("Metric company is unavailable")
        scope = scope.model_copy(
            update={"operation_id": data.operation_id, "trace_id": data.audit_trace_id}
        )
        return await configured_metrics(management_services).observe(scope, signed, data.request)

    @get("/{observation_id:uuid}/current", status_code=200)
    async def current(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        observation_id: FromPath[UUID],
        management_services: NamedDependency[ManagementApiServices],
    ) -> MetricCurrentObservation:
        """Freshly derive current known/unknown facts; never echo a previously saved count."""
        scope, signed = await owner_scope(request, management_services, company_id)
        result = await configured_metrics(management_services).current(
            scope, signed, observation_id
        )
        if result is None:
            raise NotFoundException(detail="Metric observation unavailable")
        return result

    @get("/{observation_id:uuid}/recorded", status_code=200)
    async def recorded(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        observation_id: FromPath[UUID],
        management_services: NamedDependency[ManagementApiServices],
    ) -> MetricObservationRecord:
        """Return immutable dated history only with its actual current source permissions."""
        scope, signed = await owner_scope(request, management_services, company_id)
        result = await configured_metrics(management_services).get_saved(
            scope, signed, observation_id
        )
        if result is None:
            raise NotFoundException(detail="Metric observation unavailable")
        return result

"""Company reads and owner decisions; no work intake, continuation or effect routes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from litestar import Controller, Request, get, post
from litestar.connection import ASGIConnection
from litestar.datastructures import State
from litestar.di import NamedDependency
from litestar.exceptions import NotFoundException, PermissionDeniedException, ValidationException
from litestar.handlers.base import BaseRouteHandler
from litestar.params import FromPath, FromQuery
from litestar.response import Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from nexus.api.company_auth import (
    require_company_identity,
    resolve_company_control,
    resolve_company_scope,
)
from nexus.company.access import (
    AccessDeniedError,
    Capability,
    PrincipalAccess,
    WorkAccess,
    bind_work_scope,
    require_capability,
    resolve_principal_access,
)
from nexus.company.control_store import CompanyPauseState
from nexus.company.services import CompanyServices
from nexus.harness.journal_contracts import ActionRecord, LedgerScope

CompanyRequest = Request[object, object, State]


class ApiContract(BaseModel):
    """Strict versioned company HTTP payloads cannot carry undeclared scope grants."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)
    schema_version: Literal["nexus.company.api.v1"] = "nexus.company.api.v1"

    @field_validator("approved", "paused", mode="before", check_fields=False)
    @classmethod
    def preserve_boolean_wire_type(cls, value: object) -> object:
        """Litestar's decoder uses strict=False; do not let it relax an intent boolean."""
        if type(value) is not bool:
            raise ValueError("Decision and pause intent require literal JSON booleans")
        return value


class HealthStatus(ApiContract):
    """Liveness only; business intake is deliberately disabled in this profile."""

    status: Literal["alive"] = "alive"
    intake_enabled: Literal[False] = False


class PauseRequest(ApiContract):
    """Owner pause intent without client-supplied actor/company/audit/budget identity."""

    paused: StrictBool


class DecisionRequest(ApiContract):
    """One exact work trace and proposal digest; caller authority comes from signed identity."""

    trace_id: UUID
    expected_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved: StrictBool


class DecisionResponse(ApiContract):
    """Saving a decision does not assert scheduling, execution or business completion."""

    status: Literal["decision_saved"] = "decision_saved"
    scheduled: Literal[False] = False
    executed: Literal[False] = False
    record: ActionRecord


class ApiError(ApiContract):
    """Bounded error response without source records or sensitive input reflection."""

    status_code: int
    detail: str


def company_identity_guard(
    connection: ASGIConnection[BaseRouteHandler, object, object, State], _: BaseRouteHandler
) -> None:
    """Reject missing/invalid JWT before protected request body parsing."""
    require_company_identity(connection)


def validation_error_handler(_: CompanyRequest, __: ValidationException) -> Response[ApiError]:
    """Use the SDD's 422 contract for malformed schema/path/query payloads."""
    return Response(ApiError(status_code=422, detail="Invalid company request"), status_code=422)


@get("/health")
async def company_health() -> HealthStatus:
    """Report process liveness without claiming integration/operating readiness."""
    return HealthStatus()


async def _current_read_work(
    request: CompanyRequest,
    services: CompanyServices,
    scope: LedgerScope,
) -> WorkAccess:
    """Recheck current membership and the same read policy before returning the record."""
    try:
        access = await resolve_principal_access(
            require_company_identity(request),
            services.directory,
            company_id=scope.company_id,
            capability=Capability.READ,
            task_id=scope.task_id,
            trace_id=scope.trace_id,
        )
        work = await services.directory.lookup_work(
            scope.company_id,
            scope.task_id,
            trace_id=scope.trace_id,
        )
        bind_work_scope(
            access, work, task_id=scope.task_id, trace_id=scope.trace_id, capability=Capability.READ
        )
        assert work is not None  # The shared policy rejects missing work.
        return work
    except AccessDeniedError as exc:
        raise PermissionDeniedException(detail="Company work access denied") from exc


class CompanyController(Controller):
    """JWT plus current directory scope for every protected company HTTP route."""

    path = "/api/v2"
    guards = (company_identity_guard,)

    @get("/company")
    async def current_company(
        self, request: CompanyRequest, services: NamedDependency[CompanyServices]
    ) -> PrincipalAccess:
        """Find company from signed workspace plus actual current membership, not token role."""
        access = await services.directory.lookup_principal(
            require_company_identity(request), task_id=uuid4(), trace_id=uuid4()
        )
        if access is None:
            raise PermissionDeniedException(detail="Company access denied")
        try:
            require_capability(access, Capability.READ)
        except AccessDeniedError as exc:
            raise PermissionDeniedException(detail="Company access denied") from exc
        return access

    @get("/companies/{company_id:uuid}/work/{task_id:uuid}")
    async def get_work(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        task_id: FromPath[UUID],
        trace_id: FromQuery[UUID],
        services: NamedDependency[CompanyServices],
    ) -> WorkAccess:
        """Read registered work only under current actor/owner identity and exact trace."""
        scope = await resolve_company_scope(
            request,
            services.directory,
            company_id=company_id,
            task_id=task_id,
            trace_id=trace_id,
            capability=Capability.READ,
        )
        return await _current_read_work(request, services, scope)

    @get("/companies/{company_id:uuid}/work/{task_id:uuid}/actions/{action_id:uuid}")
    async def get_action(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        task_id: FromPath[UUID],
        action_id: FromPath[UUID],
        trace_id: FromQuery[UUID],
        services: NamedDependency[CompanyServices],
    ) -> ActionRecord:
        """Read an exact action after current company/actor/owner/work checks."""
        scope = await resolve_company_scope(
            request,
            services.directory,
            company_id=company_id,
            task_id=task_id,
            trace_id=trace_id,
            capability=Capability.READ,
        )
        try:
            record = await services.journal.get_action(scope, action_id)
        except ValueError as exc:
            raise NotFoundException(detail="Company action unavailable") from exc
        work = await _current_read_work(request, services, scope)
        if record.proposal.trace_id != scope.trace_id or record.proposal.actor_id != work.actor_id:
            raise NotFoundException(detail="Company action unavailable")
        return record

    @post("/companies/{company_id:uuid}/pause", status_code=200)
    async def pause_company(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        data: PauseRequest,
        services: NamedDependency[CompanyServices],
    ) -> CompanyPauseState:
        """Persist owner pause with fresh current-owner checks and server-created audit IDs."""
        scope = await resolve_company_control(
            request, services.directory, company_id=company_id, capability=Capability.PAUSE
        )
        try:
            return await services.controls.set_paused_registered(
                scope, require_company_identity(request), data.paused
            )
        except ValueError as exc:
            raise PermissionDeniedException(detail="Company control denied") from exc

    @post(
        "/companies/{company_id:uuid}/work/{task_id:uuid}/actions/{action_id:uuid}/decision",
        status_code=200,
    )
    async def decide_action(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        task_id: FromPath[UUID],
        action_id: FromPath[UUID],
        data: DecisionRequest,
        services: NamedDependency[CompanyServices],
    ) -> DecisionResponse | Response[ApiError]:
        """Save exact owner decision only; no continuation or tool/model is executed here."""
        scope = await resolve_company_scope(
            request,
            services.directory,
            company_id=company_id,
            task_id=task_id,
            trace_id=data.trace_id,
            capability=Capability.APPROVE,
        )
        try:
            record = await services.journal.approve_registered(
                scope,
                action_id,
                data.expected_hash,
                datetime.now(UTC),
                identity=require_company_identity(request),
                approved=data.approved,
            )
        except AccessDeniedError as exc:
            raise PermissionDeniedException(detail="Company decision denied") from exc
        except ValueError:
            return Response(
                ApiError(
                    status_code=409,
                    detail="Action changed or is unavailable; reload before deciding",
                ),
                status_code=409,
            )
        return DecisionResponse(record=record)

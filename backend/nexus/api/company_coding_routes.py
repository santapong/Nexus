"""Explicit supervised coding steps; owner input cannot supply worker authority."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from litestar import Controller, get, post
from litestar.di import NamedDependency
from litestar.exceptions import ValidationException
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import FromPath, FromQuery
from litestar.response import Response
from litestar.types import ExceptionHandlersMap
from pydantic import BaseModel, ValidationError

from nexus.api.company_auth import (
    require_company_credential,
    require_company_identity,
    resolve_company_control,
)
from nexus.api.company_management_routes import conflict, invalid, unavailable
from nexus.api.company_routes import ApiError, CompanyRequest, company_identity_guard
from nexus.company.access import AccessDeniedError, Capability, CompanyControlScope
from nexus.company.brain.scope_support import BrainConflictError
from nexus.company.management.base import SHA256, ValueContract
from nexus.company.management.control_support import ManagementConflictError
from nexus.company.management.planning_native_facts import clock_us, require_time
from nexus.company.management.transactions import ManagementDeniedError
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.coding_api_services import CodingApiServices
from nexus.execution.coding_dispatch import CodingDispatchRecord
from nexus.execution.coding_lifecycle_contracts import (
    CodingCandidateReview,
    CodingGoalSelection,
    CodingLifecycleRead,
    CodingLifecycleStatus,
)
from nexus.execution.coding_owner_reads import CodingInputReview
from nexus.execution.coding_preparation import PreparedCodingAction
from nexus.execution.runtime_contracts import ExecutionDeniedError

if TYPE_CHECKING:
    from nexus.execution.coding_lifecycle import CodingLifecycle


class DispatchCodingRequest(ValueContract):
    expected_hash: SHA256


class RecoverCodingWaitRequest(CodingGoalSelection):
    expected_current_revision_id: UUID
    expected_hash: SHA256


class CodingNotConfiguredError(RuntimeError):
    """Optional input review is not a configured preparation/dispatch service."""


def unconfigured(_: CompanyRequest, __: CodingNotConfiguredError) -> Response[ApiError]:
    return Response(
        ApiError(status_code=503, detail="Coding is not configured for this company"),
        status_code=503,
        headers={"Cache-Control": "no-store"},
    )


def expired(_: CompanyRequest, __: TimeoutError) -> Response[ApiError]:
    return Response(
        ApiError(status_code=503, detail="Coding request expired; inspect current status"),
        status_code=503,
        headers={"Cache-Control": "no-store"},
    )


def _response_json(value: BaseModel) -> object:
    """Keep all nested strict aliases local to this private-input controller."""
    return value.model_dump(mode="json", by_alias=True)


async def _owner(
    request: CompanyRequest,
    services: CodingApiServices,
    company_id: UUID,
) -> tuple[CompanyControlScope, AuthenticatedWorkerIdentity, int]:
    # Capture the genuine bearer before any directory await, without renewing either end.
    before_us, before_utc = clock_us(), datetime.now(UTC)
    credential = await require_company_credential(request)
    end = min(
        before_us + 30_000_000,
        before_us + (credential.expires_at - before_utc) // timedelta(microseconds=1),
    )
    require_time(end)
    credential.require_time(datetime.now(UTC))
    async with asyncio.timeout(max(0, end - clock_us()) / 1_000_000):
        scope = await resolve_company_control(
            request,
            services.directory,
            company_id=company_id,
            capability=Capability.GRANT,
        )
    if (
        scope.principal_id != credential.identity.principal_id
        or require_company_identity(request) != credential.identity
    ):
        raise ManagementDeniedError("Original coding identity changed")
    require_time(end)
    credential.require_time(datetime.now(UTC))
    return scope, credential, end


def _lifecycle(services: CodingApiServices) -> CodingLifecycle:
    services.require_composition()
    return services.lifecycle


def _reply[T: BaseModel](
    result: CodingLifecycleRead[T],
    credential: AuthenticatedWorkerIdentity,
    end: int,
) -> Response[bytes]:
    end = min(end, result.read_end_us)
    require_time(end)
    raw = result.value.model_dump_json(by_alias=True).encode()
    credential.require_time(datetime.now(UTC))
    require_time(end)
    return Response(raw, media_type="application/json", headers={"Cache-Control": "no-store"})


def _goal(company: UUID, goal: UUID, selection: CodingGoalSelection) -> None:
    if (selection.goal.company_id, selection.goal.goal_id) != (company, goal):
        raise ValueError("Coding goal differs from the requested company/goal")


def _head(value: UUID | None) -> UUID:
    if value is None:
        raise ValueError("The exact current coding head is required")
    return value


class CompanyCodingController(Controller):
    path = "/api/v2/companies/{company_id:uuid}/coding"
    guards = (company_identity_guard,)
    type_encoders = {BaseModel: _response_json}  # noqa: RUF012
    exception_handlers: ExceptionHandlersMap = {  # noqa: RUF012
        AccessDeniedError: unavailable,
        ExecutionDeniedError: unavailable,
        ManagementDeniedError: unavailable,
        ManagementConflictError: conflict,
        BrainConflictError: conflict,
        ValidationError: invalid,
        ValidationException: invalid,
        ValueError: invalid,
        TimeoutError: expired,
        CodingNotConfiguredError: unconfigured,
    }

    @get(
        "/actions/{action_id:uuid}/input",
        responses={200: ResponseSpec(data_container=CodingInputReview, generate_examples=False)},
    )
    async def input(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        action_id: FromPath[UUID],
        coding_services: NamedDependency[CodingApiServices],
    ) -> Response[bytes]:
        scope, owner, end = await _owner(request, coding_services, company_id)
        read = await coding_services.reads.read(scope, owner, action_id, end_us=end)
        return _reply(CodingLifecycleRead(read.value, read.read_end_us), owner, end)

    @get(
        "/goals/{goal_id:uuid}/status",
        responses={
            200: ResponseSpec(data_container=CodingLifecycleStatus, generate_examples=False)
        },
    )
    async def status(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        goal_id: FromPath[UUID],
        coding_services: NamedDependency[CodingApiServices],
    ) -> Response[bytes]:
        scope, owner, end = await _owner(request, coding_services, company_id)
        return _reply(
            await _lifecycle(coding_services).status(scope, owner, goal_id, end_us=end), owner, end
        )

    @post(
        "/goals/{goal_id:uuid}/prepare",
        status_code=200,
        responses={200: ResponseSpec(data_container=PreparedCodingAction, generate_examples=False)},
    )
    async def prepare(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        goal_id: FromPath[UUID],
        data: CodingGoalSelection,
        coding_services: NamedDependency[CodingApiServices],
    ) -> Response[bytes]:
        _goal(company_id, goal_id, data)
        scope, owner, end = await _owner(request, coding_services, company_id)
        return _reply(
            await _lifecycle(coding_services).prepare(
                scope, owner, data.goal, data.expected_current_revision_id, end_us=end
            ),
            owner,
            end,
        )

    @post(
        "/actions/{action_id:uuid}/dispatch",
        status_code=200,
        responses={200: ResponseSpec(data_container=CodingDispatchRecord, generate_examples=False)},
    )
    async def dispatch(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        action_id: FromPath[UUID],
        data: DispatchCodingRequest,
        coding_services: NamedDependency[CodingApiServices],
    ) -> Response[bytes]:
        scope, owner, end = await _owner(request, coding_services, company_id)
        return _reply(
            await _lifecycle(coding_services).dispatch(
                scope, owner, action_id, data.expected_hash, end_us=end
            ),
            owner,
            end,
        )

    @get(
        "/actions/{action_id:uuid}/candidate",
        responses={
            200: ResponseSpec(data_container=CodingCandidateReview, generate_examples=False)
        },
    )
    async def candidate(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        action_id: FromPath[UUID],
        coding_services: NamedDependency[CodingApiServices],
        expected_current_revision_id: FromQuery[UUID],
    ) -> Response[bytes]:
        scope, owner, end = await _owner(request, coding_services, company_id)
        return _reply(
            await _lifecycle(coding_services).candidate(
                scope, owner, action_id, expected_current_revision_id, end_us=end
            ),
            owner,
            end,
        )

    @post(
        "/actions/{action_id:uuid}/recover-wait",
        status_code=200,
        responses={200: ResponseSpec(data_container=PreparedCodingAction, generate_examples=False)},
    )
    async def recover_wait(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        action_id: FromPath[UUID],
        data: RecoverCodingWaitRequest,
        coding_services: NamedDependency[CodingApiServices],
    ) -> Response[bytes]:
        if data.goal.company_id != company_id:
            raise ValueError("Coding Goal belongs to another company")
        scope, owner, end = await _owner(request, coding_services, company_id)
        return _reply(
            await _lifecycle(coding_services).recover_wait(
                scope,
                owner,
                action_id,
                data.expected_hash,
                expected_goal=data.goal,
                expected_current_revision_id=data.expected_current_revision_id,
                end_us=end,
            ),
            owner,
            end,
        )

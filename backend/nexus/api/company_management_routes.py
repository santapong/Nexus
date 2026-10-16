"""Supervised owner direction/plan HTTP operations reuse native current-authority stores."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from litestar import post
from litestar.di import NamedDependency
from litestar.exceptions import ValidationException
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import FromPath
from litestar.response import Response
from litestar.types import ExceptionHandlersMap
from pydantic import ValidationError

from nexus.api.company_auth import (
    require_company_credential,
    require_company_identity,
    resolve_company_control,
)
from nexus.api.company_management_read_routes import CompanyManagementReadController
from nexus.api.company_routes import ApiError, CompanyRequest, company_identity_guard
from nexus.company.access import (
    AccessDeniedError,
    Capability,
    CompanyControlScope,
    VerifiedIdentity,
)
from nexus.company.brain.scope_support import BrainConflictError, BrainDeniedError
from nexus.company.management.api_contracts import (
    CharterPublish,
    GoalPublish,
    MandatePublish,
    PlanDecision,
    PlanPropose,
)
from nexus.company.management.api_services import ManagementApiServices
from nexus.company.management.control_support import ManagementConflictError
from nexus.company.management.goal_store import GoalRevisionRecord
from nexus.company.management.governance import CharterRevision, MandateRevision
from nexus.company.management.lifecycle import PlanRevision
from nexus.company.management.planning_native_facts import clock_us, require_time
from nexus.execution.runtime_contracts import ExecutionDeniedError

if TYPE_CHECKING:
    from nexus.execution.planning_lifecycle import PlanningLifecycle


def unavailable(
    _: CompanyRequest, __: AccessDeniedError | ExecutionDeniedError | BrainDeniedError
) -> Response[ApiError]:
    return Response(
        ApiError(status_code=403, detail="Management operation unavailable"), status_code=403
    )


def conflict(
    _: CompanyRequest, __: ManagementConflictError | BrainConflictError
) -> Response[ApiError]:
    return Response(
        ApiError(status_code=409, detail="Management state changed; refresh"), status_code=409
    )


def invalid(
    _: CompanyRequest, __: ValidationError | ValidationException | ValueError
) -> Response[ApiError]:
    return Response(ApiError(status_code=422, detail="Invalid management request"), status_code=422)


def expired(_: CompanyRequest, __: TimeoutError) -> Response[ApiError]:
    return Response(
        ApiError(status_code=503, detail="Plan request expired; inspect the current plan"),
        status_code=503,
        headers={"Cache-Control": "no-store"},
    )


async def _planning_approval(
    request: CompanyRequest,
    services: ManagementApiServices,
    lifecycle: PlanningLifecycle,
    company_id: UUID,
    revision_id: UUID,
    data: PlanDecision,
) -> Response[bytes]:
    # R2 reconstructs its reader from the actual saved base; owner JWT time starts
    # before directory IO, and the returned source cutoff only shortens this end.
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
        raise AccessDeniedError("Original planning approval identity changed")
    require_time(end)
    credential.require_time(datetime.now(UTC))
    result = await lifecycle.approve(
        scope,
        credential,
        revision_id,
        data.exact_hash,
        data.expected_current_revision_id,
        end_us=end,
    )
    end = min(end, result.read_end_us)
    require_time(end)
    raw = result.value.model_dump_json(by_alias=True).encode()
    credential.require_time(datetime.now(UTC))
    require_time(end)
    return Response(raw, media_type="application/json", headers={"Cache-Control": "no-store"})


async def _owner(
    request: CompanyRequest, services: ManagementApiServices, company_id: UUID
) -> tuple[CompanyControlScope, VerifiedIdentity]:
    identity = require_company_identity(request)
    scope = await resolve_company_control(
        request, services.directory, company_id=company_id, capability=Capability.GRANT
    )
    return scope, identity


class CompanyManagementController(CompanyManagementReadController):
    path = "/api/v2/companies/{company_id:uuid}/management"
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
        TimeoutError: expired,
    }

    @post("/mandate", status_code=200)
    async def publish_mandate(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        data: MandatePublish,
        management_services: NamedDependency[ManagementApiServices],
    ) -> MandateRevision:
        scope, identity = await _owner(request, management_services, company_id)
        return await management_services.controls.publish_mandate(
            scope, identity, data.mandate, expected_revision_id=data.expected_revision_id
        )

    @post("/charters", status_code=200)
    async def publish_charter(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        data: CharterPublish,
        management_services: NamedDependency[ManagementApiServices],
    ) -> CharterRevision:
        scope, identity = await _owner(request, management_services, company_id)
        return await management_services.controls.publish_charter(
            scope,
            identity,
            data.charter,
            mandate=data.mandate,
            expected_revision_id=data.expected_revision_id,
        )

    @post("/goals", status_code=200)
    async def publish_goal(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        data: GoalPublish,
        management_services: NamedDependency[ManagementApiServices],
    ) -> GoalRevisionRecord:
        scope, identity = await _owner(request, management_services, company_id)
        return await management_services.goals.publish(
            scope,
            identity,
            data.definition,
            version=data.version,
            expected_revision_id=data.expected_revision_id,
        )

    @post("/plans", status_code=200)
    async def propose_plan(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        data: PlanPropose,
        management_services: NamedDependency[ManagementApiServices],
    ) -> PlanRevision:
        scope, identity = await _owner(request, management_services, company_id)
        credential = (
            await require_company_credential(request)
            if management_services.plans.catalog.nexus_cycle_admission is not None
            else None
        )
        return await management_services.plans.propose(
            scope,
            identity,
            data.payload,
            expected_current_revision_id=data.expected_current_revision_id,
            credential=credential,
        )

    @post(
        "/plans/{plan_revision_id:uuid}/approve",
        status_code=200,
        responses={
            200: ResponseSpec(data_container=PlanRevision, generate_examples=False),
        },
    )
    async def approve_plan(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        plan_revision_id: FromPath[UUID],
        data: PlanDecision,
        management_services: NamedDependency[ManagementApiServices],
    ) -> PlanRevision | Response[bytes]:
        lifecycle = management_services.require_lifecycle()
        if lifecycle is not None:
            return await _planning_approval(
                request,
                management_services,
                lifecycle,
                company_id,
                plan_revision_id,
                data,
            )
        scope, identity = await _owner(request, management_services, company_id)
        credential = (
            await require_company_credential(request)
            if management_services.plans.catalog.nexus_cycle_admission is not None
            else None
        )
        return await management_services.plans.approve_and_register(
            scope,
            identity,
            plan_revision_id,
            data.exact_hash,
            expected_current_revision_id=data.expected_current_revision_id,
            credential=credential,
        )

    @post("/plans/{plan_revision_id:uuid}/revoke", status_code=200)
    async def revoke_plan(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        plan_revision_id: FromPath[UUID],
        data: PlanDecision,
        management_services: NamedDependency[ManagementApiServices],
    ) -> PlanRevision:
        scope, identity = await _owner(request, management_services, company_id)
        return await management_services.plans.revoke(
            scope,
            identity,
            plan_revision_id,
            data.exact_hash,
            expected_current_revision_id=data.expected_current_revision_id,
        )

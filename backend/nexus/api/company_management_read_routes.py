"""Optional signed-owner read/commitment handlers inherit the company controller guard."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

from litestar import Controller, get, post
from litestar.di import NamedDependency
from litestar.exceptions import ServiceUnavailableException
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import FromPath, FromQuery
from litestar.response import Response

from nexus.api.company_auth import (
    require_company_credential,
    require_company_identity,
    resolve_company_control,
)
from nexus.api.company_routes import ApiError, CompanyRequest
from nexus.company.access import Capability, CompanyControlScope, VerifiedIdentity
from nexus.company.management.action_review_contracts import ActionReview
from nexus.company.management.api_services import ManagementApiServices
from nexus.company.management.commitment_contracts import CommitmentPublish, CommitmentRevision
from nexus.company.management.owner_view_contracts import (
    ApprovalPage,
    CompanyView,
    OwnerViewPage,
    PlanView,
    TodayView,
    WorkView,
)
from nexus.company.management.owner_view_store import ManagementOwnerViews
from nexus.company.management.planning_native_facts import clock_us, require_time
from nexus.company.management.transactions import ManagementDeniedError
from nexus.company.notifications.worker_identity import WorkerIdentityDeniedError


async def owner_scope(
    request: CompanyRequest,
    services: ManagementApiServices,
    company_id: UUID,
) -> tuple[CompanyControlScope, VerifiedIdentity]:
    signed = require_company_identity(request)
    return await resolve_company_control(
        request, services.directory, company_id=company_id, capability=Capability.GRANT
    ), signed


def configured_views(services: ManagementApiServices) -> ManagementOwnerViews:
    if services.views is None:
        raise ServiceUnavailableException(detail="Company owner views are not configured")
    return services.views


def review_expired(
    _: CompanyRequest, __: TimeoutError | WorkerIdentityDeniedError
) -> Response[ApiError]:
    """Expired original READ windows never return previously loaded exact parameters."""
    return Response(
        ApiError(status_code=503, detail="Action review expired; refresh"), status_code=503
    )


class CompanyManagementReadController(Controller):
    @get(
        "/actions/{action_id:uuid}/review",
        response_headers={"Cache-Control": "no-store"},
        responses={200: ResponseSpec(data_container=ActionReview, generate_examples=False)},
        exception_handlers={
            TimeoutError: review_expired,
            WorkerIdentityDeniedError: review_expired,
        },
    )
    async def review_action(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        action_id: FromPath[UUID],
        management_services: NamedDependency[ManagementApiServices],
    ) -> Response[bytes]:
        before, utc = clock_us(), datetime.now(UTC)
        credential = await require_company_credential(request)
        end_us = min(
            before + 30_000_000, before + (credential.expires_at - utc) // timedelta(microseconds=1)
        )
        require_time(end_us)
        credential.require_time(datetime.now(UTC))
        async with asyncio.timeout(max(0, end_us - clock_us()) / 1_000_000):
            scope, signed = await owner_scope(request, management_services, company_id)
        require_time(end_us)
        if signed != credential.identity or scope.principal_id != credential.identity.principal_id:
            raise ManagementDeniedError("Original action review identity changed")
        if management_services.action_reviews is None:
            raise ServiceUnavailableException(detail="Action review is not configured")
        result = await management_services.action_reviews.read(
            scope, credential.identity, action_id, end_us=end_us, credential=credential
        )
        end_us = min(end_us, result.read_end_us)
        raw = result.value.model_dump_json(by_alias=True).encode()
        if len(raw) > 65536:
            raise ManagementDeniedError("Complete action review exceeds its byte bound")
        require_time(end_us)
        credential.require_time(datetime.now(UTC))
        if require_company_identity(request) != credential.identity:
            raise ManagementDeniedError("Original action review session changed")
        require_time(end_us)
        return Response(raw, media_type="application/json")

    @get("/company")
    async def read_company(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        management_services: NamedDependency[ManagementApiServices],
        after_id: FromQuery[UUID | None] = None,
        limit: FromQuery[int] = 32,
    ) -> CompanyView:
        scope, signed = await owner_scope(request, management_services, company_id)
        return await configured_views(management_services).company(
            scope, signed, page=OwnerViewPage(after_id=after_id, limit=limit)
        )

    @get("/today")
    async def read_today(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        management_services: NamedDependency[ManagementApiServices],
        after_id: FromQuery[UUID | None] = None,
        limit: FromQuery[int] = 32,
    ) -> TodayView:
        scope, signed = await owner_scope(request, management_services, company_id)
        return await configured_views(management_services).today(
            scope, signed, page=OwnerViewPage(after_id=after_id, limit=limit)
        )

    @get("/approvals")
    async def read_approvals(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        management_services: NamedDependency[ManagementApiServices],
        after_id: FromQuery[UUID | None] = None,
        limit: FromQuery[int] = 32,
    ) -> ApprovalPage:
        scope, signed = await owner_scope(request, management_services, company_id)
        return await configured_views(management_services).approvals(
            scope, signed, page=OwnerViewPage(after_id=after_id, limit=limit)
        )

    @get("/plans/{plan_id:uuid}")
    async def read_plan(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        plan_id: FromPath[UUID],
        management_services: NamedDependency[ManagementApiServices],
        revision_id: FromQuery[UUID | None] = None,
    ) -> PlanView:
        scope, signed = await owner_scope(request, management_services, company_id)
        return await configured_views(management_services).plan(
            scope, signed, plan_id, revision_id=revision_id
        )

    @get("/work/{task_id:uuid}")
    async def read_work(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        task_id: FromPath[UUID],
        management_services: NamedDependency[ManagementApiServices],
    ) -> WorkView:
        scope, signed = await owner_scope(request, management_services, company_id)
        return await configured_views(management_services).work(scope, signed, task_id)

    @post("/commitments", status_code=200)
    async def publish_commitment(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        data: CommitmentPublish,
        management_services: NamedDependency[ManagementApiServices],
    ) -> CommitmentRevision:
        scope, signed = await owner_scope(request, management_services, company_id)
        if management_services.commitments is None:
            raise ServiceUnavailableException(detail="Company commitments are not configured")
        return await management_services.commitments.publish(
            scope,
            signed,
            data.definition,
            version=data.version,
            expected_revision_id=data.expected_revision_id,
        )

    @get("/commitments/{commitment_id:uuid}")
    async def read_commitment(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        commitment_id: FromPath[UUID],
        management_services: NamedDependency[ManagementApiServices],
    ) -> CommitmentRevision:
        scope, signed = await owner_scope(request, management_services, company_id)
        if management_services.commitments is None:
            raise ServiceUnavailableException(detail="Company commitments are not configured")
        return await management_services.commitments.current(scope, signed, commitment_id)

    @get("/commitments/{commitment_id:uuid}/history")
    async def read_commitment_history(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        commitment_id: FromPath[UUID],
        management_services: NamedDependency[ManagementApiServices],
        after_revision_id: FromQuery[UUID | None] = None,
        limit: FromQuery[int] = 32,
    ) -> tuple[CommitmentRevision, ...]:
        scope, signed = await owner_scope(request, management_services, company_id)
        if management_services.commitments is None:
            raise ServiceUnavailableException(detail="Company commitments are not configured")
        return await management_services.commitments.history(
            scope, signed, commitment_id, after_revision_id=after_revision_id, limit=limit
        )

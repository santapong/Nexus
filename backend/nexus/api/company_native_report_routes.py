"""Current owner report selection and pending preparation; no dispatch or authority minting."""

import asyncio
from typing import Self
from uuid import UUID

from litestar import Controller, get, post
from litestar.di import NamedDependency
from litestar.exceptions import NotFoundException, ServiceUnavailableException, ValidationException
from litestar.params import FromPath
from litestar.response import Response
from litestar.types import ExceptionHandlersMap
from pydantic import AwareDatetime, Field, ValidationError, model_validator

from nexus.api.company_management_read_routes import owner_scope
from nexus.api.company_management_routes import conflict, invalid, unavailable
from nexus.api.company_routes import ApiError, CompanyRequest, company_identity_guard
from nexus.company.access import AccessDeniedError
from nexus.company.brain.scope_support import BrainConflictError, BrainDeniedError
from nexus.company.management.api_services import ManagementApiServices
from nexus.company.management.base import ValueContract
from nexus.company.management.control_support import ManagementConflictError
from nexus.company.management.native_profile_contracts import (
    NativeReportOperatingProfile,
    NativeReportPreparedAction,
    NativeReportProfileRef,
)
from nexus.company.management.native_profile_store import NativeReportPreparationService
from nexus.company.management.operating_report_contracts import SavedOperatingReport
from nexus.company.management.operating_report_store import OperatingReportStore
from nexus.execution.runtime_contracts import ExecutionDeniedError


class NewReportSnapshot(ValueContract):
    """Each explicit request creates a new dated snapshot, never a new workflow or allowance."""

    plan_revision_id: UUID
    author_task_id: UUID
    selected_task_ids: tuple[UUID, ...] = Field(default=(), max_length=100)
    period_start: AwareDatetime
    period_end: AwareDatetime

    @model_validator(mode="after")
    def exact_period_selection(self) -> Self:
        if self.period_end <= self.period_start or len(set(self.selected_task_ids)) != len(
            self.selected_task_ids
        ):
            raise ValueError("Report requires an aware ordered period and unique actual work")
        return self


class ResolveReportProfile(ValueContract):
    report_id: UUID
    commitment_id: UUID
    evidence_ids: tuple[UUID, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def unique_evidence(self) -> Self:
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("Report evidence selection must be unique")
        return self


class PrepareReportAuthor(ValueContract):
    reference: NativeReportProfileRef


def configured_reports(services: ManagementApiServices) -> OperatingReportStore:
    """No default report service is instantiated by the router."""
    if services.reports is None:
        raise ServiceUnavailableException(detail="Native reports are not configured")
    return services.reports


def configured_preparation(services: ManagementApiServices) -> NativeReportPreparationService:
    """Only explicitly configured actual actor/source/resource services can prepare work."""
    if services.report_preparation is None:
        raise ServiceUnavailableException(detail="Native report preparation is not configured")
    return services.report_preparation


def missing_report(_: CompanyRequest, __: NotFoundException) -> Response[ApiError]:
    """Preserve missing-report404 rather than generic validation422."""
    return Response(ApiError(status_code=404, detail="Native report unavailable"), status_code=404)


class CompanyNativeReportController(Controller):
    path = "/api/v2/companies/{company_id:uuid}/management/reports"
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
        NotFoundException: missing_report,
    }

    @post("/", status_code=200)
    async def new_snapshot(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        data: NewReportSnapshot,
        management_services: NamedDependency[ManagementApiServices],
    ) -> SavedOperatingReport:
        """Save an explicit snapshot; expenses retain their actual selected-work lifetime basis."""
        scope, signed = await owner_scope(request, management_services, company_id)
        async with asyncio.timeout(30):
            return await configured_reports(management_services).save_snapshot(
                scope,
                signed,
                data.plan_revision_id,
                data.author_task_id,
                data.selected_task_ids,
                period_start=data.period_start,
                period_end=data.period_end,
            )

    @get("/{report_id:uuid}", status_code=200)
    async def recorded_report(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        report_id: FromPath[UUID],
        management_services: NamedDependency[ManagementApiServices],
    ) -> SavedOperatingReport:
        """Return dated history through current owner and complete native resource permissions."""
        scope, signed = await owner_scope(request, management_services, company_id)
        async with asyncio.timeout(30):
            record = await configured_reports(management_services).get_saved(
                scope, signed, report_id
            )
        if record is None:
            raise NotFoundException(detail="Native report unavailable")
        return record

    @post("/profiles", status_code=200)
    async def resolve_profile(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        data: ResolveReportProfile,
        management_services: NamedDependency[ManagementApiServices],
    ) -> NativeReportOperatingProfile:
        """Resolve existing owner rows; the returned selectors convey no registration permission."""
        scope, signed = await owner_scope(request, management_services, company_id)
        async with asyncio.timeout(30):
            return await configured_preparation(management_services).resolve_profile(
                scope, signed, data.report_id, data.commitment_id, data.evidence_ids
            )

    @post("/profiles/prepare-author", status_code=200)
    async def prepare_author(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        data: PrepareReportAuthor,
        management_services: NamedDependency[ManagementApiServices],
    ) -> NativeReportPreparedAction:
        """Re-resolve the signed owner's exact selection before configured actor preparation."""
        scope, signed = await owner_scope(request, management_services, company_id)
        if data.reference.company_id != company_id:
            raise AccessDeniedError("Native report profile unavailable")
        service = configured_preparation(management_services)
        async with asyncio.timeout(30):
            current = await service.resolve_profile(
                scope,
                signed,
                data.reference.report_id,
                data.reference.commitment.commitment_id,
                data.reference.evidence_ids,
            )
            if current.reference != data.reference:
                raise AccessDeniedError("Native report profile changed")
            return await service.prepare_author(current.reference)

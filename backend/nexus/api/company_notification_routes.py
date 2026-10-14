"""Optional signed current-owner notification reads; no provider calls or action authority."""

from __future__ import annotations

from uuid import UUID

from litestar import Controller, get
from litestar.di import NamedDependency
from litestar.exceptions import NotFoundException, ServiceUnavailableException, ValidationException
from litestar.params import FromPath, FromQuery
from litestar.response import Response
from litestar.types import ExceptionHandlersMap
from pydantic import ValidationError

from nexus.api.company_auth import require_company_identity, resolve_company_control
from nexus.api.company_routes import ApiError, CompanyRequest, company_identity_guard
from nexus.company.access import (
    AccessDeniedError,
    Capability,
    CompanyControlScope,
    VerifiedIdentity,
)
from nexus.company.brain.scope_support import BrainConflictError, BrainDeniedError
from nexus.company.notifications.api_services import NotificationApiServices
from nexus.company.notifications.inbox_contracts import (
    InboxUnavailableError,
    NotificationInboxEntry,
    NotificationInboxPage,
)
from nexus.company.notifications.inbox_store import NotificationInboxStore
from nexus.company.notifications.native_facts import NotificationUnavailableError
from nexus.company.notifications.recipient_registry import RecipientConfigurationError
from nexus.execution.runtime_contracts import ExecutionDeniedError


def denied(_: CompanyRequest, __: Exception) -> Response[ApiError]:
    return Response(ApiError(status_code=403, detail="Owner inbox unavailable"), status_code=403)


def missing(_: CompanyRequest, __: Exception) -> Response[ApiError]:
    return Response(ApiError(status_code=404, detail="Notification unavailable"), status_code=404)


def invalid(_: CompanyRequest, __: Exception) -> Response[ApiError]:
    return Response(ApiError(status_code=422, detail="Invalid inbox request"), status_code=422)


async def notification_owner(
    request: CompanyRequest, services: NotificationApiServices, company_id: UUID
) -> tuple[CompanyControlScope, VerifiedIdentity]:
    signed = require_company_identity(request)
    return await resolve_company_control(
        request, services.directory, company_id=company_id, capability=Capability.GRANT
    ), signed


def configured_inbox(services: NotificationApiServices) -> NotificationInboxStore:
    if services.inbox is None:
        raise ServiceUnavailableException(detail="Owner inbox is not configured")
    return services.inbox


class CompanyNotificationInboxController(Controller):
    path = "/api/v2/companies/{company_id:uuid}/notifications"
    guards = (company_identity_guard,)
    exception_handlers: ExceptionHandlersMap = {  # noqa: RUF012
        AccessDeniedError: denied,
        ExecutionDeniedError: denied,
        BrainDeniedError: denied,
        BrainConflictError: missing,
        NotificationUnavailableError: missing,
        RecipientConfigurationError: missing,
        InboxUnavailableError: missing,
        NotFoundException: missing,
        ValidationError: invalid,
        ValidationException: invalid,
        ValueError: invalid,
    }

    @get("/", status_code=200)
    async def current_page(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        notification_services: NamedDependency[NotificationApiServices],
        after_id: FromQuery[UUID | None] = None,
        limit: FromQuery[int] = 4,
    ) -> NotificationInboxPage:
        scope, signed = await notification_owner(request, notification_services, company_id)
        return await configured_inbox(notification_services).current_page(
            scope, signed, after_id=after_id, limit=limit
        )

    @get("/{draft_id:uuid}", status_code=200)
    async def detail(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        draft_id: FromPath[UUID],
        notification_services: NamedDependency[NotificationApiServices],
    ) -> NotificationInboxEntry:
        scope, signed = await notification_owner(request, notification_services, company_id)
        result = await configured_inbox(notification_services).current(scope, signed, draft_id)
        if result is None:
            raise NotFoundException(detail="Notification unavailable")
        return result

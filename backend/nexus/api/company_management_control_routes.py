"""Current-owner permanent stop and pause/resume descriptors; no execution or allowance minting."""

from typing import Literal
from uuid import UUID

from litestar import Controller, get, post
from litestar.di import NamedDependency
from litestar.exceptions import ServiceUnavailableException, ValidationException
from litestar.params import FromPath
from litestar.types import ExceptionHandlersMap
from pydantic import ValidationError

from nexus.api.company_auth import require_company_identity, resolve_company_control
from nexus.api.company_management_routes import conflict, invalid, unavailable
from nexus.api.company_routes import CompanyRequest, PauseRequest, company_identity_guard
from nexus.company.access import AccessDeniedError, Capability
from nexus.company.brain.scope_support import BrainConflictError, BrainDeniedError
from nexus.company.management.api_services import ManagementApiServices
from nexus.company.management.base import ManagementContract, ValueContract
from nexus.company.management.cancellation_contracts import CancellationCommand, OwnerCancellation
from nexus.company.management.control_support import ManagementConflictError
from nexus.execution.runtime_contracts import ExecutionDeniedError


class WorkCancellationIntent(ValueContract):
    """Audit/replay IDs supply no authority; current signed owner and native target are checked."""

    intent: Literal["cancel_work_permanently"]
    command: CancellationCommand
    operation_id: UUID
    audit_trace_id: UUID


class ManagementControlDescriptor(ManagementContract):
    """UI endpoint/intent descriptions are neither an execution permit nor an uncancel operation."""

    cancellation_endpoint: str
    cancellation_intent: Literal["cancel_work_permanently"] = "cancel_work_permanently"
    pause_endpoint: str
    pause_body: PauseRequest
    resume_body: PauseRequest
    cancellation_is_permanent: Literal[True] = True
    resume_preserves_cancellation: Literal[True] = True


class CompanyManagementControlController(Controller):
    path = "/api/v2/companies/{company_id:uuid}/management/control"
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
    }

    @get("/", status_code=200)
    async def descriptor(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        management_services: NamedDependency[ManagementApiServices],
    ) -> ManagementControlDescriptor:
        """Company view provides pause state; endpoint descriptions grant no capability."""
        await resolve_company_control(
            request,
            management_services.directory,
            company_id=company_id,
            capability=Capability.GRANT,
        )
        if management_services.cancellations is None:
            raise ServiceUnavailableException(detail="Company work cancellation is not configured")
        return ManagementControlDescriptor(
            company_id=company_id,
            cancellation_endpoint=(
                f"/api/v2/companies/{company_id}/management/control/work/{{task_id}}/cancel"
            ),
            pause_endpoint=f"/api/v2/companies/{company_id}/pause",
            pause_body=PauseRequest(paused=True),
            resume_body=PauseRequest(paused=False),
        )

    @post("/work/{task_id:uuid}/cancel", status_code=200)
    async def cancel_work(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        task_id: FromPath[UUID],
        data: WorkCancellationIntent,
        management_services: NamedDependency[ManagementApiServices],
    ) -> OwnerCancellation:
        """Stop exact work/descendants while preserving issued facts and allowances."""
        identity = require_company_identity(request)
        scope = await resolve_company_control(
            request,
            management_services.directory,
            company_id=company_id,
            capability=Capability.GRANT,
        )
        store = management_services.cancellations
        if store is None:
            raise ServiceUnavailableException(detail="Company work cancellation is not configured")
        if data.command.company_id != company_id or data.command.target.task_id != task_id:
            raise AccessDeniedError("Exact cancellation target is unavailable")
        # Requested IDs identify immutable audit/replay history. The principal,
        # company/workspace authority and actual registration are server-derived.
        scope = scope.model_copy(
            update={"operation_id": data.operation_id, "trace_id": data.audit_trace_id}
        )
        return await store.cancel(scope, identity, data.command)

"""Explicit current-owner whole-family financial reads; no execution or model startup."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from litestar import Controller, get
from litestar.di import NamedDependency
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import FromPath
from litestar.response import Response
from litestar.types import ExceptionHandlersMap

from nexus.api.company_auth import (
    require_company_credential,
    require_company_identity,
    resolve_company_control,
)
from nexus.api.company_routes import ApiError, CompanyRequest, company_identity_guard
from nexus.company.access import AccessDeniedError, Capability
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management.cycle_cost_contracts import SNAPSHOT_LIMIT, CycleCostSnapshot
from nexus.company.management.cycle_cost_snapshot import CycleCostSnapshotReader
from nexus.company.management.planning_native_facts import clock_us, require_time
from nexus.company.notifications.worker_identity import WorkerIdentityDeniedError


@dataclass(frozen=True, slots=True)
class CycleCostApiServices:
    """Same concrete native/private reader graph; construction performs no IO."""

    directory: PersistentCompanyDirectory
    reads: CycleCostSnapshotReader
    _bound: tuple[object, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_bound", (self.directory, self.reads))
        self.require_composition()

    def require_composition(self) -> None:
        """A copied descriptor or replacement store cannot become financial authority."""
        if (
            type(self.directory) is not PersistentCompanyDirectory
            or type(self.reads) is not CycleCostSnapshotReader
            or self.directory._factory is not self.reads.factory
            or any(
                a is not b for a, b in zip((self.directory, self.reads), self._bound, strict=True)
            )
        ):
            raise ValueError("Original company financial API graph differs")
        self.reads.require_composition()


def _error(status: int, detail: str) -> Response[ApiError]:
    return Response(
        ApiError(status_code=status, detail=detail),
        status_code=status,
        headers={"Cache-Control": "no-store"},
    )


def _expired(_: CompanyRequest, __: TimeoutError | WorkerIdentityDeniedError) -> Response[ApiError]:
    return _error(503, "Financial read expired; refresh")


def _unavailable(_: CompanyRequest, __: ValueError) -> Response[ApiError]:
    return _error(409, "Financial snapshot changed or is unavailable; refresh")


def _denied(_: CompanyRequest, __: AccessDeniedError) -> Response[ApiError]:
    return _error(403, "Company financial access denied")


class CompanyCycleCostController(Controller):
    """One configured family audit; callers cannot select actors, sources or cost authority."""

    path = "/api/v2/companies/{company_id:uuid}/management/cycle-costs"
    guards = (company_identity_guard,)
    exception_handlers: ExceptionHandlersMap = {  # noqa: RUF012
        AccessDeniedError: _denied,
        ValueError: _unavailable,
        TimeoutError: _expired,
        WorkerIdentityDeniedError: _expired,
    }

    @get(
        response_headers={"Cache-Control": "no-store"},
        responses={200: ResponseSpec(data_container=CycleCostSnapshot, generate_examples=False)},
    )
    async def read(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        cycle_cost_services: NamedDependency[CycleCostApiServices],
    ) -> Response[bytes]:
        """Keep the original bearer and native/source ends through final complete bytes."""
        api = cycle_cost_services
        api.require_composition()
        before, utc = clock_us(), datetime.now(UTC)
        owner = await require_company_credential(request)
        end = min(
            before + 30_000_000,
            before + (owner.expires_at - utc) // timedelta(microseconds=1),
        )
        require_time(end)
        owner.require_time(datetime.now(UTC))
        async with asyncio.timeout(max(0, end - clock_us()) / 1_000_000):
            scope = await resolve_company_control(
                request,
                api.directory,
                company_id=company_id,
                capability=Capability.GRANT,
            )
        require_time(end)
        if scope.principal_id != owner.identity.principal_id:
            raise ValueError("Original financial owner changed")
        found = await api.reads.read(scope, owner, end_us=end)
        end = min(end, found.read_end_us)
        api.require_composition()
        require_time(end)
        if found.value.company_id != company_id:
            raise ValueError("Financial snapshot belongs to another company")
        raw = found.value.model_dump_json(by_alias=True).encode()
        if len(raw) > SNAPSHOT_LIMIT:
            raise ValueError("Complete financial snapshot exceeds its byte bound")
        require_time(end)
        owner.require_time(datetime.now(UTC))
        if require_company_identity(request) != owner.identity:
            raise ValueError("Original financial bearer changed")
        require_time(end)
        return Response(raw, media_type="application/json", headers={"Cache-Control": "no-store"})

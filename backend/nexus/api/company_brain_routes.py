"""Signed, read-only Brain HTTP queries; no model, authority, source write or work intake."""

from __future__ import annotations

from uuid import UUID

from litestar import Controller, get, post
from litestar.di import NamedDependency
from litestar.exceptions import ValidationException
from litestar.params import FromPath, FromQuery
from litestar.response import Response
from litestar.types import ExceptionHandlersMap
from pydantic import ValidationError

from nexus.api.company_auth import require_company_identity
from nexus.api.company_routes import ApiError, CompanyRequest, company_identity_guard
from nexus.company.access import AccessDeniedError, VerifiedIdentity
from nexus.company.brain.api_services import (
    BrainServices,
    ContextRead,
    SearchRead,
    WorkBinding,
    current_entity,
    resolve_brain_read,
)
from nexus.company.brain.artifact_contracts import ArtifactSlice
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.context import AssembledContext
from nexus.company.brain.ontology import EntityRevisionRecord
from nexus.company.brain.retrieval import MaterializedEvidence, RetrievalResult
from nexus.company.brain.scope_support import BrainConflictError
from nexus.company.brain.sources import SourceHead


def denied_error(_: CompanyRequest, __: AccessDeniedError) -> Response[ApiError]:
    return Response(ApiError(status_code=403, detail="Brain resource unavailable"), status_code=403)


def conflict_error(_: CompanyRequest, __: BrainConflictError) -> Response[ApiError]:
    return Response(
        ApiError(status_code=409, detail="Brain state changed; refresh"), status_code=409
    )


def invalid_error(
    _: CompanyRequest, __: ValidationError | ValidationException
) -> Response[ApiError]:
    return Response(ApiError(status_code=422, detail="Invalid Brain request"), status_code=422)


async def _scope(
    request: CompanyRequest, services: BrainServices, company_id: UUID, binding: WorkBinding
) -> tuple[BrainReadScope, VerifiedIdentity]:
    identity = require_company_identity(request)
    return await resolve_brain_read(services.directory, identity, company_id, binding), identity


class CompanyBrainController(Controller):
    """Opt-in controller; production mounting belongs to the isolated company app factory."""

    path = "/api/v2/companies/{company_id:uuid}/brain"
    guards = (company_identity_guard,)
    # Litestar declares this class configuration as an instance variable.
    exception_handlers: ExceptionHandlersMap = {  # noqa: RUF012
        AccessDeniedError: denied_error,
        BrainConflictError: conflict_error,
        ValidationError: invalid_error,
        ValidationException: invalid_error,
    }

    @post("/search", status_code=200)
    async def search(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        data: SearchRead,
        brain_services: NamedDependency[BrainServices],
    ) -> RetrievalResult:
        scope, identity = await _scope(request, brain_services, company_id, data)
        return await brain_services.retriever.search(
            scope, identity, data.search.selection(company_id)
        )

    @post("/context", status_code=200)
    async def context(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        data: ContextRead,
        brain_services: NamedDependency[BrainServices],
    ) -> AssembledContext:
        scope, identity = await _scope(request, brain_services, company_id, data)
        return await brain_services.assembler.assemble(scope, identity, data.selection(company_id))

    @get("/evidence/{evidence_id:uuid}")
    async def evidence(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        evidence_id: FromPath[UUID],
        brain_services: NamedDependency[BrainServices],
        task_id: FromQuery[UUID | None] = None,
        task_trace_id: FromQuery[UUID | None] = None,
        include_history: FromQuery[bool] = False,
    ) -> MaterializedEvidence:
        scope, identity = await _scope(
            request,
            brain_services,
            company_id,
            WorkBinding(task_id=task_id, task_trace_id=task_trace_id),
        )
        materials = await brain_services.retriever.get_evidence(
            scope, identity, (evidence_id,), include_history=include_history
        )
        return materials[0]

    @get("/entities/{entity_id:uuid}")
    async def entity(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        entity_id: FromPath[UUID],
        brain_services: NamedDependency[BrainServices],
        task_id: FromQuery[UUID | None] = None,
        task_trace_id: FromQuery[UUID | None] = None,
    ) -> EntityRevisionRecord:
        scope, identity = await _scope(
            request,
            brain_services,
            company_id,
            WorkBinding(task_id=task_id, task_trace_id=task_trace_id),
        )
        return await current_entity(brain_services, scope, identity, entity_id)

    @get("/artifacts/{artifact_revision_id:uuid}")
    async def artifact(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        artifact_revision_id: FromPath[UUID],
        brain_services: NamedDependency[BrainServices],
        task_id: FromQuery[UUID | None] = None,
        task_trace_id: FromQuery[UUID | None] = None,
        start_byte: FromQuery[int] = 0,
        include_history: FromQuery[bool] = False,
    ) -> ArtifactSlice:
        if start_byte < 0 or start_byte > 2_097_152:
            raise ValidationException(detail="Invalid artifact offset")
        scope, identity = await _scope(
            request,
            brain_services,
            company_id,
            WorkBinding(task_id=task_id, task_trace_id=task_trace_id),
        )
        return await brain_services.retriever.bounded_artifact(
            scope,
            identity,
            artifact_revision_id,
            start_byte=start_byte,
            max_bytes=16_384,
            include_history=include_history,
        )

    @get("/sources/{source_id:uuid}/freshness")
    async def freshness(
        self,
        request: CompanyRequest,
        company_id: FromPath[UUID],
        source_id: FromPath[UUID],
        brain_services: NamedDependency[BrainServices],
        task_id: FromQuery[UUID | None] = None,
        task_trace_id: FromQuery[UUID | None] = None,
    ) -> SourceHead:
        scope, identity = await _scope(
            request,
            brain_services,
            company_id,
            WorkBinding(task_id=task_id, task_trace_id=task_trace_id),
        )
        return (await brain_services.retriever.current_source_heads(scope, identity, (source_id,)))[
            0
        ]

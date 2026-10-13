"""HTTP authentication/strict read inputs; persistent payload acceptance is a separate gate."""

from __future__ import annotations

from uuid import UUID

import pytest
from litestar import Litestar
from litestar.di import Provide
from litestar.testing import AsyncTestClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.api.company_brain_routes import CompanyBrainController
from nexus.api.company_routes import company_health
from nexus.company.access import PrincipalAccess, VerifiedIdentity, WorkAccess
from nexus.company.brain.api_services import (
    BrainServices,
    ContextRead,
    SearchRead,
    WorkBinding,
    resolve_brain_read,
)
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.context import ContextAuthorityState, ContextLimits
from nexus.company.brain.context_store import PersistentContextAssembler
from nexus.company.brain.retrieval import RetrievalResult, SearchRequest
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.brain.scope_support import BrainConflictError, BrainDeniedError
from nexus.settings import settings
from nexus.tests.integration.test_company_api import KEY, headers
from nexus.tests.integration.test_company_directory import (
    ACTOR,
    COMPANY,
    OWNER,
    TASK,
    TRACE,
    WORKSPACE,
)


class Directory:
    async def lookup_principal(
        self, identity: VerifiedIdentity, *, task_id: UUID, trace_id: UUID
    ) -> PrincipalAccess | None:
        if identity.workspace_id != WORKSPACE or identity.principal_id not in (OWNER, ACTOR):
            return None
        return PrincipalAccess(
            company_id=COMPANY,
            workspace_id=WORKSPACE,
            principal_id=identity.principal_id,
            owner_id=OWNER,
            membership_role="owner" if identity.principal_id == OWNER else "member",
            company_active=True,
            workspace_active=True,
            principal_active=True,
            membership_active=True,
        )

    async def lookup_work(
        self, company_id: UUID, task_id: UUID, *, trace_id: UUID
    ) -> WorkAccess | None:
        if (company_id, task_id, trace_id) != (COMPANY, TASK, TRACE):
            return None
        return WorkAccess(
            company_id=COMPANY,
            workspace_id=WORKSPACE,
            task_id=TASK,
            trace_id=TRACE,
            actor_id=ACTOR,
            active=True,
            allowed_principals=(ACTOR,),
        )


class NoPayload(PersistentBrainRetriever):
    def __init__(self) -> None:
        self.last_scope: BrainReadScope | None = None
        self.failure: type[Exception] | None = None

    async def search(
        self, scope: BrainReadScope, identity: VerifiedIdentity, request: SearchRequest
    ) -> RetrievalResult:
        self.last_scope = scope
        if self.failure:
            raise self.failure("private sentinel must never enter an error response")
        return RetrievalResult(company_id=scope.company_id, query_sha256="0" * 64, truncated=False)


class NoAuthority:
    async def current(
        self, session: AsyncSession, scope: BrainReadScope, identity: VerifiedIdentity
    ) -> ContextAuthorityState:
        raise AssertionError("This input/auth test must not assemble context")


@pytest.fixture
def aggregate(monkeypatch: pytest.MonkeyPatch) -> BrainServices:
    monkeypatch.setattr(settings, "jwt_secret_key", KEY)
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256")
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(expire_on_commit=False)
    retriever = NoPayload()
    # NoAuthority is never called in this isolated HTTP boundary fixture.
    assembler = PersistentContextAssembler(factory, retriever, NoAuthority(), limits=_limits())
    return BrainServices(Directory(), retriever, assembler)


def _limits() -> ContextLimits:
    return ContextLimits(policy_version="fixture.api.v1")


def app(aggregate: BrainServices) -> Litestar:
    def provide_brain_services() -> BrainServices:
        return aggregate

    return Litestar(
        [company_health, CompanyBrainController],
        dependencies={
            "brain_services": Provide(provide_brain_services, use_cache=True, sync_to_thread=False)
        },
    )


BASE = f"/api/v2/companies/{COMPANY}/brain"


@pytest.mark.parametrize(
    "extra",
    [
        {"actor_id": str(OWNER)},
        {"allowed_principals": [str(ACTOR)]},
        {"max_results": 100},
        {"data_classification": "public"},
        {"work_cap_usd": "100"},
    ],
)
async def test_search_rejects_authority_and_limit_input(
    aggregate: BrainServices, extra: dict[str, object]
) -> None:
    async with AsyncTestClient(app(aggregate)) as client:
        response = await client.post(
            BASE + "/search", headers=headers(), json={"search": {"query": "evidence", **extra}}
        )
        assert response.status_code == 422


@pytest.mark.parametrize("history", ["true", 1, 0, None])
async def test_actual_http_decoder_cannot_relax_literal_history_flag(
    aggregate: BrainServices, history: object
) -> None:
    async with AsyncTestClient(app(aggregate)) as client:
        response = await client.post(
            BASE + "/search",
            headers=headers(),
            json={"search": {"query": "evidence", "include_history": history}},
        )
        assert response.status_code == 422


async def test_signed_identity_is_guarded_before_malformed_body(aggregate: BrainServices) -> None:
    async with AsyncTestClient(app(aggregate)) as client:
        missing = await client.post(BASE + "/search", json={"budget": 100})
        assert missing.status_code == 401
        bad = await client.post(
            BASE + "/search",
            headers=headers(key="wrong-fixture-key-with-at-least-32-bytes"),
            json={},
        )
        assert bad.status_code == 401
        foreign = await client.post(
            f"/api/v2/companies/{UUID(int=99)}/brain/search",
            headers=headers(),
            json={"search": {"query": "evidence"}},
        )
        assert foreign.status_code == 403


async def test_work_actor_and_audit_ids_are_derived_from_registered_directory(
    aggregate: BrainServices,
) -> None:
    async with AsyncTestClient(app(aggregate)) as client:
        response = await client.post(
            BASE + "/search",
            headers=headers(OWNER),
            json={
                "task_id": str(TASK),
                "task_trace_id": str(TRACE),
                "search": {"query": "evidence"},
            },
        )
        assert response.status_code == 200
    assert isinstance(aggregate.retriever, NoPayload)
    scope = aggregate.retriever.last_scope
    assert scope is not None and scope.principal_id == OWNER and scope.actor_id == ACTOR
    assert scope.operation_id != TASK and scope.trace_id != TRACE


@pytest.mark.parametrize("failure,status", [(BrainDeniedError, 403), (BrainConflictError, 409)])
async def test_typed_failures_expose_generic_error_only(
    aggregate: BrainServices, failure: type[Exception], status: int
) -> None:
    assert isinstance(aggregate.retriever, NoPayload)
    aggregate.retriever.failure = failure
    async with AsyncTestClient(app(aggregate)) as client:
        response = await client.post(
            BASE + "/search", headers=headers(), json={"search": {"query": "evidence"}}
        )
        assert response.status_code == status and "sentinel" not in response.text


@pytest.mark.parametrize("body", [{"task_id": TASK}, {"task_trace_id": TRACE}])
def test_work_binding_requires_registered_pair(body: dict[str, UUID]) -> None:
    with pytest.raises(ValidationError):
        WorkBinding.model_validate(body)


async def test_company_read_mints_no_work_or_actor_binding() -> None:
    scope = await resolve_brain_read(
        Directory(),
        VerifiedIdentity(principal_id=ACTOR, workspace_id=WORKSPACE),
        COMPANY,
        WorkBinding(),
    )
    assert scope.task_id is None and scope.task_trace_id is None and scope.actor_id is None


def test_context_has_only_read_selections_and_server_constructs_company_refs() -> None:
    parsed = ContextRead(attachments=(UUID(int=1),), workspace_files=(UUID(int=2),))
    selection = parsed.selection(COMPANY)
    assert selection.attachments[0].company_id == COMPANY
    assert selection.workspace_files[0].evidence_id == UUID(int=2)
    with pytest.raises(ValidationError):
        SearchRead.model_validate({"search": {"query": "x"}, "operation_id": UUID(int=3)})

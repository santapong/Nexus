"""Actual HTTP witness forwarding; current SQL/source delivery is explicitly supplied."""

from pathlib import Path
from uuid import UUID

import pytest
from litestar import Litestar
from litestar.testing import AsyncTestClient

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.management.action_review_store import OwnerActionReviewStore, ReviewedAction
from nexus.company.management.planning_native_facts import clock_us
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.tests.unit.test_coding_owner_reads import OwnerCase
from nexus.tests.unit.test_planning_action_review_api import headers, path, routed


async def test_original_genuine_owner_credential_survives_directory_io_to_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = OwnerActionReviewStore.read
    received: list[AuthenticatedWorkerIdentity | None] = []

    async def inspect(
        self: OwnerActionReviewStore,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        action: UUID,
        *,
        end_us: int,
        credential: AuthenticatedWorkerIdentity | None = None,
    ) -> ReviewedAction:
        received.append(credential)
        return await original(self, scope, identity, action, end_us=end_us, credential=credential)

    monkeypatch.setattr(OwnerActionReviewStore, "read", inspect)
    fixture, app, _ = await routed(tmp_path, monkeypatch)
    async with AsyncTestClient(app, raise_server_exceptions=True) as client:
        response = await client.get(path(fixture), headers=headers(fixture))
        assert response.status_code == 200
    assert received and type(received[0]) is AuthenticatedWorkerIdentity
    assert received[0].identity == fixture.owner


async def test_c_exact_generic_review_requires_same_original_owner_and_real_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nexus.company.management.action_review_store import OwnerActionReviewStore
    from nexus.company.management.planning_native_facts import clock_us
    from nexus.tests.unit.test_coding_owner_reads import owner_case

    f = await owner_case(tmp_path, monkeypatch)
    value = await f.reviews.read(
        f.scope, f.owner.identity, f.row.id, end_us=clock_us() + 10_000_000, credential=f.owner
    )
    assert value.value.availability == "available" and value.value.detail is not None
    assert value.value.detail.proposal_sha256 == f.row.proposal_hash
    assert f.delivery.action is not None
    assert value.value.detail.proposal.parameters == f.delivery.action.parameters
    assert f.prepared.request.input_text not in value.value.model_dump_json(by_alias=True)
    assert not f.reviews.pending_owners()
    # Old identity-only entrypoints cannot manufacture the C credential witness.
    old = await f.reviews.review(f.scope, f.owner.identity, f.row.id)
    assert old.availability == "unavailable" and old.detail is None
    unconfigured = OwnerActionReviewStore(
        f.services.factory, f.services.management.catalog, f.services.source_views
    )
    missing = await unconfigured.read(
        f.scope, f.owner.identity, f.row.id, end_us=clock_us() + 10_000_000, credential=f.owner
    )
    assert missing.value.availability == "unavailable" and missing.value.detail is None


@pytest.mark.parametrize("fault", ["marker", "extra-field", "static", "owner"])
async def test_c_unknown_markers_or_incomplete_sources_have_no_generic_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    from unittest.mock import AsyncMock

    from nexus.company.contracts.actions import ActionProposal, ResourceRevision
    from nexus.company.management import action_review_store as generic
    from nexus.company.management.planning_native_facts import clock_us
    from nexus.harness.canonical import action_hash
    from nexus.tests.unit.test_coding_owner_reads import owner_case

    f = await owner_case(tmp_path, monkeypatch)
    proposal = ActionProposal.model_validate_json(f.row.proposal_json)
    if fault == "marker":
        proposal = proposal.model_copy(
            update={
                "preconditions": (
                    *proposal.preconditions[:-1],
                    ResourceRevision(resource="coding.prepared:foreign", revision="unknown"),
                )
            }
        )
    elif fault == "extra-field":
        proposal = proposal.model_copy(
            update={"parameters": {**proposal.parameters, "authority": "owner"}}
        )
    elif fault == "static":
        monkeypatch.setattr(generic, "review_disclosure", AsyncMock(return_value=None))
    else:
        f.delivery.control.owner_id = f.prepared.binding.actor_id
    f.row.proposal_json = proposal.model_dump_json()
    f.row.proposal_hash = action_hash(proposal)
    result = await f.reviews.read(
        f.scope, f.owner.identity, f.row.id, end_us=clock_us() + 10_000_000, credential=f.owner
    )
    assert result.value.availability == "unavailable" and result.value.detail is None
    assert not f.services._stores


async def routed_c(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[OwnerCase, Litestar]:
    """Actual mounted HTTP/directory auth; only native/source SQL leaves are supplied."""
    from collections.abc import AsyncIterator
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock, MagicMock

    from sqlalchemy.ext.asyncio import AsyncSession

    from nexus.company.control_store import CompanyControls
    from nexus.company.directory_models import DirectoryCompany, DirectoryMembership
    from nexus.company.directory_store import PersistentCompanyDirectory
    from nexus.company.management.api_services import ManagementApiServices
    from nexus.company.management.control_store import ManagementControlStore
    from nexus.company.management.goal_store import GoalStore
    from nexus.company.management.plan_store import ManagementPlanStore
    from nexus.company.services import CompanyServices
    from nexus.company_app import create_company_app
    from nexus.harness.journal import CompanyJournal
    from nexus.settings import settings
    from nexus.tests.unit.test_coding_owner_reads import owner_case
    from nexus.tests.unit.test_company_auth import TEST_KEY

    f = await owner_case(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "jwt_secret_key", TEST_KEY)
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256")
    directory = PersistentCompanyDirectory(f.services.factory)
    company = DirectoryCompany(
        company_id=f.scope.company_id,
        workspace_id=f.owner.identity.workspace_id,
        owner_id=f.owner.identity.principal_id,
        company_active=True,
        workspace_active=True,
    )
    member = DirectoryMembership(
        company_id=f.scope.company_id,
        principal_id=f.owner.identity.principal_id,
        role="owner",
        principal_active=True,
        membership_active=True,
    )

    @asynccontextmanager
    async def session(*args: object, **kwargs: object) -> AsyncIterator[AsyncSession]:
        yield f.session

    monkeypatch.setattr(directory, "_session", session)
    result = MagicMock()
    result.one_or_none.return_value = (company, member)
    monkeypatch.setattr(f.session, "execute", AsyncMock(return_value=result))
    common = CompanyServices(
        directory, CompanyJournal(f.services.factory), CompanyControls(f.services.factory)
    )
    management = ManagementApiServices(
        directory,
        ManagementControlStore(f.services.factory),
        GoalStore(f.services.factory, f.services.contexts._retriever),
        ManagementPlanStore(f.services.factory, f.services.management.catalog),
        action_reviews=f.reviews,
    )
    return f, create_company_app(common, management_services=management)


@pytest.mark.parametrize("late", [False, True])
async def test_actual_c_http_owner_witness_source_cutoff_and_final_aliases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, late: bool
) -> None:
    from datetime import UTC, datetime, timedelta

    from nexus.api import company_management_read_routes as routes
    from nexus.company.management.action_review_contracts import ActionReview
    from nexus.tests.unit.test_company_auth import token

    f, app = await routed_c(tmp_path, monkeypatch)
    owner = f.owner.identity
    end = [clock_us()]
    if late:
        actual = ActionReview.model_dump_json

        def serialize(value: ActionReview, *, by_alias: bool | None = None) -> str:
            result = actual(value, by_alias=by_alias)
            end[0] += 31_000_000
            return result

        def current(deadline: int) -> None:
            if end[0] >= deadline:
                raise TimeoutError("Original route window expired")

        monkeypatch.setattr(routes, "clock_us", lambda: end[0])
        monkeypatch.setattr(routes, "require_time", current)
        monkeypatch.setattr(ActionReview, "model_dump_json", serialize)
    signed = token(
        {
            "sub": str(owner.principal_id),
            "workspace_id": str(owner.workspace_id),
            "exp": int((datetime.now(UTC) + timedelta(seconds=60)).timestamp()),
        }
    )
    url = f"/api/v2/companies/{f.scope.company_id}/management/actions/{f.row.id}/review"
    async with AsyncTestClient(app, raise_server_exceptions=True) as client:
        response = await client.get(url, headers={"Authorization": "Bearer " + signed})
        if late:
            assert response.status_code == 503
        else:
            assert response.status_code == 200
            body = ActionReview.model_validate_json(response.content)
            assert body.availability == "available" and body.detail is not None
            assert body.detail.proposal_sha256 == f.row.proposal_hash
            assert f.prepared.request.input_text not in response.text
            assert response.headers["cache-control"] == "no-store"
    assert not f.reviews.pending_owners()

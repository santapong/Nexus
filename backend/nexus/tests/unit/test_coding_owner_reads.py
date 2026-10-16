"""Real H files/TinyGit and genuine owner, with explicitly supplied native/source SQL.

Cohesion exception: one full concrete C graph and its native/static deliveries
stay adjacent; no SQL, affordability, model quality or owner acceptance follows.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Event
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID

import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management import action_review_coding as static
from nexus.company.management import action_review_store as generic
from nexus.company.management import coding_prepared_store as protected
from nexus.company.management.action_review_store import OwnerActionReviewStore
from nexus.company.management.coding_intent import PreparedCodingRequest
from nexus.company.management.coding_repository import CodingRepositoryReader
from nexus.company.management.owner_view_sources import SourceDisclosure
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.planning_native_facts import clock_us
from nexus.company.notifications.worker_identity import (
    AuthenticatedWorkerIdentity,
)
from nexus.core.llm.company_pricing import quote_cost
from nexus.execution import coding_owner_reads as module
from nexus.execution.coding_owner_reads import (
    OWNER_INPUT_LIMIT,
    CodingInputReview,
    CodingOwnerReader,
)
from nexus.execution.coding_services import CodingServices
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.authorization_models import ActionAuthority
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CompanyControl, JournalAction
from nexus.tests.unit.coding_runtime_fixture import native_work, services_from_store
from nexus.tests.unit.nexus_report_fixture import credentials
from nexus.tests.unit.test_coding_prepared_store import NativeDelivery, saved_case

STATIC_ID = UUID(int=50001)


@dataclass
class OwnerCase:
    reader: CodingOwnerReader
    services: CodingServices
    reviews: OwnerActionReviewStore
    prepared: PreparedCodingRequest
    owner: AuthenticatedWorkerIdentity
    scope: CompanyControlScope
    native: ExecutionWork
    row: JournalAction
    delivery: NativeDelivery
    session: AsyncSession


async def owner_case(root: Path, monkeypatch: pytest.MonkeyPatch) -> OwnerCase:
    """No fake store/proof: fresh owner stores load actual immutable H files."""
    store, prepared, lease, _, delivery = await saved_case(root, monkeypatch)
    services = services_from_store(
        root, store, prepared, lease, httpx2.MockTransport(lambda _: httpx2.Response(500))
    )
    reader = CodingOwnerReader(services)
    admission = services.management.catalog.nexus_coding_admission
    assert admission is not None and delivery.action is not None
    owner = await credentials(admission.procedure.binding).current(admission.procedure.binding)
    scope = CompanyControlScope(
        company_id=admission.company_id,
        principal_id=owner.identity.principal_id,
        operation_id=UUID(int=50002),
        trace_id=UUID(int=50003),
    )
    # Full quote is descriptive native input, not native spend/affordability proof.
    # The original fixture still declares only0.1USD; real effect remains denied.
    model = services.management.catalog.models.models[1]
    proposal = delivery.action.model_copy(
        update={
            "estimated_cost_usd": quote_cost(
                model.price, prepared.request.bounds, now=datetime.now(UTC)
            ).amount_usd
        }
    )
    delivery.action = proposal
    delivery.control.policy_version = proposal.policy_version
    delivery.control.price_version = proposal.price_version
    work = native_work(services, lease)
    row = JournalAction(
        id=proposal.action_id,
        company_id=proposal.company_id,
        task_id=proposal.task_id,
        trace_id=proposal.trace_id,
        proposal_json=proposal.model_dump_json(),
        proposal_hash=action_hash(proposal),
        approval_json=None,
        state="awaiting_approval",
        consumed_at=None,
    )
    session = delivery.session
    session.in_transaction.return_value = True

    async def get(model_type: type[object], key: object) -> object | None:
        if model_type is JournalAction:
            return row
        if model_type is ExecutionWork:
            return work
        if model_type is ActionAuthority:
            return None
        if model_type is CompanyControl:
            return delivery.control
        raise AssertionError("Unexpected supplied current review metadata query")

    session.get.side_effect = get
    active = [False]

    @asynccontextmanager
    async def tx(
        *args: object, **kwargs: object
    ) -> AsyncIterator[tuple[AsyncSession, CompanyControl, datetime]]:
        assert not active[0], "No nested CC transaction across H private load"
        active[0] = True
        try:
            yield session, delivery.control, datetime.now(UTC)
        finally:
            active[0] = False

    @asynccontextmanager
    async def brain(
        factory: object, scope: BrainReadScope, identity: VerifiedIdentity, *, owner: bool = False
    ) -> AsyncIterator[tuple[AsyncSession, CompanyControl, datetime]]:
        assert not active[0], "Protected H load must happen outside outer CC"
        assert owner and identity == scope_identity
        yield session, delivery.control, datetime.now(UTC)

    scope_identity = owner.identity
    monkeypatch.setattr(generic, "management_owner_transaction", tx)
    monkeypatch.setattr(module, "management_owner_transaction", tx)
    monkeypatch.setattr(protected, "brain_transaction", brain)
    monkeypatch.setattr(
        protected,
        "current_native",
        AsyncMock(side_effect=lambda *args, **kwargs: delivery.native()),
    )
    monkeypatch.setattr(
        ManagementPlanStore,
        "current_binding",
        AsyncMock(side_effect=lambda *args: delivery.native().current.current),
    )
    monkeypatch.setattr(generic, "require_member", AsyncMock())
    monkeypatch.setattr(generic, "require_current_governance", AsyncMock())
    monkeypatch.setattr(generic, "db_clock", AsyncMock(side_effect=lambda _: datetime.now(UTC)))
    monkeypatch.setattr(module, "db_clock", AsyncMock(side_effect=lambda _: datetime.now(UTC)))
    monkeypatch.setattr(static, "db_clock", AsyncMock(side_effect=lambda _: datetime.now(UTC)))
    ref = prepared.sources[0].artifact
    monkeypatch.setattr(
        static,
        "action_resource_symbols",
        AsyncMock(return_value=(proposal.resource, "static.charter")),
    )
    monkeypatch.setattr(
        static, "review_named_artifacts", AsyncMock(return_value=((ref,), (STATIC_ID,)))
    )
    monkeypatch.setattr(
        generic, "review_disclosure", AsyncMock(return_value=SourceDisclosure(None))
    )
    provider = services.identities._credentials
    assert provider is not None
    monkeypatch.setattr(
        provider,
        "credential",
        AsyncMock(side_effect=AssertionError("Owner input borrowed C credential")),
    )
    monkeypatch.setattr(
        CodingRepositoryReader,
        "read",
        AsyncMock(side_effect=AssertionError("Owner input acquired Git")),
    )
    reviews = OwnerActionReviewStore(
        services.factory, services.management.catalog, services.source_views, coding=reader
    )
    return OwnerCase(
        reader, services, reviews, prepared, owner, scope, work, row, delivery, session
    )


async def test_complete_saved_c_input_uses_real_owner_without_actor_or_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = await owner_case(tmp_path, monkeypatch)
    originalstores = tuple(f.services._stores)
    value = await f.reader.read(f.scope, f.owner, f.row.id, end_us=clock_us() + 10_000_000)
    assert value.value.prepared == f.prepared
    assert value.value.proposal_sha256 == f.row.proposal_hash
    assert value.value.reference.header.sha256 == value.value.header_sha256
    assert value.value.model == f.services.management.catalog.models.models[1]
    assert (
        value.value.maximum_reservation_usd
        == quote_cost(
            value.value.model.price, f.prepared.request.bounds, now=datetime.now(UTC)
        ).amount_usd
    )
    assert not value.value.execution_permitted and not value.value.company_completed
    raw = value.value.model_dump_json(by_alias=True).encode()
    assert len(raw) <= OWNER_INPUT_LIMIT and str(tmp_path).encode() not in raw
    assert not f.reader.pending_owners() and tuple(f.services._stores) == originalstores
    # A fresh next request creates its own unstopped store, not a reset old one.
    again = await f.reader.read(f.scope, f.owner, f.row.id, end_us=clock_us() + 10_000_000)
    assert again.value == value.value
    assert not f.reader.pending_owners()


@pytest.mark.parametrize("fault", ["source", "head", "hash", "body", "witness", "reader"])
async def test_current_source_native_or_owner_splices_never_disclose_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    f = await owner_case(tmp_path, monkeypatch)
    if fault == "source":
        monkeypatch.setattr(generic, "review_disclosure", AsyncMock(return_value=None))
    elif fault == "head":
        monkeypatch.setattr(ManagementPlanStore, "current_binding", AsyncMock(return_value=None))
    elif fault == "hash":
        f.row.proposal_hash = "f" * 64
    elif fault == "body":
        from nexus.company.management.coding_prepared_contracts import (
            decode_header,
            prepared_reference,
        )

        assert f.delivery.action is not None
        reference = prepared_reference(f.delivery.action)
        raw = await f.services.prepared_blobs.read(reference.header)
        path = f.services.prepared_blobs._path(decode_header(raw, reference).body)
        path.chmod(0o600)
        path.write_bytes(b"{}\n")
        path.chmod(0o400)
    elif fault == "reader":
        object.__setattr__(f.reader, "services", object())
    owner = f.owner
    if fault == "witness":
        owner = cast(
            AuthenticatedWorkerIdentity, f.owner.identity
        )  # Deliberately wrong runtime type.
    with pytest.raises((ValueError, OSError, AttributeError)):
        await f.reader.read(f.scope, owner, f.row.id, end_us=clock_us() + 10_000_000)


async def test_first_static_window_cannot_refresh_after_actual_private_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = await owner_case(tmp_path, monkeypatch)
    first = datetime.now(UTC) + timedelta(seconds=0.08)
    calls = []

    async def disclosure(*args: object) -> SourceDisclosure:
        calls.append(1)
        return SourceDisclosure(
            first if len(calls) == 1 else datetime.now(UTC) + timedelta(seconds=5)
        )

    monkeypatch.setattr(generic, "review_disclosure", disclosure)
    actual = f.services.prepared_blobs.read

    async def delayed(ref: ArtifactRevisionRef) -> bytes:
        await asyncio.sleep(0.15)
        return await actual(ref)

    monkeypatch.setattr(f.services.prepared_blobs, "read", delayed)
    try:
        with pytest.raises(TimeoutError):
            await f.reader.read(f.scope, f.owner, f.row.id, end_us=clock_us() + 10_000_000)
    finally:
        for task in f.reader.pending_owners():
            with suppress(ValueError, TimeoutError):
                await asyncio.shield(task)  # Resource errors never become adopted input.
    assert calls and not f.reader.pending_owners()


async def test_full_input_alias_serialization_cannot_outlive_loaded_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = await owner_case(tmp_path, monkeypatch)
    from nexus.company.management import planning_native_facts

    original = CodingInputReview.model_dump_json
    end = clock_us() + 10_000_000

    def late(value: CodingInputReview, *, by_alias: bool | None = None) -> str:
        result = original(value, by_alias=by_alias)
        monkeypatch.setattr(planning_native_facts, "clock_us", lambda: end)
        return result

    monkeypatch.setattr(CodingInputReview, "model_dump_json", late)
    with pytest.raises(TimeoutError):
        await f.reader.read(f.scope, f.owner, f.row.id, end_us=end)
    assert not f.reader.pending_owners()


async def test_cancel_retains_real_private_leaf_and_only_stops_its_own_read_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nexus.company.brain.blob_store import ProtectedBlobStore

    f = await owner_case(tmp_path, monkeypatch)
    other = f.services.create_prepared()
    actual = ProtectedBlobStore._read
    entered, finish = Event(), Event()

    def slow(path: Path) -> bytes:
        entered.set()
        assert finish.wait(4)
        return actual(path)

    monkeypatch.setattr(ProtectedBlobStore, "_read", staticmethod(slow))
    run = asyncio.create_task(
        f.reader.read(f.scope, f.owner, f.row.id, end_us=clock_us() + 10_000_000)
    )
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        run.cancel()
        with pytest.raises(asyncio.CancelledError):
            await run
        assert f.reader.pending_owners() and f.services.pending_owners()
        assert not other._stopped
    finally:
        finish.set()
        owners = f.reader.pending_owners()
        if owners:
            await asyncio.wait(owners, timeout=4)
    assert not f.reader.pending_owners()
    assert f.services._stores == [other] and not other._stopped


async def test_complete_input_bound_and_exact_native_quote_are_not_truncated_or_invented(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = await owner_case(tmp_path, monkeypatch)
    actual = CodingInputReview.model_dump_json

    def oversized(value: CodingInputReview, *, by_alias: bool | None = None) -> str:
        return actual(value, by_alias=by_alias) + (" " * OWNER_INPUT_LIMIT)

    monkeypatch.setattr(CodingInputReview, "model_dump_json", oversized)
    with pytest.raises(ValueError, match="byte bound"):
        await f.reader.read(f.scope, f.owner, f.row.id, end_us=clock_us() + 10_000_000)
    monkeypatch.setattr(CodingInputReview, "model_dump_json", actual)
    assert f.delivery.action is not None
    proposal = f.delivery.action.model_copy(update={"estimated_cost_usd": Decimal("0.1")})
    from nexus.company.contracts.actions import ActionProposal

    proposal = ActionProposal.model_validate_json(proposal.model_dump_json())
    f.delivery.action = proposal
    f.row.proposal_json = proposal.model_dump_json()
    f.row.proposal_hash = action_hash(proposal)
    with pytest.raises(ValueError, match="financial proof"):
        await f.reader.read(f.scope, f.owner, f.row.id, end_us=clock_us() + 10_000_000)
    assert not f.reader.pending_owners()

"""Actual TinyGit/private files; native SQL delivery is supplied, never DB admission proof.

Cohesion exception: one complete C repository/context fixture is shared with the
consumer forward so source bytes do not become a fake material DTO permission.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from threading import Event
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.builder.contracts import RepositoryPin
from nexus.company.brain.base import SourceTime
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.context import ContextLimits
from nexus.company.brain.context_render import render_context
from nexus.company.brain.retrieval import MaterializedEvidence
from nexus.company.brain.sources import SourceHead
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.coding_content import coding_schema
from nexus.company.management.coding_intent import PreparedCodingRequest, prepare_coding_request
from nexus.company.management.coding_prepared_checks import CodingNative, conditions
from nexus.company.management.coding_prepared_contracts import (
    StoredCodingRequest,
    encode_prepared,
    header_for,
    header_reference,
    repository_selection,
)
from nexus.company.management.coding_prepared_store import CodingPreparedStore
from nexus.company.management.coding_repository import CodingRepositoryReader
from nexus.company.management.owner_view_sources import OwnerViewSources
from nexus.company.management.plan_catalog import PlanAdmissionCatalog
from nexus.company.management.plan_registration import registration
from nexus.company.management.plan_support import CurrentPlanBinding
from nexus.company.management.planning_native_facts import clock_us
from nexus.company.management.planning_prepared_checks import NativePrepared
from nexus.company.management.transactions import ManagementDeniedError
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_support import registration_digest
from nexus.harness.journal_models import CompanyControl, JournalAction
from nexus.harness.model_authorizer_contracts import model_action_parameters
from nexus.harness.model_input_estimator import FullContextInputEstimator
from nexus.tests.unit.test_coding_intent import prepared_case, runtime_graph, witness
from nexus.tests.unit.test_company_brain_context_render import material
from nexus.tests.unit.test_native_builder_snapshot import git


def repository_case(
    root: Path,
) -> tuple[
    PreparedCodingRequest, PlanAdmissionCatalog, FullContextInputEstimator, ExecutionLease, Path
]:
    """Actual temporary Git proof plus actual renderer/whole proof, synthetic native catalog."""
    prepared, catalog, estimator, lease = prepared_case()
    repo = root / "repository"
    repo.mkdir(mode=0o700)
    git(repo, "init", "-q")
    for old_file, raw in zip(prepared.sources, (b"old\n", b"fixed\n"), strict=True):
        path = repo / old_file.file.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    git(repo, "add", "src/app.py", "tests/test_app.py")
    git(
        repo,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "coding prepared fixture",
    )
    commit = git(repo, "rev-parse", "HEAD").decode().strip()
    event = SourceTime(
        precision="instant",
        value=git(repo, "show", "-s", "--format=%cI", commit).decode().strip(),
        basis="Actual temporary fixture commit",
    )
    pin = RepositoryPin(
        repository_symbol="nexus.fixture",
        commit=commit,
        tree=git(repo, "rev-parse", "HEAD^{tree}").decode().strip(),
        archive_sha256=hashlib.sha256(git(repo, "archive", "--format=tar", commit)).hexdigest(),
    )
    materials: list[MaterializedEvidence] = []
    sources = []
    for index, old in enumerate(prepared.sources):
        row = material("old\n" if index == 0 else "fixed\n", identifier=40 + 10 * index)
        source = old.source.model_copy(update={"revision": commit})
        record = row.record.model_copy(
            update={
                "company_id": prepared.request.company_id,
                "source": source,
                "artifact": old.artifact,
                "source_event": event,
            }
        )
        row = row.model_copy(
            update={
                "company_id": prepared.request.company_id,
                "record": record,
                "external_key": old.git.external_key,
                "source_contributors": (source,),
                "contributors": tuple(
                    value.model_copy(update={"company_id": prepared.request.company_id})
                    for value in row.contributors
                ),
            }
        )
        materials.append(row)
        sources.append(
            old.model_copy(
                update={
                    "source": source,
                    "git": old.git.model_copy(
                        update={
                            "commit": commit,
                            "git_blob": git(repo, "rev-parse", f"HEAD:{old.git.path}")
                            .decode()
                            .strip(),
                            "source_event": event,
                        }
                    ),
                }
            )
        )
    heads = tuple(
        SourceHead(
            company_id=prepared.request.company_id,
            source_id=row.record.source.source_id,
            current=row.record.source,
            generation=1,
            observed_at=datetime.now(UTC),
            availability="available",
        )
        for row in materials
    )
    context = render_context(
        prepared.scope,
        prepared.context.manifest.authority,
        ContextLimits(policy_version="context-v1"),
        tuple(materials),
        heads,
        question="Implement the cited change",
        purposes={row.record.evidence_id: "workspace" for row in materials},
    )
    binding = prepared.binding.model_copy(
        update={"source": pin, "context_manifest_sha256": canonical_sha256(context.manifest)}
    )
    call = prepared.request.model_copy(
        update={
            "input_text": context.input_text,
            "system_text": context.system_text,
            "output_schema": coding_schema(binding, manifest=context.manifest),
        }
    )
    prepared = prepare_coding_request(
        call,
        context,
        binding,
        scope=prepared.scope,
        sources=tuple(sources),
        input_recipe=prepared.input_recipe,
        catalog=catalog,
        input_estimator=estimator,
    )
    (repo / "src/app.py").write_text("dirty checkout must not enter prepared input")
    return prepared, catalog, estimator, lease, repo


def store_case(root: Path) -> tuple[CodingPreparedStore, PreparedCodingRequest, ExecutionLease]:
    prepared, catalog, _, lease, repo = repository_case(root)
    factory, management, contexts = runtime_graph(root, prepared, catalog)
    return (
        CodingPreparedStore(
            factory,
            management,
            contexts,
            ProtectedBlobStore(root / "prepared", storage_symbol="coding.prepared.fixture"),
            OwnerViewSources(management.artifacts, management.freshness),
            prepared.input_recipe,
            CodingRepositoryReader(repo, repository_selection(prepared)),
        ),
        prepared,
        lease,
    )


class NativeDelivery:
    """Only native SQL delivery is supplied; concrete storage/repository/check sequence runs."""

    def __init__(self, store: CodingPreparedStore, prepared: PreparedCodingRequest) -> None:
        self.store, self.prepared = store, prepared
        self.action: ActionProposal | None = None
        self.events: list[str] = []
        self.session = AsyncMock(spec=AsyncSession)
        self.session.get.side_effect = lambda model, key: JournalAction(
            id=prepared.request.action_id,
            company_id=prepared.request.company_id,
            task_id=prepared.request.task_id,
        )
        admission = store.management.catalog.nexus_coding_admission
        assert admission is not None
        slot = admission.slots[1]
        self.registration_sha = registration_digest(
            registration(slot.child.binding, slot.work, slot.child.quota)
        )
        self.control = CompanyControl(
            company_id=prepared.request.company_id,
            owner_id=admission.procedure.binding.actor_id,
            paused=False,
        )

    def native(self) -> CodingNative:
        admission = self.store.management.catalog.nexus_coding_admission
        assert admission is not None
        slot = admission.slots[1]
        return CodingNative(
            NativePrepared(
                self.control.owner_id,
                self.registration_sha,
                self.prepared.binding.run_id,
                self.prepared.binding.goal,
                CurrentPlanBinding(
                    company_id=admission.company_id,
                    plan=self.prepared.binding.plan,
                    child=slot.child,
                    work=slot.work,
                    work_sha256=self.registration_sha,
                    procedure_id=admission.procedure.procedure_id,
                ),
                self.action,
                "b" * 64 if self.action else None,
            ),
            "c" * 64,
        )

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from nexus.company.management import coding_prepared_store as module

        @asynccontextmanager
        async def transaction(
            *args: object, **kwargs: object
        ) -> AsyncIterator[tuple[AsyncSession, CompanyControl, None]]:
            self.events.append("native")
            yield self.session, self.control, None

        async def current(*args: object, **kwargs: object) -> CodingNative:
            return self.native()

        monkeypatch.setattr(module, "brain_transaction", transaction)
        monkeypatch.setattr(self.store, "_native", current)
        monkeypatch.setattr(module, "source_read", AsyncMock(return_value=()))
        monkeypatch.setattr(module, "action_sources", AsyncMock(return_value=("d" * 64, ())))
        monkeypatch.setattr(module, "db_now", AsyncMock(side_effect=lambda _: datetime.now(UTC)))

    def publish(self, reference: object) -> None:
        admission = self.store.management.catalog.nexus_coding_admission
        assert admission is not None
        raw, body = encode_prepared(self.prepared)
        header = header_for(
            self.prepared,
            body,
            owner_id=self.control.owner_id,
            registration_sha256=self.registration_sha,
            root_task_id=admission.procedure.binding.task_id,
            root_run_id=admission.procedure.binding.run_id,
            root_registration_sha256="c" * 64,
            procedure_id=admission.procedure.procedure_id,
        )
        assert header_reference(header)[0] == reference and raw
        self.action = ActionProposal(
            company_id=self.prepared.request.company_id,
            action_id=self.prepared.request.action_id,
            task_id=self.prepared.request.task_id,
            trace_id=self.prepared.request.trace_id,
            actor_id=self.prepared.request.actor_id,
            revision=1,
            policy_version=self.prepared.context.manifest.authority.policy_version,
            tool="model.request.v1",
            tool_version="v1",
            resource=f"model:{self.prepared.request.registry_id}",
            parameters=model_action_parameters(self.prepared.request, self.prepared.input_recipe),
            preconditions=conditions(header),
            estimated_cost_usd="0.1",
            price_version=self.prepared.request.price_version,
        )


async def saved_case(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[
    CodingPreparedStore,
    PreparedCodingRequest,
    ExecutionLease,
    AuthenticatedWorkerIdentity,
    NativeDelivery,
]:
    store, prepared, lease = store_case(root)
    credential = await witness(prepared)
    delivery = NativeDelivery(store, prepared)
    delivery.install(monkeypatch)
    reference = await store.save_worker(lease, credential, prepared, end_us=clock_us() + 20_000_000)
    delivery.publish(reference)
    return store, prepared, lease, credential, delivery


async def test_actual_repo_before_write_and_store_issued_worker_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, prepared, lease, credential, _ = await saved_case(tmp_path, monkeypatch)
    loaded = await store.load_worker(
        lease, credential, prepared.request.action_id, end_us=clock_us() + 10_000_000
    )
    store.require_loaded(
        loaded, credential, ExecutionLease.model_validate_json(lease.model_dump_json())
    )
    assert loaded.prepared == prepared
    assert loaded.read_end_us <= clock_us() + 10_000_000
    assert store.pending_owners() == ()
    duplicate = StoredCodingRequest(
        loaded.prepared, loaded.reference, loaded.header, loaded.read_end_us
    )
    with pytest.raises(ValueError):
        store.require_loaded(duplicate, credential, lease)
    with pytest.raises(ValueError):
        store.require_loaded(loaded, await witness(prepared), lease)
    assert os.stat(store.blobs._path(loaded.reference.header)).st_mode & 0o777 == 0o400


async def test_actor_read_never_satisfies_worker_proof_and_locked_gate_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, prepared, lease, credential, delivery = await saved_case(tmp_path, monkeypatch)
    loaded = await store.load_actor(
        prepared.scope, credential, prepared.request.action_id, end_us=clock_us() + 10_000_000
    )
    store.require_loaded(loaded, credential, None, mode="actor")
    await store.validate_loaded_locked(
        delivery.session,
        delivery.control,
        prepared.scope,
        loaded,
        credential,
        None,
        mode="actor",
        now=datetime.now(UTC),
    )
    with pytest.raises(ValueError):
        store.require_loaded(loaded, credential, lease)
    delivery.action = (
        delivery.action.model_copy(update={"parameters": {}}) if delivery.action else None
    )
    with pytest.raises(ValueError):
        await store.validate_loaded_locked(
            delivery.session,
            delivery.control,
            prepared.scope,
            loaded,
            credential,
            None,
            mode="actor",
            now=datetime.now(UTC),
        )


async def test_unavailable_repository_never_writes_or_returns_preparation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, prepared, lease = store_case(tmp_path)
    credential = await witness(prepared)
    NativeDelivery(store, prepared).install(monkeypatch)
    # Exact actual archive pin is wrong; actual repository reader denies, no fake reader.
    (store.repository._repository / ".git" / "HEAD").unlink()
    with pytest.raises(ValueError):
        await store.save_worker(lease, credential, prepared, end_us=clock_us() + 10_000_000)
    assert not store.blobs._root.exists()


@pytest.mark.parametrize("fault", ["body", "mode", "symlink", "native"])
async def test_actual_private_or_native_replacement_denies_without_worker_seal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    store, prepared, lease, credential, delivery = await saved_case(tmp_path, monkeypatch)
    assert delivery.action is not None
    from nexus.company.management.coding_prepared_contracts import prepared_reference

    reference = prepared_reference(delivery.action)
    if fault == "native":
        delivery.action = delivery.action.model_copy(update={"parameters": {}})
    else:
        header_path = store.blobs._path(reference.header)
        if fault == "mode":
            header_path.chmod(0o600)
        elif fault == "symlink":
            header_path.unlink()
            header_path.symlink_to(tmp_path / "missing")
        else:
            header_path.chmod(0o600)
            header_path.write_bytes(b"{}\n")
            header_path.chmod(0o400)
    with pytest.raises((ValueError, OSError)):
        await store.load_worker(
            lease, credential, prepared.request.action_id, end_us=clock_us() + 10_000_000
        )
    assert not store._issued


@pytest.mark.parametrize("stop", ["cancel", "timeout"])
async def test_actual_blob_leaf_remains_owned_and_late_save_is_not_adopted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stop: str
) -> None:
    store, prepared, lease = store_case(tmp_path)
    credential = await witness(prepared)
    NativeDelivery(store, prepared).install(monkeypatch)
    original = store.blobs._owned
    entered, release = Event(), Event()

    async def delayed[T](call: Callable[[], T]) -> T:
        def held() -> T:
            entered.set()
            release.wait(3)
            return call()

        return await original(held)

    monkeypatch.setattr(store.blobs, "_owned", delayed)
    task = asyncio.create_task(
        store.save_worker(
            lease,
            credential,
            prepared,
            end_us=clock_us() + (300_000 if stop == "timeout" else 10_000_000),
        )
    )
    try:
        while not entered.is_set():
            await asyncio.sleep(0.005)
        if stop == "cancel":
            task.cancel()
        with pytest.raises(asyncio.CancelledError if stop == "cancel" else TimeoutError):
            await task
        assert store.pending_owners()
        assert not store._issued
    finally:
        release.set()
        # Stopped pipelines now deny their next phase; an admitted leaf may still
        # complete. Observe both without cancelling leaves or hiding other errors.
        results = await asyncio.gather(
            *(asyncio.shield(owner) for owner in store.pending_owners()), return_exceptions=True
        )
        for result in results:
            if isinstance(result, BaseException):
                if stop == "cancel":
                    assert isinstance(result, ManagementDeniedError)
                    assert str(result) == "Original prepared IO stopped admission"
                else:
                    assert isinstance(result, TimeoutError)
    assert not store.pending_owners()
    assert not store._issued
    assert store._stopped


async def test_historical_owner_header_read_never_borrows_c_credential_or_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Actual header file and actual owner JWT; native/history delivery is supplied."""
    from datetime import timedelta
    from uuid import UUID

    from nexus.company.access import CompanyControlScope
    from nexus.company.contracts.actions import ApprovalDecision
    from nexus.company.management import coding_prepared_history as history
    from nexus.company.management import cycle_model_reader as finance
    from nexus.company.management.cycle_cost_contracts import DirectoryCostWork, NativeCostSelection
    from nexus.company.management.plan_models import ManagementPlanRevision
    from nexus.company.management.plan_registration import registration
    from nexus.execution.runtime_contracts import ExecutionSnapshot
    from nexus.execution.runtime_support import registration_digest
    from nexus.harness.canonical import action_hash
    from nexus.harness.journal_contracts import ActionRecord
    from nexus.harness.lifecycle import ActionState
    from nexus.harness.limits import LoopCounters
    from nexus.tests.unit.nexus_report_fixture import credentials
    from nexus.tests.unit.test_nexus_coding_admission import planning_origin

    store, prepared, _, _, delivery = await saved_case(tmp_path, monkeypatch)
    admission = store.management.catalog.nexus_coding_admission
    assert admission is not None and delivery.action is not None
    owner = await credentials(admission.procedure.binding).current(admission.procedure.binding)
    scope = CompanyControlScope(
        company_id=admission.company_id,
        principal_id=owner.identity.principal_id,
        operation_id=UUID(int=9001),
        trace_id=UUID(int=9002),
    )
    slot, now = admission.slots[1], datetime.now(UTC)
    registered = registration(slot.child.binding, slot.work, slot.child.quota)
    header = header_for(
        prepared,
        encode_prepared(prepared)[1],
        owner_id=owner.identity.principal_id,
        registration_sha256="a" * 64,
        root_task_id=admission.procedure.binding.task_id,
        root_run_id=admission.procedure.binding.run_id,
        root_registration_sha256="c" * 64,
        procedure_id=admission.procedure.procedure_id,
    )
    # Supplied saved native registration hash must be the real registration digest.
    header = header.model_copy(update={"registration_sha256": registration_digest(registered)})
    ref, raw = header_reference(header)
    await store._io._save(ref.header, raw, clock_us() + 10_000_000)
    action = delivery.action.model_copy(update={"preconditions": conditions(header)})
    zero = LoopCounters(model_requests=0, tool_attempts=0, rework_rounds=0, plan_revisions=0)
    work = ExecutionSnapshot(
        company_id=admission.company_id,
        registration=registered,
        workspace_id=slot.child.binding.workspace_id,
        actor_id=slot.child.binding.actor_id,
        parent_task_id=admission.procedure.binding.task_id,
        state="verifying",
        counters=zero,
        delegated=zero,
        fence=2,
        worker_id=None,
        lease_principal_id=None,
        expires_at=None,
        segment_number=1,
        segment_id=UUID(int=9003),
        waiting_action_id=None,
    )
    selected = NativeCostSelection(
        directory=DirectoryCostWork(
            company_id=admission.company_id,
            task_id=slot.work.task_id,
            trace_id=slot.work.trace_id,
            actor_id=slot.child.binding.actor_id,
            workspace_id=slot.child.binding.workspace_id,
            parent_task_id=admission.procedure.binding.task_id,
            root_task_id=admission.procedure.binding.task_id,
            allocation_usd=slot.child.allocation_usd,
            delegated_usd=Decimal(0),
            active=False,
            work=work,
        ),
        action=ActionRecord(
            company_id=admission.company_id,
            proposal=action,
            proposal_hash=action_hash(action),
            approval=ApprovalDecision(
                company_id=admission.company_id,
                decision_id=UUID(int=9004),
                action_id=action.action_id,
                action_revision=1,
                action_hash=action_hash(action),
                approver_id=owner.identity.principal_id,
                decision="approved",
                issued_at=now - timedelta(hours=1),
                expires_at=now - timedelta(minutes=1),
            ),
            state=ActionState.AUTHORIZED,
            consumed_at=now - timedelta(minutes=2),
        ),
        hold=None,
        intent=None,
        attempt=None,
    )
    payload = admission.payload("execution", origin=planning_origin(admission))
    original_plan = ManagementPlanRevision(
        company_id=admission.company_id,
        plan_id=header.plan.plan_id,
        plan_revision_id=header.plan.plan_revision_id,
        revision=header.plan.revision,
        sha256=header.plan.sha256,
        snapshot_json=payload.model_dump_json(),
        proposed_by=owner.identity.principal_id,
        recorded_at=now,
    )
    session = AsyncMock(spec=AsyncSession)
    session.get.return_value = original_plan

    @asynccontextmanager
    async def transaction(
        *args: object, **kwargs: object
    ) -> AsyncIterator[tuple[AsyncSession, CompanyControl, None]]:
        yield session, delivery.control, None

    monkeypatch.setattr(history, "management_owner_transaction", transaction)
    monkeypatch.setattr(finance, "native_cost_selection", AsyncMock(return_value=selected))
    monkeypatch.setattr(finance, "stored_coding_profile", AsyncMock(return_value=True))
    monkeypatch.setattr(history, "root_registration", AsyncMock(return_value="c" * 64))
    monkeypatch.setattr(history, "action_sources", AsyncMock(return_value=("d" * 64, ())))
    monkeypatch.setattr(history, "require_code_metadata", AsyncMock())
    monkeypatch.setattr(history, "db_now", AsyncMock(side_effect=lambda _: datetime.now(UTC)))
    monkeypatch.setattr(
        store,
        "_native",
        AsyncMock(side_effect=AssertionError("Historical read required current C/Goal/head")),
    )
    monkeypatch.setattr(
        store.repository,
        "read",
        AsyncMock(side_effect=AssertionError("Historical read borrowed C repository access")),
    )
    actual_read = store._io._read

    async def metadata_only(reference: object, end: int) -> bytes:
        assert reference == ref.header
        return await actual_read(ref.header, end)

    monkeypatch.setattr(store._io, "_read", metadata_only)
    result = await store.read_history_header(
        scope, owner, action.action_id, end_us=clock_us() + 5_000_000
    )
    assert result.header == header and result.reference == ref
    assert result.source_signature == "d" * 64
    assert not store._issued

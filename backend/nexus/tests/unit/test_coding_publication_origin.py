"""Actual protected J files with supplied SQL; not native admission or physical proof.

Cohesion exception: the real J/H/Git/protected-file graph and its closed SQL-leaf
adapter stay with the native/source/first-window/cancel-page cases that use them.
No fixture module or permission callback is added to production.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.coding_intent import PreparedCodingRequest
from nexus.company.management.coding_publication_origin import CodingPublicationOriginReader
from nexus.company.management.owner_view_sources import OwnerViewSources
from nexus.harness.journal_models import CompanyControl
from nexus.tests.unit.coding_publication_fixture import graph


async def test_native_publication_template_accepts_admitted_title_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nexus.company.management.coding_publication_origin_native import require_c_native
    from nexus.tests.unit.coding_publication_fixture import native_files

    value = await native_files(tmp_path, monkeypatch)
    reader = CodingPublicationOriginReader(
        value.private.factory,
        value.catalog,
        value.private.sources.artifacts,
        value.private.sources.freshness,
        rules=value.rules,
        recipe=value.prepared.input_recipe,
    )
    native = value.native.directory.work
    assert native is not None
    actual = native.registration.work.model_copy(update={"title": "Model proposed coder"})
    selected = value.native.model_copy(
        update={
            "directory": value.native.directory.model_copy(
                update={
                    "work": native.model_copy(
                        update={
                            "registration": native.registration.model_copy(update={"work": actual})
                        }
                    )
                }
            )
        }
    )
    require_c_native(reader, selected, value.owner.identity.principal_id)
    assert selected.directory.work.registration.work == actual


async def test_origin_requires_exact_shared_concrete_source_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = await graph(tmp_path)
    reader = CodingPublicationOriginReader(
        value.private.factory,
        value.catalog,
        value.private.sources.artifacts,
        value.private.sources.freshness,
        rules=value.rules,
        recipe=value.prepared.input_recipe,
    )
    reader.require_composition()
    monkeypatch.setattr(reader.artifacts, "factory", object())
    with pytest.raises(ValueError):
        reader.require_composition()


async def origin_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Real J/H/Git/protected blobs; only authority/native SQL leaves are supplied.

    The held synthetic C slice remains underfunded; no admission/quality/DB proof.
    """
    from collections.abc import AsyncIterator
    from contextlib import asynccontextmanager
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from uuid import UUID

    from sqlalchemy import Select

    from nexus.builder.contracts import BuilderJobSpec, BuilderLimits, CommandRef
    from nexus.builder.execution_contracts import BuilderExecutionSpec
    from nexus.builder.execution_method import CONTAINED_EXECUTION_METHOD_SHA256
    from nexus.builder.policy import BuilderCommandPolicy, BuilderToolPolicy
    from nexus.builder.runtime_identity import RUNTIME_V2, RUNTIME_V2_METHOD_SHA256
    from nexus.company.brain.access_models import BrainResourceAccess
    from nexus.company.brain.access_support import require_resources
    from nexus.company.brain.artifact_store import _Snapshot
    from nexus.company.brain.retrieval_records import heads
    from nexus.company.brain.source_models import (
        BrainArtifactRevision,
        BrainSourceHead,
        BrainSourceRevision,
    )
    from nexus.company.brain.sources import ArtifactRevisionRef
    from nexus.company.contracts.actions import ActionProposal
    from nexus.company.management import coding_publication_origin as reader_module
    from nexus.company.management import coding_publication_origin_native as native_module
    from nexus.company.management.canonical import canonical_sha256
    from nexus.company.management.plan_store import ManagementPlanStore
    from nexus.execution.runtime_contracts import ExecutionLease
    from nexus.execution.runtime_models import ExecutionWork
    from nexus.harness.canonical import action_hash
    from nexus.harness.journal_models import JournalAction
    from nexus.tests.unit.coding_publication_fixture import supplied_case
    from nexus.tests.unit.nexus_report_fixture import credentials
    from nexus.tests.unit.test_coding_publication import publish

    value = await supplied_case(tmp_path, monkeypatch)
    published = (await publish(value)).value
    slot = value.catalog.nexus_coding_admission.slots[5]
    bound = slot.child.binding
    credential = await credentials(bound).current(bound)
    lease = ExecutionLease.model_validate(
        value.lease.model_dump()
        | {
            "task_id": bound.task_id,
            "trace_id": bound.trace_id,
            "actor_id": bound.actor_id,
            "workspace_id": bound.workspace_id,
            "run_id": bound.run_id,
            "expires_at": datetime.now(UTC) + timedelta(seconds=20),
        }
    )
    policy = BuilderToolPolicy(
        company_id=bound.company_id,
        policy_symbol="nexus.component.v1",
        resource_symbol=slot.tool.resource,
        repository_symbol=value.prepared.binding.source.repository_symbol,
        image="registry.example/nexus@sha256:" + "a" * 64,
        commands=(
            BuilderCommandPolicy(
                command_key="unit", argv=("python", "-m", "pytest"), directory="."
            ),
        ),
        write_paths=value.prepared.binding.allowed_write_paths,
        artifact_paths=("checks",),
        runtime_recipe=RUNTIME_V2,
        runtime_method_sha256=RUNTIME_V2_METHOD_SHA256,
        full_execution_method_sha256=CONTAINED_EXECUTION_METHOD_SHA256,
    )
    job = BuilderJobSpec(
        company_id=bound.company_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        run_id=bound.run_id,
        workspace_id=bound.workspace_id,
        actor_id=bound.actor_id,
        action_id=UUID(int=17001),
        policy_symbol=policy.policy_symbol,
        resource_symbol=policy.resource_symbol,
        architecture="amd64",
        source=value.prepared.binding.source,
        patch_sha256=published.patch.artifact.sha256,
        write_paths=policy.write_paths,
        artifact_paths=policy.artifact_paths,
        commands=(
            CommandRef(command_key="unit", phase="baseline"),
            CommandRef(command_key="unit", phase="post"),
        ),
        limits=BuilderLimits(),
    )
    target = next(
        row.resource for row in value.catalog.resources if row.symbol == slot.tool.resource
    )
    spec = BuilderExecutionSpec(
        job=job,
        policy_sha256=canonical_sha256(policy),
        runtime_recipe=RUNTIME_V2,
        protected_patch=published.patch.artifact,
        output_resource=target,
    )
    proposal = ActionProposal.model_validate(
        value.native.action.proposal.model_dump()
        | {
            "action_id": job.action_id,
            "task_id": bound.task_id,
            "trace_id": bound.trace_id,
            "actor_id": bound.actor_id,
            "tool": "company.builder.run.v1",
            "resource": slot.tool.resource,
            "parameters": spec.model_dump(mode="json"),
            "preconditions": (),
        }
    )
    action = JournalAction(
        id=job.action_id,
        company_id=job.company_id,
        task_id=job.task_id,
        trace_id=job.trace_id,
        proposal_json=proposal.model_dump_json(),
        proposal_hash=action_hash(proposal),
        state="authorized",
    )
    value.memory.add(action)
    work = ExecutionWork(company_id=job.company_id, task_id=job.task_id)
    resources = {
        row.resource_id for row in value.memory.rows if isinstance(row, BrainResourceAccess)
    }
    for resource in resources:
        value.memory.add(
            BrainResourceAccess(
                company_id=job.company_id,
                resource_id=resource,
                principal_id=bound.actor_id,
                active=True,
                generation=1,
                expires_at=None,
            )
        )

    @asynccontextmanager
    async def transaction(
        *args: object, **kwargs: object
    ) -> AsyncIterator[tuple[AsyncSession, CompanyControl, datetime]]:
        assert not value.memory.inside
        value.memory.inside = True
        try:
            yield value.memory.session, value.control, datetime.now(UTC)
        finally:
            value.memory.inside = False

    for name in (
        "nexus.company.brain.artifact_store",
        "nexus.company.management.acceptance_freshness",
        "nexus.builder.engineering_bodies",
    ):
        monkeypatch.setattr(name + ".brain_transaction", transaction)
    monkeypatch.setattr(reader_module, "brain_transaction", transaction)
    monkeypatch.setattr("nexus.company.brain.artifact_store.revalidate_brain_scope", AsyncMock())
    monkeypatch.setattr(native_module, "execution_row", AsyncMock(return_value=work))
    monkeypatch.setattr(native_module, "require_lease", lambda *a, **k: None)
    monkeypatch.setattr(native_module, "require_management_execution", AsyncMock())
    monkeypatch.setattr(
        native_module, "native_cost_selection", AsyncMock(side_effect=lambda *_: value.native)
    )
    monkeypatch.setattr(
        native_module,
        "root_registration",
        AsyncMock(return_value=value.loaded.header.root_registration_sha256),
    )
    monkeypatch.setattr(
        ManagementPlanStore,
        "current_binding",
        AsyncMock(
            return_value=SimpleNamespace(
                plan=value.loaded.header.plan, work=value.native.directory.work.registration.work
            )
        ),
    )
    monkeypatch.setattr(reader_module, "execution_row", AsyncMock(return_value=work))

    async def snapshot(
        session: AsyncSession,
        scope: BrainReadScope,
        key: UUID,
        now: datetime,
        include_history: bool,
    ) -> _Snapshot:
        assert not include_history and scope.principal_id == credential.identity.principal_id
        artifact = await value.memory.get(BrainArtifactRevision, (scope.company_id, key))
        assert artifact
        refs = [row.current for row in value.loaded.header.source_heads]
        own = (
            (published.origin.source,)
            if key == published.origin.artifact.artifact_revision_id
            else (published.origin.source, published.patch.source)
            if key == published.patch.artifact.artifact_revision_id
            else ()
        )
        refs.extend(own)
        required = {row.resource_id for row in value.loaded.header.contributors}
        if own:
            required.add(value.rules.origin.resource.resource_id)
        if len(own) == 2:
            required.add(value.rules.patch.resource.resource_id)
        grants = await require_resources(session, scope, tuple(sorted(required)), now)
        current = await heads(session, scope, tuple(refs))
        return _Snapshot(
            ArtifactRevisionRef(
                **{
                    k: getattr(artifact, k)
                    for k in ArtifactRevisionRef.model_fields
                    if k != "schema_version"
                }
            ),
            artifact.raw_text,
            tuple(refs),
            grants,
            current,
            artifact.data_classification,
            False,
        )

    original_execute = value.memory.execute

    async def execute(statement: Select[tuple[object, ...]]) -> SimpleNamespace:
        descriptions = statement.column_descriptions
        if len(descriptions) == 2 and descriptions[0]["entity"] is BrainSourceHead:
            return SimpleNamespace(
                all=lambda: [
                    (head, rev)
                    for head in value.memory.selected(statement, BrainSourceHead)
                    for rev in value.memory.rows
                    if isinstance(rev, BrainSourceRevision)
                    and rev.source_revision_id == head.current_revision_id
                ]
            )
        result = await original_execute(statement)
        assert isinstance(result, SimpleNamespace)
        return result

    monkeypatch.setattr(value.memory.session, "execute", AsyncMock(side_effect=execute))

    async def closure(
        session: AsyncSession, scope: BrainReadScope, refs: tuple[ArtifactRevisionRef, ...]
    ) -> tuple[tuple[UUID, ...], tuple[UUID, ...]]:
        values = [
            await snapshot(session, scope, ref.artifact_revision_id, datetime.now(UTC), False)
            for ref in refs
        ]
        return tuple(sorted({row.source_id for v in values for row in v.heads})), tuple(
            sorted({row.resource_id for v in values for row in v.grants})
        )

    for name in (
        "nexus.company.management.acceptance_freshness",
        "nexus.company.management.coding_prepared_checks",
    ):
        monkeypatch.setattr(name + ".reference_sources", closure)
    monkeypatch.setattr(native_module, "reference_sources", closure)
    monkeypatch.setattr(value.private.sources.artifacts, "_snapshot", snapshot)
    reader = CodingPublicationOriginReader(
        value.private.factory,
        value.catalog,
        value.private.sources.artifacts,
        value.private.sources.freshness,
        rules=value.rules,
        recipe=value.prepared.input_recipe,
    )
    (
        value.origin_reader,
        value.builder_spec,
        value.builder_policy,
        value.builder_lease,
        value.builder_credential,
        value.builder_work,
        value.builder_action,
        value.published,
    ) = (reader, spec, policy, lease, credential, work, action, published)
    return value


@pytest.mark.parametrize("different_native_title", [False, True])
async def test_current_origin_requires_exact_approved_title_before_private_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, different_native_title: bool
) -> None:
    from unittest.mock import AsyncMock

    from nexus.company.management import coding_publication_origin_native as native_module
    from nexus.company.management.plan_store import ManagementPlanStore
    from nexus.company.management.planning_native_facts import clock_us

    value = await origin_case(tmp_path, monkeypatch)
    current = value.native.directory.work
    assert current is not None
    approved = current.registration.work.model_copy(update={"title": "Model proposed coder"})
    actual = (
        approved.model_copy(update={"title": "Different native title"})
        if different_native_title
        else approved
    )
    value.native = value.native.model_copy(
        update={
            "directory": value.native.directory.model_copy(
                update={
                    "work": current.model_copy(
                        update={
                            "registration": current.registration.model_copy(update={"work": actual})
                        }
                    )
                }
            )
        }
    )
    monkeypatch.setattr(
        ManagementPlanStore,
        "current_binding",
        AsyncMock(return_value=SimpleNamespace(plan=value.loaded.header.plan, work=approved)),
    )

    class BeforePrivatePairError(RuntimeError):
        pass

    private = AsyncMock(
        side_effect=BeforePrivatePairError("native metadata joined before private pair")
    )
    monkeypatch.setattr(native_module, "origin_references", private)
    if different_native_title:
        with pytest.raises(ValueError, match="native work differs"):
            await value.origin_reader.load(
                value.builder_lease,
                value.builder_credential,
                value.builder_spec,
                end_us=clock_us() + 20_000_000,
            )
        private.assert_not_awaited()
    else:
        with pytest.raises(BeforePrivatePairError):
            await value.origin_reader.load(
                value.builder_lease,
                value.builder_credential,
                value.builder_spec,
                end_us=clock_us() + 20_000_000,
            )
        private.assert_awaited_once()
    assert not value.origin_reader.pending_owners()


async def test_actual_published_pair_read_has_current_actor_and_issued_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace

    from nexus.company.management.planning_native_facts import clock_us

    value = await origin_case(tmp_path, monkeypatch)
    reader = value.origin_reader
    proof = await reader.load(
        value.builder_lease,
        value.builder_credential,
        value.builder_spec,
        end_us=clock_us() + 20_000_000,
    )
    assert proof.bodies[1].raw == proof.origin.content.patch.encode()
    assert proof.origin.actual_usd == value.native.hold.actual_usd
    assert value.builder_credential.identity.principal_id not in value.artifact.allowed_principals
    reader.require_loaded(proof, value.builder_lease, value.builder_credential, value.builder_spec)
    with pytest.raises(ValueError):
        reader.require_loaded(
            replace(proof), value.builder_lease, value.builder_credential, value.builder_spec
        )
    assert not reader.pending_owners()


async def test_crossed_native_receipt_denies_before_any_derivative_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import AsyncMock
    from uuid import UUID

    from nexus.company.management.planning_native_facts import clock_us

    value = await origin_case(tmp_path, monkeypatch)
    original = value.private.sources.artifacts.bounded_artifact
    reads = AsyncMock(side_effect=original)
    monkeypatch.setattr(value.private.sources.artifacts, "bounded_artifact", reads)
    receipt = value.native.intent.receipt.model_copy(update={"receipt_id": UUID(int=17881)})
    value.native = value.native.model_copy(
        update={"intent": value.native.intent.model_copy(update={"receipt": receipt})}
    )
    with pytest.raises(ValueError):
        await value.origin_reader.load(
            value.builder_lease,
            value.builder_credential,
            value.builder_spec,
            end_us=clock_us() + 20_000_000,
        )
    reads.assert_not_awaited()


@pytest.mark.parametrize("when", ["before", "after"])
async def test_actual_actor_source_revocation_never_returns_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, when: str
) -> None:
    from nexus.company.brain.access_models import BrainResourceAccess
    from nexus.company.management.planning_native_facts import clock_us

    value = await origin_case(tmp_path, monkeypatch)
    resource = value.loaded.header.contributors[0].resource_id
    grant = next(
        row
        for row in value.memory.rows
        if isinstance(row, BrainResourceAccess)
        and row.resource_id == resource
        and row.principal_id == value.builder_credential.identity.principal_id
    )
    blobs = value.private.sources.artifacts.blobs
    original = blobs.read
    calls = []

    async def read(reference: ArtifactRevisionRef) -> bytes:
        calls.append(reference)
        raw = await original(reference)
        assert isinstance(raw, bytes)
        grant.active = False
        return raw

    if when == "before":
        grant.active = False
    else:
        monkeypatch.setattr(blobs, "read", read)
    old = value.native.model_dump_json()
    with pytest.raises(ValueError):
        await value.origin_reader.load(
            value.builder_lease,
            value.builder_credential,
            value.builder_spec,
            end_us=clock_us() + 20_000_000,
        )
    assert (len(calls) == 0) if when == "before" else (len(calls) == 1)
    assert value.native.model_dump_json() == old
    assert not value.origin_reader._issued


async def test_cancelled_actual_blob_leaf_stays_owned_and_never_issues_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio
    from threading import Event

    from nexus.company.management.planning_native_facts import clock_us

    value = await origin_case(tmp_path, monkeypatch)
    blobs = value.private.sources.artifacts.blobs
    original = blobs._read
    started, finish = asyncio.Event(), Event()
    loop = asyncio.get_running_loop()

    def read(path: Path) -> bytes:
        loop.call_soon_threadsafe(started.set)
        if not finish.wait(3):
            raise TimeoutError("finite fixture worker")
        raw = original(path)
        assert isinstance(raw, bytes)
        return raw

    monkeypatch.setattr(blobs, "_read", read)
    end_us = clock_us() + 10_000_000
    task = asyncio.create_task(
        value.origin_reader.load(
            value.builder_lease,
            value.builder_credential,
            value.builder_spec,
            end_us=end_us,
        )
    )
    try:
        await asyncio.wait_for(started.wait(), max(0, end_us - clock_us()) / 1_000_000)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert value.origin_reader.pending_owners()
        assert not value.origin_reader._issued
        finish.set()
        while value.origin_reader.pending_owners():
            await asyncio.sleep(0.01)
        assert not value.origin_reader._issued
    finally:
        finish.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        pending = value.origin_reader.pending_owners()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


async def test_first_source_expiry_cannot_be_renewed_during_body_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio
    from datetime import UTC, datetime, timedelta

    from nexus.company.management import coding_publication_origin_native as native_module
    from nexus.company.management.planning_native_facts import clock_us

    value = await origin_case(tmp_path, monkeypatch)
    from nexus.company.management.coding_prepared_checks import action_sources

    original_sources = action_sources
    original_read = value.private.sources.artifacts.blobs.read
    first = datetime.now(UTC) + timedelta(seconds=0.2)
    count = 0

    async def sources(
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        action: ActionProposal,
        views: OwnerViewSources,
        *,
        historical: bool,
    ) -> tuple[str, tuple[datetime, ...]]:
        nonlocal count
        signature, windows = await original_sources(
            session, control, scope, identity, action, views, historical=historical
        )
        count += 1
        return signature, (
            *windows,
            first if count == 1 else datetime.now(UTC) + timedelta(seconds=20),
        )

    async def read(reference: ArtifactRevisionRef) -> bytes:
        await asyncio.sleep(0.3)
        raw = await original_read(reference)
        assert isinstance(raw, bytes)
        return raw

    monkeypatch.setattr(native_module, "action_sources", sources)
    monkeypatch.setattr(value.private.sources.artifacts.blobs, "read", read)
    with pytest.raises((ValueError, TimeoutError)):
        await value.origin_reader.load(
            value.builder_lease,
            value.builder_credential,
            value.builder_spec,
            end_us=clock_us() + 10_000_000,
        )
    while value.origin_reader.pending_owners():
        await asyncio.sleep(0.01)
    assert not value.origin_reader._issued


async def test_actual_original_witness_values_cannot_change_across_private_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import timedelta

    from nexus.company.management.planning_native_facts import clock_us

    value = await origin_case(tmp_path, monkeypatch)
    blobs = value.private.sources.artifacts.blobs
    original = blobs.read
    old = value.builder_credential.expires_at

    async def read(reference: ArtifactRevisionRef) -> bytes:
        raw = await original(reference)
        assert isinstance(raw, bytes)
        object.__setattr__(value.builder_credential, "expires_at", old + timedelta(seconds=30))
        return raw

    monkeypatch.setattr(blobs, "read", read)
    with pytest.raises(ValueError):
        await value.origin_reader.load(
            value.builder_lease,
            value.builder_credential,
            value.builder_spec,
            end_us=clock_us() + 20_000_000,
        )
    assert not value.origin_reader._issued


async def test_cancelled_first_page_settles_leaf_without_starting_later_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio
    import json
    from threading import Event
    from unittest.mock import AsyncMock

    from nexus.company.management.planning_native_facts import clock_us
    from nexus.tests.unit import test_coding_consumer as fixture

    original_output = fixture.output

    def output(prepared: PreparedCodingRequest, semantic: str = "valid") -> str:
        value = json.loads(original_output(prepared, semantic))
        value["explanation"] = "x" * 8192
        value["questions"] = [str(i) + "q" * 1000 for i in range(16)]
        return json.dumps(value)

    monkeypatch.setattr(fixture, "output", output)
    value = await origin_case(tmp_path, monkeypatch)
    assert value.published.origin.artifact.byte_length > 16384
    reader = value.origin_reader
    blobs = reader.artifacts.blobs
    original = blobs._read
    started, finish = asyncio.Event(), Event()
    loop = asyncio.get_running_loop()

    def read(path: Path) -> bytes:
        loop.call_soon_threadsafe(started.set)
        if not finish.wait(3):
            raise TimeoutError("finite fixture worker")
        raw = original(path)
        assert isinstance(raw, bytes)
        return raw

    monkeypatch.setattr(blobs, "_read", read)
    pages = AsyncMock(side_effect=reader.artifacts.bounded_artifact)
    monkeypatch.setattr(reader.artifacts, "bounded_artifact", pages)
    end_us = clock_us() + 10_000_000
    task = asyncio.create_task(
        reader.load(
            value.builder_lease,
            value.builder_credential,
            value.builder_spec,
            end_us=end_us,
        )
    )
    try:
        await asyncio.wait_for(started.wait(), max(0, end_us - clock_us()) / 1_000_000)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert reader.pending_owners()
        finish.set()
        while reader.pending_owners():
            await asyncio.sleep(0.01)
        assert pages.await_count == 1
        assert not reader._issued
        # Per-read stop cannot poison a subsequent genuine read with the same store.
    finally:
        finish.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        pending = reader.pending_owners()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
    second = await reader.load(
        value.builder_lease,
        value.builder_credential,
        value.builder_spec,
        end_us=clock_us() + 10_000_000,
    )
    assert second.origin.actual_usd == value.native.hold.actual_usd


async def test_cancelled_real_unicode_boundary_cannot_start_private_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio
    import json
    from threading import Event
    from unittest.mock import AsyncMock

    from nexus.company.management.planning_native_facts import clock_us
    from nexus.tests.unit import test_coding_consumer as fixture

    original_output = fixture.output
    value = None
    for prefix in range(3):

        def output(
            prepared: PreparedCodingRequest, semantic: str = "valid", offset: int = prefix
        ) -> str:
            body = json.loads(original_output(prepared, semantic))
            body["explanation"] = "x" * offset + "ก" * 2728
            body["questions"] = [str(i) + "q" * 1000 for i in range(16)]
            return json.dumps(body, ensure_ascii=False)

        monkeypatch.setattr(fixture, "output", output)
        directory = tmp_path / str(prefix)
        directory.mkdir(mode=0o700)
        candidate = await origin_case(directory, monkeypatch)
        raw = await candidate.origin_reader.blobs.read(candidate.published.origin.artifact)
        try:
            raw[:16384].decode("utf-8")
        except UnicodeDecodeError:
            value = candidate
            break
    assert value is not None, "three literal UTF8 alignments must include an actual split"
    reader = value.origin_reader
    original = reader.blobs._read
    started, finish = asyncio.Event(), Event()
    loop = asyncio.get_running_loop()

    def read(path: Path) -> bytes:
        loop.call_soon_threadsafe(started.set)
        if not finish.wait(3):
            raise TimeoutError("finite fixture worker")
        raw = original(path)
        assert isinstance(raw, bytes)
        return raw

    monkeypatch.setattr(reader.blobs, "_read", read)
    pages = AsyncMock(side_effect=reader.artifacts.bounded_artifact)
    monkeypatch.setattr(reader.artifacts, "bounded_artifact", pages)
    end_us = clock_us() + 10_000_000
    task = asyncio.create_task(
        reader.load(
            value.builder_lease,
            value.builder_credential,
            value.builder_spec,
            end_us=end_us,
        )
    )
    try:
        await asyncio.wait_for(started.wait(), max(0, end_us - clock_us()) / 1_000_000)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert reader.pending_owners()
        finish.set()
        while reader.pending_owners():
            await asyncio.sleep(0.01)
        assert pages.await_count == 1
        assert not reader._issued
    finally:
        finish.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        pending = reader.pending_owners()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
    second = await reader.load(
        value.builder_lease,
        value.builder_credential,
        value.builder_spec,
        end_us=clock_us() + 10_000_000,
    )
    assert second.origin.actual_usd == value.native.hold.actual_usd

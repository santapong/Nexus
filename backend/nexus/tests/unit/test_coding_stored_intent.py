"""Original C/store proof and actual native metadata predicates with supplied SQL only."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.model_context_check import BrainModelContextCheck
from nexus.company.brain.source_models import BrainSource, BrainSourceRevision
from nexus.company.management.coding_intent import CodingIntentCheck
from nexus.company.management.coding_prepared_checks import (
    action_sources,
    current_native,
    require_action_header,
    require_code_metadata,
    require_native_header,
    source_read,
)
from nexus.company.management.coding_prepared_contracts import (
    StoredCodingRequest,
    encode_prepared,
    header_for,
)
from nexus.company.management.coding_prepared_store import Mode
from nexus.company.management.coding_stored_intent import StoredCodingIntent
from nexus.company.management.nexus_coding_model_intent import NexusCodingModelIntentCheck
from nexus.company.management.plan_models import ManagementPlanRevision
from nexus.company.management.planning_native_facts import clock_us
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.harness.journal_models import CompanyControl
from nexus.tests.unit.test_coding_intent import witness
from nexus.tests.unit.test_coding_prepared_store import NativeDelivery, saved_case, store_case
from nexus.tests.unit.test_nexus_coding_admission import planning_origin


async def stored_check(root: Path, monkeypatch: pytest.MonkeyPatch) -> StoredCodingIntent:
    store, prepared, lease, credential, _ = await saved_case(root, monkeypatch)
    loaded = await store.load_worker(
        lease, credential, prepared.request.action_id, end_us=clock_us() + 10_000_000
    )
    brain = BrainModelContextCheck(
        store.contexts,
        prepared.context,
        prepared.scope,
        credential.identity,
        prepared.request,
        prepared.input_recipe,
        lease,
        allowed_classification=prepared.request.data_classification,
    )
    return StoredCodingIntent(
        NexusCodingModelIntentCheck(
            CodingIntentCheck(brain, prepared, registry=store.management.catalog.models), credential
        ),
        store,
        loaded,
    )


async def test_same_actual_store_loaded_witness_and_context_are_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    check = await stored_check(tmp_path, monkeypatch)
    check.validate_time(datetime.now(UTC))
    copied = StoredCodingRequest(
        check.stored.prepared, check.stored.reference, check.stored.header, check.stored.read_end_us
    )
    with pytest.raises(ValueError):
        StoredCodingIntent(check.original, check.store, copied)
    check.stored = copied
    with pytest.raises(ValueError):
        check.require_composition()


async def test_stored_native_checks_are_bracketed_by_original_c_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    check = await stored_check(tmp_path, monkeypatch)
    events = []

    async def original(*args: object) -> None:
        events.append("original")

    actual = check.store.validate_loaded_locked

    async def stored(
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        value: StoredCodingRequest,
        credential: AuthenticatedWorkerIdentity,
        lease: ExecutionLease | None,
        *,
        mode: Mode = "worker",
        now: datetime,
    ) -> int:
        events.append("store")
        return await actual(session, control, scope, value, credential, lease, mode=mode, now=now)

    monkeypatch.setattr(check.original, "validate", original)
    monkeypatch.setattr(check.store, "validate_loaded_locked", stored)
    from nexus.execution.runtime_models import ExecutionWork
    from nexus.harness.journal_models import JournalAction

    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = datetime.now(UTC)
    await check.validate(
        session,
        CompanyControl(),
        ExecutionWork(),
        JournalAction(),
        datetime.now(UTC),
    )
    assert events == ["original", "store", "original"]


@pytest.mark.parametrize("fault", ["root", "goal", "plan", "admission", "parameters", "conditions"])
def test_exact_native_header_root_and_model_action_are_not_replaceable(fault: str) -> None:
    from nexus.company.management.coding_prepared_checks import conditions
    from nexus.tests.unit.test_coding_prepared_contracts import encoded_case

    header, _, action = encoded_case()
    action = action.model_copy(update={"preconditions": conditions(header)})
    if fault == "parameters":
        action = action.model_copy(
            update={"parameters": {**action.parameters, "request_hash": "f" * 64}}
        )
    elif fault == "conditions":
        action = action.model_copy(update={"preconditions": action.preconditions[:-1]})
    else:
        changes: dict[str, dict[str, object]] = {
            "root": {"root_registration_sha256": "f" * 64},
            "goal": {"goal": header.goal.model_copy(update={"revision_id": UUID(int=999)})},
            "plan": {"plan": header.plan.model_copy(update={"sha256": "f" * 64})},
            "admission": {"admission_sha256": "f" * 64},
        }
        header = header.model_copy(update=changes[fault])
    with pytest.raises(ValueError):
        require_action_header(action, header)


@pytest.mark.parametrize("fault", [None, "missing", "full-profile", "child", "root"])
async def test_actual_current_execution_plan_and_full_allocation_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str | None
) -> None:
    from nexus.company.management import coding_prepared_checks as module

    store, prepared, lease = store_case(tmp_path)
    delivery = NativeDelivery(store, prepared)
    native = delivery.native()
    admission = store.management.catalog.nexus_coding_admission
    assert admission is not None
    payload = admission.payload("execution", origin=planning_origin(admission))
    row = ManagementPlanRevision(
        company_id=prepared.request.company_id,
        plan_id=prepared.binding.plan.plan_id,
        plan_revision_id=prepared.binding.plan.plan_revision_id,
        revision=2,
        sha256=prepared.binding.plan.sha256,
        snapshot_json=payload.model_dump_json(),
        proposed_by=delivery.control.owner_id,
        recorded_at=datetime.now(UTC),
    )
    if fault == "full-profile":
        row.snapshot_json = payload.model_copy(
            update={"coding_admission_sha256": "f" * 64}
        ).model_dump_json()
    if fault == "child":
        native = replace(
            native,
            current=replace(
                native.current,
                current=native.current.current.model_copy(update={"work": admission.slots[0].work}),
            ),
        )
    session = AsyncMock(spec=AsyncSession)
    session.get.return_value = None if fault == "missing" else row
    monkeypatch.setattr(module, "native_prepared", AsyncMock(return_value=native.current))
    root = AsyncMock(return_value=native.root_registration_sha256)
    if fault == "root":
        root.side_effect = ValueError("actual root differs")
    monkeypatch.setattr(module, "root_registration", root)
    call = current_native(
        session,
        delivery.control,
        prepared.scope,
        (await witness(prepared)).identity,
        store.management.catalog,
        prepared.request.task_id,
        prepared.request.action_id,
        prepared.input_recipe,
        lease=lease,
        mode="worker",
    )
    if fault is None:
        assert await call == native
        raw, body = encode_prepared(prepared)
        header = header_for(
            prepared,
            body,
            owner_id=delivery.control.owner_id,
            registration_sha256=native.current.registration_sha256,
            root_task_id=admission.procedure.binding.task_id,
            root_run_id=admission.procedure.binding.run_id,
            root_registration_sha256="c" * 64,
            procedure_id=admission.procedure.procedure_id,
        )
        require_native_header(native, header, admission, prepared.input_recipe)
        assert raw
    else:
        with pytest.raises(ValueError):
            await call


async def source_case(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[StoredCodingIntent, AsyncSession]:
    check = await stored_check(root, monkeypatch)
    from nexus.company.management import coding_prepared_checks as module

    session = AsyncMock(spec=AsyncSession)
    header = check.stored.header
    rows: dict[
        tuple[type[BrainSource] | type[BrainSourceRevision], UUID],
        BrainSource | BrainSourceRevision,
    ] = {}
    artifacts = {}
    for code in header.code_sources:
        rows[(BrainSourceRevision, code.source.source_revision_id)] = BrainSourceRevision(
            company_id=header.company_id,
            source_id=code.source.source_id,
            source_revision_id=code.source.source_revision_id,
            revision=code.source.revision,
            artifact_revision_id=code.artifact.artifact_revision_id,
            source_event_precision=code.git.source_event.precision,
            source_event_value=code.git.source_event.value,
            source_event_basis=code.git.source_event.basis,
        )
        rows[(BrainSource, code.source.source_id)] = BrainSource(
            company_id=header.company_id,
            source_id=code.source.source_id,
            source_symbol=code.git.source_symbol,
            external_key=code.git.external_key,
        )
        artifacts[code.artifact.artifact_revision_id] = code.artifact
    session.get.side_effect = lambda model, key: rows.get((model, key[1]))
    monkeypatch.setattr(
        module,
        "source_artifact_reference",
        AsyncMock(side_effect=lambda _session, _scope, key: artifacts[key]),
    )
    monkeypatch.setattr(module, "heads", AsyncMock(return_value=header.source_heads))
    monkeypatch.setattr(module, "require_resources", AsyncMock(return_value=header.contributors))
    monkeypatch.setattr(
        module,
        "reference_sources",
        AsyncMock(
            return_value=(
                tuple(row.source_id for row in header.source_heads),
                tuple(row.resource_id for row in header.contributors),
            )
        ),
    )
    monkeypatch.setattr(module, "db_now", AsyncMock(side_effect=lambda _: datetime.now(UTC)))
    monkeypatch.setattr(check.store.sources.artifacts, "revalidate_artifact_reference", AsyncMock())
    monkeypatch.setattr(check.store.sources.freshness, "revalidate_references", AsyncMock())
    return check, session


@pytest.mark.parametrize("fault", [None, "event", "external", "artifact", "expired"])
async def test_registered_git_metadata_and_complete_source_closure_before_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str | None
) -> None:
    check, session = await source_case(tmp_path, monkeypatch)
    header = check.stored.header
    first = header.code_sources[0]
    if fault in {"event", "external"}:
        model, key = (
            (BrainSourceRevision, first.source.source_revision_id)
            if fault == "event"
            else (BrainSource, first.source.source_id)
        )
        row = await session.get(model, (header.company_id, key))
        assert row is not None
        if fault == "event":
            assert isinstance(row, BrainSourceRevision)
            row.source_event_value = "2000-01-01T00:00:00+00:00"
        else:
            assert isinstance(row, BrainSource)
            row.external_key = "foreign"
    elif fault == "artifact":
        header = header.model_copy(
            update={
                "code_sources": (
                    first.model_copy(
                        update={"artifact": first.artifact.model_copy(update={"sha256": "f" * 64})}
                    ),
                    *header.code_sources[1:],
                )
            }
        )
    elif fault == "expired":
        header = header.model_copy(
            update={
                "contributors": (
                    header.contributors[0].model_copy(
                        update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
                    ),
                    *header.contributors[1:],
                )
            }
        )
    operation = source_read(
        session,
        CompanyControl(),
        check.stored.prepared.scope,
        check.credential.identity,
        header,
        check.store.sources,
    )
    if fault is None:
        assert await operation == ()
        await require_code_metadata(session, check.stored.prepared.scope, header)
    else:
        with pytest.raises(ValueError):
            await operation


async def test_historical_source_access_uses_current_acl_and_history_policy_not_old_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nexus.company.management import coding_prepared_checks as module
    from nexus.company.management.acceptance_freshness import QualifiedFreshness

    check, session = await source_case(tmp_path, monkeypatch)
    header = check.stored.header
    action = check.store._issued[0][0].prepared.request
    delivery = NativeDelivery(check.store, check.stored.prepared)
    delivery.publish(check.stored.reference)
    assert delivery.action is not None and action.action_id == delivery.action.action_id
    changed = tuple(
        row.model_copy(update={"generation": row.generation + 1}) for row in header.source_heads
    )
    monkeypatch.setattr(module, "heads", AsyncMock(return_value=changed))
    historical = AsyncMock(return_value=())
    monkeypatch.setattr(
        check.store.sources.artifacts, "revalidate_historical_artifact_reference", historical
    )
    monkeypatch.setattr(
        check.store.sources.freshness,
        "revalidate_historical_references",
        AsyncMock(return_value=()),
    )
    from nexus.company.brain.source_registry import SourcePolicy

    policy = SourcePolicy(
        source_symbol=header.code_sources[0].git.source_symbol,
        authority_profile="owner.primary.v1",
        data_classification="confidential",
        media_type="text/plain",
        parser_version="utf8-identity-v1",
        chunker_version="utf8-sections-v1",
        search_config="simple",
        freshness_seconds=None,
    )
    qualified = QualifiedFreshness(
        source_id=changed[0].source_id, policy=policy, fresh_until=None, available=True
    )
    monkeypatch.setattr(
        check.store.sources.freshness,
        "capture_plan_heads_locked",
        AsyncMock(return_value=(qualified,)),
    )
    args = (
        session,
        CompanyControl(),
        check.stored.prepared.scope,
        check.credential.identity,
        delivery.action,
        check.store.sources,
    )
    with pytest.raises(ValueError):
        await action_sources(*args, historical=False)
    signature, windows = await action_sources(*args, historical=True)
    assert (
        len(signature) == 64
        and windows == ()
        and historical.await_count == len(header.code_sources)
    )

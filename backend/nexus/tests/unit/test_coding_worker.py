"""Actual C orchestration around supplied native history, no DB/SDK process activation.

Cohesion exception: issued replay, real queue-header decoding and retained worker
owners share the same native-delivery fixture; splitting it would hide replay scope.
"""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from nexus.builder.contained_query import clock_us
from nexus.execution.coding_history import NativeCodingHistory
from nexus.execution.coding_operation import CodingOperation
from nexus.execution.coding_services import (
    APPLICATION,
    APPLICATION_VERSION,
    QUEUE,
    VERSION,
    WORKFLOW,
)
from nexus.execution.coding_worker import execute_coding_segment
from nexus.execution.runtime_contracts import EffectRecord
from nexus.tests.unit.coding_runtime_fixture import command, runtime_case


@pytest.mark.parametrize("state", ["succeeded", "failed", "intent", "outcome_unknown"])
async def test_issued_history_precedes_token_private_body_lease_and_sdk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    state: str,
) -> None:
    from nexus.execution import coding_worker as module

    value, prepared, lease = runtime_case(tmp_path)
    selected = command(prepared, lease)
    effect = EffectRecord.model_validate(
        {
            "company_id": selected.company_id,
            "action_id": selected.action_id,
            "task_id": selected.task_id,
            "trace_id": selected.trace_id,
            "run_id": selected.run_id,
            "proposal_hash": "a" * 64,
            "intent_fence": 1,
            "attempt_kind": "model_requests",
            "state": state,
            "created_at": datetime.now(UTC),
            "receipt": None,
            "verification": None,
        }
    )
    monkeypatch.setattr(
        module, "native_history", AsyncMock(return_value=NativeCodingHistory(effect, "b" * 64))
    )
    token = AsyncMock(side_effect=AssertionError("history must not refresh JWT"))
    claim = AsyncMock(side_effect=AssertionError("history must not acquire lease"))
    monkeypatch.setattr(type(value.identities), "current", token)
    monkeypatch.setattr(value.execution, "recover_dispatched", claim)
    from nexus.company.management.coding_prepared_store import CodingPreparedStore

    body = AsyncMock(side_effect=AssertionError("history must not read body"))
    monkeypatch.setattr(CodingPreparedStore, "load_worker", body)
    result = await execute_coding_segment(
        value, selected, workflow_id=selected.workflow_id, end_us=clock_us() + 10_000_000
    )
    assert result.replayed and result.native_state == state and not result.company_completed
    assert result.status == (
        "known_history" if state in {"succeeded", "failed"} else "outcome_unknown"
    )
    token.assert_not_awaited()
    claim.assert_not_awaited()
    body.assert_not_awaited()


async def test_real_c_launcher_uses_pinned_one_shot_queue_api_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import dataclass

    import dbos._dbos as sdk
    from dbos import DBOS
    from sqlalchemy.ext.asyncio import AsyncSession

    from nexus.execution import coding_worker as module

    @dataclass
    class State:
        _launched: bool = False
        _listening_queues: list[str] | None = None

    value, _, _ = runtime_case(tmp_path)
    state = State()
    events = []
    monkeypatch.setattr(sdk, "_dbos_global_instance", state)
    monkeypatch.setattr(module, "_services", value)
    sql = AsyncMock(return_value=False)
    registration = AsyncMock()
    monkeypatch.setattr(AsyncSession, "scalar", sql)
    monkeypatch.setattr(DBOS, "register_queue_async", registration)

    def launch() -> None:
        assert state._listening_queues == [QUEUE]
        state._launched = True
        events.append("launch")

    monkeypatch.setattr(DBOS, "launch", launch)
    await module.launch_coding_worker()
    assert events == ["launch"]
    registration.assert_awaited_once_with(
        QUEUE, global_concurrency=1, worker_concurrency=1, polling_interval_sec=1.0
    )
    sql.assert_awaited_once()


@pytest.mark.parametrize("fault", [None, "recipe", "marker", "legacy_unissued", "legacy_issued"])
async def test_real_native_history_consumes_exact_producer_parameters_without_private_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str | None,
) -> None:
    from collections.abc import AsyncIterator
    from contextlib import asynccontextmanager
    from decimal import Decimal
    from typing import cast
    from unittest.mock import MagicMock

    from sqlalchemy.ext.asyncio import AsyncSession

    from nexus.company.contracts.actions import ActionProposal
    from nexus.company.management.coding_prepared_contracts import (
        encode_prepared,
        header_for,
        header_reference,
    )
    from nexus.execution import coding_history as module
    from nexus.execution.runtime_models import EffectIntent, ExecutionWork
    from nexus.harness.canonical import action_hash
    from nexus.harness.journal import CompanyJournal
    from nexus.harness.journal_budget import billing_day
    from nexus.harness.journal_contracts import LedgerScope
    from nexus.harness.journal_models import CompanyControl, CostHold, JournalAction
    from nexus.harness.model_authorizer_contracts import model_action_parameters

    value, prepared, lease = runtime_case(tmp_path)
    selected = command(prepared, lease)
    admission = value.management.catalog.nexus_coding_admission
    assert admission is not None
    _, body = encode_prepared(prepared)
    header = header_for(
        prepared,
        body,
        owner_id=admission.procedure.binding.actor_id,
        registration_sha256="a" * 64,
        root_task_id=admission.procedure.binding.task_id,
        root_run_id=admission.procedure.binding.run_id,
        root_registration_sha256="b" * 64,
        procedure_id=admission.procedure.procedure_id,
    )
    reference, _ = header_reference(header)
    recipe = (
        value.recipe.model_copy(update={"minimum_score": Decimal("0.12")})
        if fault == "recipe"
        else value.recipe
    )
    proposal = ActionProposal(
        company_id=selected.company_id,
        task_id=selected.task_id,
        trace_id=selected.trace_id,
        actor_id=selected.actor_id,
        action_id=selected.action_id,
        revision=1,
        tool="model.request.v1",
        tool_version="v1",
        resource="model:" + value.registry_id,
        parameters=model_action_parameters(prepared.request, recipe),
        preconditions=() if fault == "marker" else (reference.condition,),
        policy_version="fixture-policy",
        price_version=value.management.catalog.models.pricebook_version,
        estimated_cost_usd="0.01",
    )
    work = ExecutionWork(
        company_id=selected.company_id,
        task_id=selected.task_id,
        workflow_name=WORKFLOW,
        workflow_version=VERSION,
        model_registry_version=prepared.request.registry_revision,
        model_profile=value.recipe.profile,
    )
    action = JournalAction(
        id=selected.action_id,
        company_id=selected.company_id,
        task_id=selected.task_id,
        trace_id=selected.trace_id,
        proposal_json=proposal.model_dump_json(),
        proposal_hash=action_hash(proposal),
        state="authorized",
        consumed_at=datetime.now(UTC),
        approval_json=None,
    )
    effect, hold = None, None
    if fault == "legacy_issued":
        from nexus.tests.unit.coding_runtime_fixture import native_work

        work = native_work(value, lease)
        work.model_requests_used = 1
        now = datetime.now(UTC)
        effect = EffectIntent(
            company_id=selected.company_id,
            action_id=selected.action_id,
            task_id=selected.task_id,
            trace_id=selected.trace_id,
            run_id=selected.run_id,
            proposal_hash=action_hash(proposal),
            intent_fence=1,
            attempt_kind="model_requests",
            state="outcome_unknown",
            created_at=now,
            receipt_json=None,
            verification_json=None,
        )
        hold = CostHold(
            company_id=selected.company_id,
            task_id=selected.task_id,
            action_id=selected.action_id,
            amount_usd=proposal.estimated_cost_usd,
            day=billing_day(now),
            state="unknown",
            actual_usd=None,
        )
    fake = MagicMock(spec=AsyncSession)
    fake.get = AsyncMock(
        side_effect=lambda model, key: {
            ExecutionWork: work,
            JournalAction: action,
            EffectIntent: effect,
            CostHold: hold,
        }.get(model)
    )
    queue = MagicMock()
    queue.mappings.return_value.one_or_none.return_value = {
        "name": WORKFLOW,
        "queue_name": QUEUE,
        "application_version": "v1"
        if fault in {"legacy_unissued", "legacy_issued"}
        else APPLICATION_VERSION,
        "application_name": APPLICATION,
        "serialization": "portable_json",
        "inputs": json.dumps({"positionalArgs": [selected.model_dump_json()], "namedArgs": {}}),
    }
    fake.execute = AsyncMock(return_value=queue)

    @asynccontextmanager
    async def native(self: CompanyJournal, scope: LedgerScope) -> AsyncIterator[AsyncSession]:
        assert scope.task_id == selected.task_id
        yield cast(AsyncSession, fake)

    monkeypatch.setattr(CompanyJournal, "_session", native)
    monkeypatch.setattr(
        module,
        "_control",
        AsyncMock(
            return_value=CompanyControl(
                company_id=selected.company_id, owner_id=admission.procedure.binding.actor_id
            )
        ),
    )
    monkeypatch.setattr(module, "dispatched_binding", AsyncMock(return_value=selected))
    credential = AsyncMock(side_effect=AssertionError("No fresh JWT in native history"))
    monkeypatch.setattr(type(value.identities), "current", credential)
    if fault in {None, "legacy_issued"}:
        read = await module.native_history(value, selected)
        assert read.request_sha256 == prepared.request_sha256
        if fault == "legacy_issued":
            assert read.effect is not None and read.effect.state == "outcome_unknown"
            assert hold is not None and hold.state == "unknown" and hold.actual_usd is None
        else:
            assert read.effect is None
    else:
        with pytest.raises(ValueError):
            await module.native_history(value, selected)
    credential.assert_not_awaited()


async def test_cancelled_projection_retains_governed_unknown_without_late_candidate(
    tmp_path: Path,
) -> None:
    from nexus.core.llm.company_adapter_contracts import CompanyModelResult
    from nexus.execution.coding_worker import _result
    from nexus.harness.model_client import GovernedModelClient
    from nexus.harness.model_client_contracts import GovernedModelCancelledError

    value, prepared, lease = runtime_case(tmp_path)
    selected = command(prepared, lease)
    operation = CodingOperation(value, "cancelled", clock_us() + 10_000_000)
    governed = GovernedModelClient._outcome(
        CompanyModelResult(
            request_id=selected.action_id,
            status="cancelled",
            billing="unknown",
            usage=None,
            error_code="cancelled",
        ),
        None,
        recording_error="recording_timeout",
        release_error="release_failed",
    )
    first = GovernedModelCancelledError(governed)
    operation.first = first
    result = _result(
        selected,
        operation,
        NativeCodingHistory(None, prepared.request_sha256),
        None,
        replayed=False,
    )
    assert result.status == "outcome_unknown" and result.native_state is None
    assert not result.company_completed and result.receipt_id is None
    assert operation.first is first and first.governed == governed
    operation.finish()


@pytest.mark.parametrize("response_delay", [0.0, 1.2])
async def test_actual_worker_uses_h_issued_store_load_and_one_real_sdk_post(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    response_delay: float,
) -> None:
    """Actual TinyGit/store/SDK/protected files; native SQL, claims and charge delivery supplied."""
    from collections.abc import AsyncIterator
    from contextlib import asynccontextmanager
    from typing import cast
    from unittest.mock import MagicMock

    import httpx2
    from sqlalchemy.ext.asyncio import AsyncSession

    from nexus.company.management.coding_consumer import RegisteredCodingConsumer
    from nexus.company.management.coding_prepared_checks import conditions
    from nexus.execution import coding_worker as module
    from nexus.harness.journal_models import CompanyControl
    from nexus.tests.unit.coding_runtime_fixture import (
        bind_real_consumer_delivery,
        native_work,
        services_from_store,
    )
    from nexus.tests.unit.test_coding_consumer import output
    from nexus.tests.unit.test_coding_prepared_store import saved_case
    from nexus.tests.unit.test_company_provider_conformance import response

    store, prepared, lease, credential, delivery = await saved_case(tmp_path, monkeypatch)
    original = await store.load_worker(
        lease, credential, prepared.request.action_id, end_us=clock_us() + 20_000_000
    )
    posts = []

    async def wire(request: httpx2.Request) -> httpx2.Response:
        posts.append(request.method)
        await asyncio.sleep(response_delay)
        body = json.loads(json.dumps(response("google")))
        row = next(
            row
            for row in store.management.catalog.models.models
            if row.registry_id == prepared.request.registry_id
        )
        body["modelVersion"] = row.model_id
        body["candidates"][0]["content"]["parts"][0]["text"] = output(prepared)
        return httpx2.Response(200, json=body)

    value = services_from_store(
        tmp_path, store, prepared, lease, httpx2.MockTransport(wire), endpoint_timeout_seconds=10
    )
    selected = command(prepared, lease)
    work = native_work(value, lease)
    seen = bind_real_consumer_delivery(monkeypatch)
    errors = []
    original_finish = CodingOperation.finish

    def finish(operation: CodingOperation) -> None:
        if operation.first is not None:
            errors.append((type(operation.first).__name__, str(operation.first)))
        original_finish(operation)

    monkeypatch.setattr(CodingOperation, "finish", finish)
    monkeypatch.setattr(type(value.identities), "current", AsyncMock(return_value=credential))
    monkeypatch.setattr(value.execution, "recover_dispatched", AsyncMock(return_value=lease))
    monkeypatch.setattr(module, "clock_now", AsyncMock(return_value=datetime.now(UTC)))
    monkeypatch.setattr(
        module,
        "native_history",
        AsyncMock(return_value=NativeCodingHistory(None, prepared.request_sha256)),
    )
    monkeypatch.setattr(
        "nexus.company.management.coding_prepared_store.current_native",
        AsyncMock(side_effect=lambda *args, **kwargs: delivery.native()),
    )

    @asynccontextmanager
    async def native(
        *args: object, **kwargs: object
    ) -> AsyncIterator[tuple[AsyncSession, CompanyControl, MagicMock]]:
        yield cast(AsyncSession, delivery.session), delivery.control, MagicMock()

    monkeypatch.setattr(module, "runtime_transaction", native)
    monkeypatch.setattr(module, "execution_row", AsyncMock(return_value=work))
    monkeypatch.setattr(module, "db_now", AsyncMock(side_effect=lambda session: datetime.now(UTC)))
    monkeypatch.setattr(
        value.contexts,
        "revalidate_context",
        AsyncMock(return_value=conditions(original.header)[:-1]),
    )
    result = await execute_coding_segment(
        value, selected, workflow_id=selected.workflow_id, end_us=clock_us() + 20_000_000
    )
    assert result.status == "historical_candidate", (result.model_dump(), errors, posts)
    assert (
        posts == ["POST"] and result.receipt_id is not None and result.artifact_sha256 is not None
    )
    assert result.lease_released and not result.resources_pending and not result.company_completed
    assert len(seen) == 1 and type(seen[0]) is RegisteredCodingConsumer
    assert seen[0]._prepared_store is value._stores[0] and value._stores[0] is not store
    value._stores[0].require_loaded(seen[0]._stored, credential, lease)

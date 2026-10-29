"""C preparation checks actual producer output; supplied native delivery is not SQL proof."""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from nexus.builder.contained_query import clock_us
from nexus.company.management.coding_intent import PreparedCodingRequest
from nexus.company.management.coding_prepared_contracts import repository_selection
from nexus.execution.coding_context import prepare_content
from nexus.execution.coding_preparation import prepare_work
from nexus.harness.journal_contracts import LedgerScope
from nexus.tests.unit.coding_runtime_fixture import runtime_case


async def test_foreign_actor_denied_before_claim_or_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value, prepared, _ = runtime_case(tmp_path)
    claim = AsyncMock(side_effect=AssertionError("foreign actor cannot claim"))
    monkeypatch.setattr(value.execution, "claim", claim)
    with pytest.raises(ValueError):
        await prepare_work(
            value,
            LedgerScope(
                company_id=prepared.request.company_id,
                principal_id=UUID(int=999),
                task_id=prepared.binding.task_id,
                trace_id=prepared.binding.trace_id,
            ),
            end_us=clock_us() + 10_000_000,
        )
    claim.assert_not_awaited()


def test_actual_c_producer_freezes_all_source_role_and_full_input_pins(tmp_path: Path) -> None:
    value, prepared, lease = runtime_case(tmp_path)
    produced = prepare_content(value, lease, prepared.scope, prepared.context, prepared.binding)
    assert type(produced) is PreparedCodingRequest
    assert produced.sources == value.code_sources
    assert repository_selection(produced) == value.repository_selection
    assert produced.admission_sha256 == prepared.admission_sha256
    assert produced.input_estimate.whole_request is not None
    assert produced.request.action_id != prepared.request.action_id
    assert (
        prepare_content(value, lease, prepared.scope, prepared.context, prepared.binding)
        == produced
    )
    assert produced.request.output_schema is not None and not produced.request.tools


async def test_expired_original_end_cannot_start_a_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value, prepared, _ = runtime_case(tmp_path)
    claim = AsyncMock()
    monkeypatch.setattr(value.execution, "claim", claim)
    with pytest.raises(TimeoutError):
        await prepare_work(
            value,
            LedgerScope(
                company_id=prepared.request.company_id,
                principal_id=prepared.request.actor_id,
                task_id=prepared.request.task_id,
                trace_id=prepared.request.trace_id,
            ),
            end_us=clock_us() - 1,
        )
    claim.assert_not_awaited()


async def test_exact_configured_c_task_required_before_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value, prepared, _ = runtime_case(tmp_path)
    from nexus.execution import coding_preparation as module

    monkeypatch.setattr(module, "clock_now", AsyncMock(return_value=datetime.now(UTC)))
    claim = AsyncMock(side_effect=AssertionError("caller cannot claim a different task"))
    monkeypatch.setattr(value.execution, "claim", claim)
    with pytest.raises(ValueError):
        await prepare_work(
            value,
            LedgerScope(
                company_id=prepared.request.company_id,
                principal_id=prepared.request.actor_id,
                task_id=UUID(int=9001),
                trace_id=prepared.binding.trace_id,
            ),
            end_us=clock_us() + 10_000_000,
        )
    claim.assert_not_awaited()


async def test_preapproval_quote_does_not_require_or_create_accounting_totals(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from decimal import Decimal
    from typing import cast
    from unittest.mock import MagicMock

    from sqlalchemy.ext.asyncio import AsyncSession

    from nexus.company.directory_models import RegisteredWork
    from nexus.execution import coding_context as module
    from nexus.execution.runtime_models import ExecutionWork
    from nexus.harness.journal_models import CompanyControl

    value, prepared, _ = runtime_case(tmp_path)
    work = ExecutionWork(company_id=prepared.request.company_id, task_id=prepared.request.task_id)
    control = CompanyControl(
        company_id=work.company_id, daily_cap_usd=Decimal(2), work_cap_usd=Decimal(3)
    )
    registered = RegisteredWork(
        company_id=work.company_id,
        task_id=work.task_id,
        active=True,
        allocation_usd=Decimal(5),
        delegated_usd=Decimal(1),
    )
    session = MagicMock(spec=AsyncSession)
    session.get = AsyncMock(
        side_effect=lambda model, key: registered if model is RegisteredWork else None
    )
    routed = object()
    captured = []

    def route(*args: object) -> object:
        captured.append(args[-2])
        return routed

    monkeypatch.setattr(module, "route_prepared", route)
    assert (
        await module.quote_locked(
            value, cast(AsyncSession, session), control, work, prepared, datetime.now(UTC)
        )
        is routed
    )
    assert captured == [Decimal(2)]
    session.add.assert_not_called()
    session.flush.assert_not_awaited()


async def test_real_c_producer_orders_actual_actor_claim_saved_input_pending_then_wait(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Native/source/save delivery supplied; real preparation builds the full immutable C input."""
    from nexus.company.access import VerifiedIdentity
    from nexus.company.brain.base import BrainReadScope
    from nexus.company.brain.context import AssembledContext, ContextSelection
    from nexus.company.contracts.actions import ActionProposal
    from nexus.company.management.coding_prepared_contracts import CodingPreparedRef
    from nexus.company.management.coding_prepared_store import CodingPreparedStore
    from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
    from nexus.core.llm.company_pricing import CostQuote, quote_cost
    from nexus.execution import coding_preparation as module
    from nexus.execution.coding_context import CodingState
    from nexus.execution.coding_operation import CodingOperation
    from nexus.execution.runtime_contracts import ExecutionLease, ExecutionSnapshot
    from nexus.execution.runtime_support import snapshot
    from nexus.harness.canonical import action_hash
    from nexus.harness.journal_contracts import ActionRecord
    from nexus.harness.lifecycle import ActionState
    from nexus.harness.model_authorizer_contracts import model_action_parameters
    from nexus.tests.unit.coding_runtime_fixture import description, native_work

    value, prepared, lease = runtime_case(tmp_path)
    events = []
    work = native_work(value, lease)

    async def claim(*args: object, **kwargs: object) -> ExecutionLease:
        events.append("claim")
        return lease

    async def initial(*args: object) -> CodingState:
        return CodingState(
            snapshot(work),
            prepared.binding.goal,
            prepared.binding.plan.plan_id,
            prepared.binding.plan,
            "p1",
            datetime.now(UTC),
            clock_us(),
        )

    async def assemble(
        scope: BrainReadScope, identity: VerifiedIdentity, selection: ContextSelection
    ) -> AssembledContext:
        assert identity.principal_id == lease.actor_id and selection == value.selection
        events.append("assemble")
        return AssembledContext.model_validate_json(
            prepared.context.model_copy(
                update={
                    "manifest": prepared.context.manifest.model_copy(
                        update={"operation_id": scope.operation_id, "trace_id": scope.trace_id}
                    )
                }
            ).model_dump_json()
        )

    async def save(
        self: CodingPreparedStore,
        actual_lease: ExecutionLease,
        credential: AuthenticatedWorkerIdentity,
        captured: PreparedCodingRequest,
        *,
        end_us: int,
    ) -> CodingPreparedRef:
        assert actual_lease == lease and credential.identity.principal_id == lease.actor_id
        assert captured.admission_sha256 == prepared.admission_sha256
        assert captured.sources == value.code_sources and end_us <= clock_us() + 10_000_000
        events.append("save-source-proof-delivery")
        return description(value, captured).reference

    async def pending(
        operation: CodingOperation, captured: PreparedCodingRequest, reference: CodingPreparedRef
    ) -> tuple[ActionRecord, CostQuote]:
        events.append("pending")
        model = next(
            row
            for row in value.management.catalog.models.models
            if row.registry_id == value.registry_id
        )
        assert model.price is not None
        quote = quote_cost(model.price, captured.request.bounds, now=datetime.now(UTC))
        proposal = ActionProposal(
            company_id=lease.company_id,
            action_id=captured.request.action_id,
            task_id=lease.task_id,
            trace_id=lease.trace_id,
            actor_id=lease.actor_id,
            revision=1,
            tool="model.request.v1",
            tool_version="v1",
            resource="model:" + value.registry_id,
            parameters=model_action_parameters(captured.request, value.recipe),
            preconditions=(reference.condition,),
            policy_version="p1",
            price_version=captured.request.price_version,
            estimated_cost_usd=quote.amount_usd,
        )
        return ActionRecord(
            company_id=lease.company_id,
            proposal=proposal,
            proposal_hash=action_hash(proposal),
            state=ActionState.AWAITING_APPROVAL,
            approval=None,
            consumed_at=None,
        ), quote

    async def wait(
        actual: ExecutionLease, identity: VerifiedIdentity, action_id: UUID
    ) -> ExecutionSnapshot:
        assert actual == lease and identity.principal_id == lease.actor_id
        events.append("owner-wait")
        return snapshot(work).model_copy(
            update={
                "state": "awaiting_approval",
                "worker_id": None,
                "lease_principal_id": None,
                "expires_at": None,
                "fence": lease.fence + 1,
                "waiting_action_id": action_id,
            }
        )

    monkeypatch.setattr(
        module, "clock_now", AsyncMock(side_effect=lambda _services: datetime.now(UTC))
    )
    monkeypatch.setattr(value.execution, "claim", claim)
    monkeypatch.setattr(module, "_initial", initial)
    monkeypatch.setattr(value.contexts, "assemble", assemble)
    monkeypatch.setattr(CodingPreparedStore, "save_worker", save)
    monkeypatch.setattr(module, "_pending", pending)
    monkeypatch.setattr(value.execution, "await_approval", wait)
    release = AsyncMock(side_effect=AssertionError("Owner wait already released its real lease"))
    monkeypatch.setattr(value.execution, "release", release)
    result = await prepare_work(
        value,
        LedgerScope(
            company_id=lease.company_id,
            principal_id=lease.actor_id,
            task_id=lease.task_id,
            trace_id=lease.trace_id,
        ),
        end_us=clock_us() + 10_000_000,
    )
    assert events == ["claim", "assemble", "save-source-proof-delivery", "pending", "owner-wait"]
    assert result.work.worker_id is None and result.action.approval is None
    assert not result.company_completed and "old\\n" not in result.model_dump_json()
    release.assert_not_awaited()


async def test_registered_c_slice_cannot_afford_real_whole_input_quote(tmp_path: Path) -> None:
    """Actual price/ceiling/route denial; supplied SQL row is not real DB admission evidence."""
    from decimal import Decimal
    from typing import cast
    from unittest.mock import MagicMock

    from sqlalchemy.ext.asyncio import AsyncSession

    from nexus.company.directory_models import RegisteredWork
    from nexus.core.llm.company_pricing import quote_cost
    from nexus.core.llm.company_routing import RoutingDeniedError
    from nexus.execution.coding_context import quote_locked
    from nexus.harness.journal_models import CompanyControl
    from nexus.tests.unit.coding_runtime_fixture import native_work

    value, prepared, lease = runtime_case(tmp_path)
    work = native_work(value, lease)
    admission = value.management.catalog.nexus_coding_admission
    assert admission is not None
    child = admission.slots[1].child
    row = next(
        row
        for row in value.management.catalog.models.models
        if row.registry_id == value.registry_id
    )
    assert row.price is not None
    actual = quote_cost(row.price, prepared.request.bounds, now=datetime.now(UTC))
    assert child.allocation_usd == Decimal("0.1") and actual.amount_usd == Decimal("1.049088")
    registered = RegisteredWork(
        company_id=work.company_id,
        task_id=work.task_id,
        active=True,
        allocation_usd=child.allocation_usd,
        delegated_usd=Decimal(0),
    )
    session = MagicMock(spec=AsyncSession)
    session.get = AsyncMock(
        side_effect=lambda model, key: registered if model is RegisteredWork else None
    )
    control = CompanyControl(
        company_id=work.company_id,
        daily_cap_usd=Decimal(5),
        work_cap_usd=Decimal(5),
        policy_version="p1",
        price_version=prepared.request.price_version,
    )
    with pytest.raises(RoutingDeniedError):
        await quote_locked(
            value, cast(AsyncSession, session), control, work, prepared, datetime.now(UTC)
        )
    session.add.assert_not_called()
    session.flush.assert_not_awaited()

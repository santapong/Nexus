"""Closed C recovery cannot borrow the existing ordinary/Planning recovery gate."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid5

import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.builder.contained_query import clock_us
from nexus.company.access import CompanyControlScope
from nexus.core.llm.company_pricing import CostQuote, quote_cost
from nexus.execution.coding_operation import CodingOperation
from nexus.execution.coding_owner_reads import CodingOwnerReader
from nexus.execution.coding_preparation_recovery import (
    PreparedCodingWaitRecovery,
    recover_prepared_wait,
)
from nexus.execution.runtime_approval_recovery import (
    recovery_scope,
    require_unissued_pending,
    restore_wait_locked,
)
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import registration_digest, snapshot
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CompanyControl, JournalAction
from nexus.harness.journal_submission import pending_action_record
from nexus.tests.unit.coding_application_fixture import application
from nexus.tests.unit.coding_runtime_fixture import native_work, services_from_store
from nexus.tests.unit.nexus_report_fixture import credentials
from nexus.tests.unit.test_coding_intent import prepared_case, witness
from nexus.tests.unit.test_coding_prepared_store import saved_case


@dataclass
class RecoveryCase:
    check: PreparedCodingWaitRecovery
    session: AsyncSession
    control: CompanyControl
    work: ExecutionWork
    action: JournalAction
    quote: CostQuote


async def recovery_case(root: Path, monkeypatch: pytest.MonkeyPatch) -> RecoveryCase:
    """Real dual H seals/Git files; CAS SQL and source/finance validation are supplied.

    Cohesion exception: both actual store seals and original native CAS rows
    remain in one fixture so a substitute DTO cannot become a recovery check.
    This wait-only writer fixture never spends/funds the unchanged0.1USD slice.
    """
    from nexus.company.management import coding_prepared_store as protected
    from nexus.execution import runtime_approval_recovery as module

    original, prepared, lease, actor, delivery = await saved_case(root, monkeypatch)
    services = services_from_store(
        root, original, prepared, lease, httpx2.MockTransport(lambda _: httpx2.Response(500))
    )
    admission = services.management.catalog.nexus_coding_admission
    assert admission is not None and delivery.action is not None
    owner = await credentials(admission.procedure.binding).current(admission.procedure.binding)
    scope = CompanyControlScope(
        company_id=admission.company_id,
        principal_id=owner.identity.principal_id,
        operation_id=UUID(int=9921),
        trace_id=UUID(int=9922),
    )
    brain = recovery_scope(admission.slots[1].child.binding, prepared.request.action_id)
    operation = CodingOperation(services, "finite-recovery-unit", clock_us() + 20_000_000)
    operation.credential = actor
    now = datetime.now(UTC)
    model = next(
        row
        for row in services.management.catalog.models.models
        if row.registry_id == prepared.request.registry_id
    )
    quote = quote_cost(model.price, prepared.request.bounds, now=now)
    assert quote.amount_usd > admission.slots[1].child.allocation_usd
    delivery.action = delivery.action.model_copy(update={"estimated_cost_usd": quote.amount_usd})
    delivery.control.policy_version = delivery.action.policy_version
    delivery.control.price_version = delivery.action.price_version
    monkeypatch.setattr(
        protected, "current_native", AsyncMock(side_effect=lambda *a, **k: delivery.native())
    )
    store = operation.prepared
    owner_loaded = await store.load_owner(
        scope, owner, prepared.request.action_id, end_us=operation.end
    )
    loaded = await store.load_actor(brain, actor, prepared.request.action_id, end_us=operation.end)
    operation.end = min(operation.end, owner_loaded.read_end_us, loaded.read_end_us)
    work = native_work(services, lease)
    work.lease_until = now - timedelta(seconds=1)
    work.segment_id = uuid5(work.run_id, "nexus-execution-segment-v1:1")
    proposal = delivery.action
    row = JournalAction(
        id=proposal.action_id,
        company_id=proposal.company_id,
        task_id=proposal.task_id,
        trace_id=proposal.trace_id,
        proposal_json=proposal.model_dump_json(),
        proposal_hash=action_hash(proposal),
        approval_json=None,
        consumed_at=None,
        state="awaiting_approval",
    )
    check = PreparedCodingWaitRecovery(
        operation,
        scope,
        owner,
        actor,
        brain,
        snapshot(work),
        pending_action_record(row),
        loaded,
        owner_loaded,
        prepared.binding.goal,
        prepared.binding.plan.plan_revision_id,
        CodingOwnerReader(services),
    )
    session = MagicMock(spec=AsyncSession)
    session.in_transaction.return_value = True
    result = MagicMock()
    result.all.return_value = [row]
    session.scalars = AsyncMock(return_value=result)
    session.scalar = AsyncMock(return_value=None)
    session.flush = AsyncMock()
    monkeypatch.setattr(module, "db_now", AsyncMock(return_value=now))
    monkeypatch.setattr(
        PreparedCodingWaitRecovery, "validate_locked", AsyncMock(return_value=quote)
    )
    return RecoveryCase(check, cast(AsyncSession, session), delivery.control, work, row, quote)


async def test_real_c_marker_and_dual_seals_enter_only_the_existing_wait_cas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = await recovery_case(tmp_path, monkeypatch)
    before = snapshot(f.work)
    original = f.action.proposal_json, f.action.approval_json
    try:
        result = await restore_wait_locked(
            f.check.services.execution, f.session, f.control, f.work, f.check
        )
        assert result.value.work.state == "awaiting_approval"
        assert result.value.work.counters == before.counters
        assert result.value.work.fence == before.fence + 1
        assert result.value.work.segment_number == before.segment_number
        assert result.value.work.waiting_action_id == f.action.id
        assert (f.action.proposal_json, f.action.approval_json) == original
        assert not result.value.company_completed and f.action.consumed_at is None
        again = replace(f.check, initial=snapshot(f.work))
        replay = await restore_wait_locked(
            f.check.services.execution, f.session, f.control, f.work, again
        )
        assert result == replay
        cast(MagicMock, f.session).flush.assert_awaited_once()
        cast(MagicMock, f.session).add.assert_not_called()
    finally:
        f.check.operation.finish()


@pytest.mark.parametrize("fault", ["live", "issued", "used", "delegated", "ordinary"])
async def test_c_recovery_prefix_never_resets_live_issued_or_other_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    f = await recovery_case(tmp_path, monkeypatch)
    if fault == "live":
        f.work.lease_until = datetime.now(UTC) + timedelta(seconds=10)
    elif fault == "issued":
        cast(MagicMock, f.session).scalar.return_value = UUID(int=9910)
    elif fault == "used":
        f.work.model_requests_used = 1
    elif fault == "delegated":
        f.work.tool_attempts_delegated = 1
    else:
        f.work.workflow_name = "ordinary.coding"
        registered = f.check.initial.registration.model_copy(
            update={"workflow_name": f.work.workflow_name}
        )
        f.work.registration_json = registered.model_dump_json()
        f.work.registration_hash = registration_digest(registered)
    before = snapshot(f.work)
    try:
        with pytest.raises(ValueError):
            await require_unissued_pending(
                f.session, f.control, f.work, f.action.id, f.action.proposal_hash, datetime.now(UTC)
            )
        assert snapshot(f.work) == before
        cast(MagicMock, f.session).flush.assert_not_awaited()
    finally:
        f.check.operation.finish()


async def test_c_recovery_expiry_during_flush_starts_no_later_native_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = await recovery_case(tmp_path, monkeypatch)

    async def expire() -> None:
        f.check.operation.end = clock_us() - 1

    fake = cast(MagicMock, f.session)
    fake.flush.side_effect = expire
    try:
        with pytest.raises(TimeoutError):
            await restore_wait_locked(
                f.check.services.execution, f.session, f.control, f.work, f.check
            )
        assert fake.scalars.await_count == 1 and fake.scalar.await_count == 4
    finally:
        # Supplied transport is not evidence of database rollback/persistence.
        f.check.operation.finish()


async def test_c_recovery_rejects_actor_as_owner_before_native_or_private_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = application(tmp_path)
    prepared, _, _, _ = prepared_case()
    actor = await witness(prepared)
    native = AsyncMock()
    monkeypatch.setattr(app.services.execution, "recover_prepared_wait", native)
    scope = CompanyControlScope(
        company_id=app.config.catalog.company_id,
        principal_id=actor.identity.principal_id,
        operation_id=UUID(int=901),
        trace_id=UUID(int=902),
    )
    with pytest.raises(ValueError):
        await recover_prepared_wait(
            app.services,
            scope,
            actor,
            prepared.request.action_id,
            "a" * 64,
            expected_goal=app.config.goal,
            expected_current_revision_id=prepared.binding.plan.plan_revision_id,
            end_us=clock_us() + 5_000_000,
        )
    native.assert_not_awaited()

"""New concrete config/action checks; base native delegation is mocked, not SQL-qualified."""

from copy import copy
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from nexus.company.notifications.mixed_worker_intent import (
    MixedCredentialNotificationIntentCheck,
    require_mixed_notification_intent_check,
)
from nexus.company.notifications.worker_guard import NotificationOperationGuard
from nexus.company.notifications.worker_intent import CredentialNotificationIntentCheck
from nexus.execution.intent_checks import BeforeIntentCheck
from nexus.tests.unit.mixed_notification_fixture import mixed_case


@pytest.mark.parametrize(
    "drift", ["factory", "artifacts", "freshness", "catalog", "policy", "replacement", "frozen"]
)
async def test_actual_managed_wrapper_preparation_stays_bound_through_final_clock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, drift: str
) -> None:
    from nexus.company.notifications.managed_admission import ManagedNotificationAdmission
    from nexus.company.notifications.managed_effects import ManagedNotificationIntent
    from nexus.harness.journal_models import JournalAction
    from nexus.tests.unit.mixed_notification_history_fixture import history_case

    case = history_case(tmp_path)
    check = case.mixed.check
    preparation = case.mixed.original.managed_effects.preparation
    admitted = MagicMock(spec=ManagedNotificationAdmission)
    admitted.deadlines = ()
    # Existing SQL/slot/admission delivery is mocked; actual mixed/final wrapper methods execute.
    monkeypatch.setattr(CredentialNotificationIntentCheck, "validate", AsyncMock())
    monkeypatch.setattr(CredentialNotificationIntentCheck, "validate_time", lambda *_: None)
    monkeypatch.setattr(preparation, "admit", AsyncMock(return_value=admitted))
    wrapper = ManagedNotificationIntent(check, preparation)
    action = case.stored[(JournalAction, case.command.action_id)]
    assert isinstance(action, JournalAction)
    await wrapper.validate(case.session, case.control, case.work, action, case.clock)
    wrapper.validate_time(case.clock)
    if drift == "frozen":
        wrapper.frozen = CredentialNotificationIntentCheck(
            check.lease,
            check.witness,
            check.draft_id,
            check.drafts,
            check.target,
            check.resource_symbol,
        )
    elif drift == "replacement":
        wrapper.preparation = copy(preparation)
    elif drift == "catalog":
        preparation.catalog = preparation.catalog.model_copy(update={"cycle_admission": None})
    elif drift == "policy":
        preparation.policy = preparation.policy.model_copy(update={"resource_symbol": "foreign"})
    else:
        setattr(preparation, drift, MagicMock())
    with pytest.raises(ValueError):
        wrapper.validate_time(case.clock)


@pytest.mark.parametrize(
    "change", ["matching", "missing", "noop", "subclass", "wrong_action", "foreign_preparation"]
)
def test_required_fresh_shape_never_accepts_noop_or_crossed_operation(
    tmp_path: Path, change: str
) -> None:
    from decimal import Decimal

    from nexus.company.contracts.actions import ActionProposal
    from nexus.company.notifications.managed_effects import ManagedNotificationIntent
    from nexus.company.notifications.proposals import (
        NOTIFICATION_TOOL,
        NotificationDispatchParameters,
    )
    from nexus.execution.runtime_models import ExecutionWork
    from nexus.harness.canonical import action_hash
    from nexus.harness.journal_models import JournalAction

    case = mixed_case(tmp_path)
    params = NotificationDispatchParameters(
        draft_id=case.draft_id, payload_sha256="a" * 64, recipient_policy_sha256="b" * 64
    )
    proposal = ActionProposal(
        company_id=case.lease.company_id,
        action_id=case.action_id,
        task_id=case.lease.task_id,
        trace_id=case.lease.trace_id,
        actor_id=case.lease.actor_id,
        revision=1,
        tool=NOTIFICATION_TOOL,
        tool_version="v1",
        resource=case.check.resource_symbol,
        parameters=params.model_dump(mode="json"),
        policy_version="p1",
        price_version="p1",
        estimated_cost_usd=Decimal(".01"),
    )
    row = JournalAction(
        id=case.action_id,
        company_id=proposal.company_id,
        task_id=proposal.task_id,
        trace_id=proposal.trace_id,
        proposal_json=proposal.model_dump_json(),
        proposal_hash=action_hash(proposal),
    )
    work = ExecutionWork(
        company_id=case.lease.company_id,
        task_id=case.lease.task_id,
        trace_id=case.lease.trace_id,
        run_id=case.lease.run_id,
        actor_id=case.lease.actor_id,
        workspace_id=case.lease.workspace_id,
        model_profile="notification.native.v1",
        model_requests_limit=0,
        model_requests_used=0,
        model_requests_delegated=0,
    )
    check = case.check
    if change == "subclass":

        class Noop(MixedCredentialNotificationIntentCheck):
            pass

        check = object.__new__(Noop)
    wrapper = ManagedNotificationIntent(check, case.original.managed_effects.preparation)
    supplied: BeforeIntentCheck | None = wrapper
    if change == "missing":
        supplied = None
    elif change == "noop":
        supplied = MagicMock()
    elif change == "wrong_action":
        row.id = UUID(int=999)
    elif change == "foreign_preparation":
        wrapper.preparation.factory = MagicMock()
    if change == "matching":
        require_mixed_notification_intent_check(
            case.reads.facts.catalog, work, case.lease, case.guard.witness.identity, row, supplied
        )
    else:
        with pytest.raises(ValueError):
            require_mixed_notification_intent_check(
                case.reads.facts.catalog,
                work,
                case.lease,
                case.guard.witness.identity,
                row,
                supplied,
            )


def test_concrete_check_binds_original_action_and_current_pins(tmp_path: Path) -> None:
    case = mixed_case(tmp_path)
    case.check.require_current(case.now)
    assert case.check.witness is case.guard.witness
    assert case.check.operation_guard is case.guard


@pytest.mark.parametrize(
    "change", ["action", "draft", "bare_guard", "factory", "catalog", "target"]
)
def test_crossed_configuration_denies_before_native_slot(tmp_path: Path, change: str) -> None:
    case = mixed_case(tmp_path)
    action, draft, guard, target = case.action_id, case.draft_id, case.guard, case.check.target
    if change == "action":
        action = UUID(int=999)
    elif change == "draft":
        draft = UUID(int=999)
    elif change == "bare_guard":
        guard = cast(NotificationOperationGuard, case.guard.witness.identity)
    elif change == "factory":
        case.reads.facts.artifacts.factory = MagicMock()
    elif change == "catalog":
        object.__setattr__(
            case.reads.facts,
            "catalog",
            case.reads.facts.catalog.model_copy(update={"cycle_admission": None}),
        )
    else:
        target = target.model_copy(update={"resource_id": UUID(int=999)})
    with pytest.raises(ValueError):
        MixedCredentialNotificationIntentCheck(
            case.lease,
            case.guard.witness,
            draft,
            case.reads.drafts,
            target,
            case.check.resource_symbol,
            action_id=action,
            operation_guard=guard,
            reads=case.reads,
        )


@pytest.mark.parametrize("which", ["file", "credential", "config"])
def test_late_final_clock_keeps_original_config_and_witness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, which: str
) -> None:
    case = mixed_case(tmp_path)
    monkeypatch.setattr(CredentialNotificationIntentCheck, "validate_time", lambda self, now: None)
    now = case.now
    if which == "file":
        case.path.unlink()
    elif which == "credential":
        now = case.guard.witness.expires_at
    else:
        now = case.guard.registration.expires_at
    with pytest.raises(ValueError):
        case.check.validate_time(now)


async def test_actual_base_delegates_then_closes_after_last_clock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nexus.company.notifications import mixed_worker_intent as module
    from nexus.harness.journal_models import CompanyControl

    case = mixed_case(tmp_path)
    base = AsyncMock()
    monkeypatch.setattr(CredentialNotificationIntentCheck, "validate", base)
    monkeypatch.setattr(
        module, "db_now", AsyncMock(return_value=case.guard.registration.expires_at)
    )
    row = MagicMock(
        id=case.action_id,
        company_id=case.lease.company_id,
        task_id=case.lease.task_id,
        trace_id=case.lease.trace_id,
    )
    work = MagicMock(
        company_id=case.lease.company_id,
        actor_id=case.lease.actor_id,
        workspace_id=case.lease.workspace_id,
        task_id=case.lease.task_id,
        trace_id=case.lease.trace_id,
        run_id=case.lease.run_id,
    )
    control = CompanyControl(company_id=case.lease.company_id, owner_id=case.lease.actor_id)
    with pytest.raises(ValueError):
        await case.check.validate(MagicMock(), control, work, row, case.now)
    assert base.await_count == 1

"""Recorded-family metadata is not fresh permission; no source bodies or mutation queries."""

from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest

from nexus.company.directory_models import DirectoryMembership, RegisteredWork
from nexus.company.management.plan_models import ManagementOwnerDecision, ManagementRevisionEvent
from nexus.company.notifications.dispatch_models import NotificationDispatchRow
from nexus.execution.mixed_notification_history import require_recorded_cycle_sender_family_locked
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt, ExecutionWork
from nexus.tests.unit.mixed_notification_history_fixture import HistoryCase, history_case


async def check(case: HistoryCase) -> None:
    await require_recorded_cycle_sender_family_locked(
        case.session,
        case.control,
        case.work,
        case.mixed.guard,
        case.command,
        case.mixed.reads.facts.catalog,
    )


async def test_known_issued_paused_inactive_family_is_metadata_only_and_keeps_original_fence(
    tmp_path: Path,
) -> None:
    case = history_case(tmp_path)
    before = deepcopy(
        [{k: v for k, v in row.__dict__.items() if not k.startswith("_sa_")} for row in case.rows]
    )
    await check(case)
    assert [
        {k: v for k, v in row.__dict__.items() if not k.startswith("_sa_")} for row in case.rows
    ] == before
    assert case.work.fence == 3
    for method in ("add", "add_all", "flush", "commit", "begin", "execute"):
        getattr(case.session, method).assert_not_called()


@pytest.mark.parametrize("role", ["root", "strategy", "engineering"])
@pytest.mark.parametrize("field", ["actor_id", "workspace_id"])
async def test_recorded_execution_rows_retain_actual_actor_and_workspace(
    tmp_path: Path, role: str, field: str
) -> None:
    case = history_case(tmp_path)
    admission = case.mixed.reads.facts.catalog.cycle_admission
    assert admission is not None
    binding = (
        admission.procedure.binding
        if role == "root"
        else admission.slots[0 if role == "strategy" else 2].child.binding
    )
    row = next(
        r for r in case.rows if isinstance(r, ExecutionWork) and r.task_id == binding.task_id
    )
    original_hash = row.registration_hash
    setattr(row, field, UUID(int=999))
    with pytest.raises(ValueError):
        await check(case)
    assert row.registration_hash == original_hash


async def test_actual_issued_sender_cannot_report_an_unconsumed_tool_counter(
    tmp_path: Path,
) -> None:
    case = history_case(tmp_path)
    assert case.work.tool_attempts_limit == case.work.tool_attempts_used == 1
    case.work.tool_attempts_used = 0
    with pytest.raises(ValueError):
        await check(case)


@pytest.mark.parametrize(
    "change",
    [
        "missing_intent",
        "missing_slot",
        "missing_attempt",
        "attempt_fence",
        "slot_fence",
        "hash",
        "extra_inactive",
        "quota",
        "root_used",
        "delegated",
        "event",
        "decision",
        "decision_late",
        "member",
        "foreign_owner",
        "unissued",
        "command",
        "config",
    ],
)
async def test_crossed_or_unissued_history_never_substitutes_permission(
    tmp_path: Path, change: str
) -> None:
    case = history_case(tmp_path)
    company = case.work.company_id
    if change.startswith("missing_"):
        typ, key = {
            "missing_intent": (EffectIntent, (company, case.command.action_id)),
            "missing_slot": (NotificationDispatchRow, (company, case.mixed.draft_id)),
            "missing_attempt": (
                ExecutionAttempt,
                (company, case.work.task_id, case.command.action_id),
            ),
        }[change]
        case.stored.pop((typ, key))
    elif change in {"attempt_fence", "slot_fence"}:
        typ = ExecutionAttempt if change == "attempt_fence" else NotificationDispatchRow
        row = next(r for r in case.rows if isinstance(r, typ))
        setattr(row, "fence" if typ is ExecutionAttempt else "intent_fence", 2)
    elif change == "hash":
        case.work.registration_hash = "f" * 64
    elif change == "extra_inactive":
        extra = deepcopy(next(r for r in case.rows if isinstance(r, RegisteredWork)))
        extra.task_id = UUID(int=999)
        case.rows.append(extra)
    elif change == "quota":
        case.work.tool_attempts_limit += 1
    elif change == "root_used":
        next(
            r for r in case.rows if isinstance(r, ExecutionWork) and r.parent_task_id is None
        ).model_requests_used = 1
    elif change == "delegated":
        next(
            r for r in case.rows if isinstance(r, ExecutionWork) and r.parent_task_id is None
        ).model_requests_delegated += 1
    elif change == "event":
        next(r for r in case.rows if isinstance(r, ManagementRevisionEvent)).revision_counter = 2
    elif change == "decision":
        next(
            r
            for r in case.rows
            if isinstance(r, ManagementOwnerDecision) and r.decision_id == UUID(int=1802)
        ).payload_sha256 = "f" * 64
    elif change == "decision_late":
        next(
            r
            for r in case.rows
            if isinstance(r, ManagementOwnerDecision) and r.decision_id == UUID(int=1802)
        ).recorded_at = case.clock + timedelta(seconds=10)
        next(r for r in case.rows if isinstance(r, ManagementRevisionEvent)).recorded_at = (
            case.clock + timedelta(seconds=10)
        )
    elif change == "member":
        next(r for r in case.rows if isinstance(r, DirectoryMembership)).membership_active = False
    elif change == "foreign_owner":
        case.control.owner_id = UUID(int=999)
    elif change == "unissued":
        next(r for r in case.rows if isinstance(r, EffectIntent)).state = "not_issued"
    elif change == "command":
        case.command = case.command.model_copy(update={"action_id": UUID(int=999)})
    else:
        case.mixed.path.unlink()
    with pytest.raises(ValueError):
        await check(case)

"""Pure comparisons on store-resolved cycle rows; no lookup, permission or call authority."""

from nexus.company.contracts.work import WorkItem
from nexus.company.directory_models import RegisteredWork
from nexus.company.management.cycle_admission_contracts import StockFlowCycleAdmission
from nexus.company.management.plan_registration import registration
from nexus.execution.runtime_contracts import ExecutionDeniedError, ExecutionRegistration
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import KINDS, snapshot


def _require(value: bool) -> None:
    if not value:
        raise ExecutionDeniedError("Current mixed-cycle partition is unavailable")


def _same(row: object, fields: str, expected: tuple[object, ...]) -> bool:
    """Compare a fixed internal ORM field projection without granting caller-selected scope."""
    return tuple(getattr(row, name) for name in fields.split()) == expected


def _execution(row: ExecutionWork, expected: ExecutionRegistration) -> None:
    current = snapshot(row)
    # snapshot validates the original stored digest; equal Decimal scales keep those original bytes.
    _require(current.registration == expected)
    for kind in KINDS:
        limit, used, delegated = (
            getattr(row, f"{kind}_{name}") for name in ("limit", "used", "delegated")
        )
        _require(type(limit) is type(used) is type(delegated) is int)
        _require(
            limit == getattr(expected.quota, kind)
            and used >= 0
            and delegated >= 0
            and used + delegated <= limit
        )


def _root(
    admission: StockFlowCycleAdmission,
    directory: RegisteredWork,
    work: ExecutionWork,
) -> None:
    # This >50-line pure check couples the complete immutable root and its nonexecution state.
    root = admission.procedure
    bound = root.binding
    item = WorkItem(
        company_id=admission.company_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        goal_id=root.goal_id,
        department="management",
        title="Non-executing goal procedure allocation",
        acceptance=("management.non-executing-allocation.v1",),
        budget_usd=root.allocation_usd,
    )
    _execution(work, registration(bound, item, root.quota))
    _require(
        _same(
            directory,
            "company_id workspace_id actor_id trace_id parent_task_id "
            "root_task_id allocation_usd active",
            (
                admission.company_id,
                bound.workspace_id,
                bound.actor_id,
                bound.trace_id,
                None,
                bound.task_id,
                root.allocation_usd,
                True,
            ),
        )
    )
    _require(
        work.parent_task_id is None
        and work.workspace_id == bound.workspace_id
        and work.actor_id == bound.actor_id
    )
    _require(
        _same(
            work,
            "state fence segment_number worker_id lease_until segment_id "
            "waiting_action_id lease_mode lease_principal_id",
            ("eligible", 0, 0, None, None, None, None, None, None),
        )
    )
    _require(
        _same(
            work,
            "model_requests_used tool_attempts_used rework_rounds_used plan_revisions_used",
            (0, 0, 0, 1),
        )
    )

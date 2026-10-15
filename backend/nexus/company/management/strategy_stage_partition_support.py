"""Pure original-stage row comparison; no lookup, allocation or grant."""

from nexus.company.contracts.work import WorkItem
from nexus.company.directory_models import RegisteredWork
from nexus.company.management.cycle_admission_contracts import StockFlowCycleAdmission
from nexus.company.management.plan_registration import registration
from nexus.execution.cycle_partition_support import _execution, _require, _same
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import KINDS


def _root(
    admission: StockFlowCycleAdmission,
    directory: RegisteredWork,
    work: ExecutionWork,
) -> None:
    # Keep this >50-line root comparison cohesive; the full-stage gate requires revision1 used.
    root, bound = admission.procedure, admission.procedure.binding
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
        _same(
            work,
            "parent_task_id workspace_id actor_id state fence segment_number worker_id lease_until "
            "segment_id waiting_action_id lease_mode lease_principal_id",
            (
                None,
                bound.workspace_id,
                bound.actor_id,
                "eligible",
                0,
                0,
                None,
                None,
                None,
                None,
                None,
                None,
            ),
        )
    )
    _require(all(getattr(work, f"{kind}_used") == 0 for kind in KINDS))
    _require(directory.delegated_usd == sum(s.child.allocation_usd for s in admission.slots[:2]))
    for kind in KINDS:
        _require(
            getattr(work, f"{kind}_delegated")
            == sum(getattr(slot.child.quota, kind) for slot in admission.slots[:2])
        )

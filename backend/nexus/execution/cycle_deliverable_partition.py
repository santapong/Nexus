"""Closed P/PV/C/CV observations; no admission, execution permit or quota mutation."""

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.cycle_artifacts.common import CycleKind, criteria_for
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.cycle_admission import validate_stockflow_cycle_configuration
from nexus.company.management.cycle_admission_contracts import StockFlowCycleAdmission
from nexus.company.management.lifecycle import PlanRevision
from nexus.company.management.report_input_contracts import native_author
from nexus.core.llm.company_registry import ModelRegistry
from nexus.execution.cycle_partition_checks import read_current_cycle_family_locked
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.journal_models import CompanyControl


async def require_cycle_deliverable_partition_locked(
    session: AsyncSession,
    control: CompanyControl,
    work: ExecutionWork,
    identity: VerifiedIdentity,
    *,
    admission: StockFlowCycleAdmission,
    registry: ModelRegistry,
) -> PlanRevision:
    checked = validate_stockflow_cycle_configuration(admission, registry)
    binding, registration = native_author(work)
    matched = tuple(slot for slot in checked.slots[4:8] if slot.child.binding == binding)
    require_acceptance(len(matched) == 1)
    for offset in range(4, 8):
        slot = checked.slots[offset]
        kind: CycleKind = "presentation" if offset < 6 else "support"
        require_acceptance(slot.work.acceptance == criteria_for(kind))
    selected = matched[0]
    require_acceptance(
        registration.work == selected.work and registration.quota == selected.child.quota
    )
    require_acceptance(
        type(work.model_requests_used) is int
        and 0 <= work.model_requests_used <= selected.child.quota.model_requests
        and type(work.model_requests_limit) is int
        and work.model_requests_limit == selected.child.quota.model_requests
        and type(work.model_requests_delegated) is int
        and work.model_requests_delegated == 0
    )
    return await read_current_cycle_family_locked(
        session, control, work, identity, admission=checked, registry=registry
    )

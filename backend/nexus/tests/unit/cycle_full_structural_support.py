"""Exact typed eleven-slot structural declarations; no runtime, model health or authority."""

from nexus.company.management.cycle_admission_contracts import StockFlowCycleAdmission
from nexus.company.management.plan_catalog import PlanAdmissionCatalog
from nexus.company.management.plans import PlanPayload
from nexus.company.strategy.contracts import STRATEGY_CHECK_CRITERIA
from nexus.tests.unit.cycle_admission_fixture import declared
from nexus.tests.unit.cycle_catalog_fixture import CycleCatalog, cycle_catalog


def configured() -> CycleCatalog:
    """Adapt only the two obsolete Strategy placeholders to the genuine six criteria."""
    original = cycle_catalog()
    slots = list(original.admission.slots)
    for index in (0, 1):
        slots[index] = slots[index].model_copy(
            update={
                "work": slots[index].work.model_copy(update={"acceptance": STRATEGY_CHECK_CRITERIA})
            }
        )
    admission = StockFlowCycleAdmission.model_validate(
        original.admission.model_copy(update={"slots": tuple(slots)}).model_dump()
    )
    catalog = PlanAdmissionCatalog.model_validate(
        original.catalog.model_dump() | {"cycle_admission": admission}
    )
    return CycleCatalog(admission, catalog)


def full() -> tuple[PlanAdmissionCatalog, PlanPayload]:
    """Only pure catalog/layout matching; both native action boundaries still required."""
    current = configured()
    return current.catalog, declared(current.admission, 2)

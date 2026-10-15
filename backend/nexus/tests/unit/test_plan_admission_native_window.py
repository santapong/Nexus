"""Exact no-model descriptions and real full capture still require current governance."""

from uuid import UUID

import pytest
from pydantic import ValidationError

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.management.plan_admission_candidates import capture_child_window
from nexus.company.management.plan_admission_capture import capture_plan_admission_locked
from nexus.company.management.plan_catalog import NamedPlanResource, PlanAdmissionCatalog
from nexus.company.management.transactions import ManagementDeniedError
from nexus.harness.journal_models import CompanyControl
from nexus.tests.unit.cycle_admission_fixture import declared
from nexus.tests.unit.cycle_catalog_fixture import cycle_catalog
from nexus.tests.unit.plan_admission_fixture_data import NOW, ordinary_fixture
from nexus.tests.unit.plan_admission_fixture_session import MetadataSession, qualifier
from nexus.tests.unit.plan_admission_witness_fixture import bound_witness


@pytest.mark.parametrize("index,kind", [(2, "native"), (3, "native"), (10, "sender")])
def test_real_exact_no_model_branch_needs_no_model_health_or_price(index: int, kind: str) -> None:
    data = cycle_catalog()
    result = capture_child_window(data.catalog, data.admission.slots[index].child, NOW)
    assert result.kind == kind and not result.candidates and result.profile_sha256
    result.require_time(NOW)


def test_unselected_native_tuple_hash_is_checked_before_selecting_model_free_child() -> None:
    data = cycle_catalog()
    wrong = data.catalog.native_profiles[1].model_copy(update={"registry_sha256": "f" * 64})
    catalog = data.catalog.model_copy(
        update={"native_profiles": (data.catalog.native_profiles[0], wrong)}
    )
    with pytest.raises((ManagementDeniedError, ValidationError)):
        capture_child_window(catalog, data.admission.slots[2].child, NOW)


async def test_actual_full_mixed_capture_does_not_skip_real_governance_after_structural_match() -> (
    None
):
    data = cycle_catalog()
    admission = data.admission
    resources = {x.symbol: x for x in data.catalog.resources}
    for index, slot in enumerate(admission.slots):
        resources.setdefault(
            slot.tool.resource,
            NamedPlanResource(
                symbol=slot.tool.resource,
                resource=ResourceRef(
                    company_id=admission.company_id, resource_id=UUID(int=800 + index)
                ),
            ),
        )
    catalog = PlanAdmissionCatalog.model_validate(
        data.catalog.model_dump()
        | {"cycle_admission": admission, "resources": tuple(resources.values())}
    )
    bound = admission.procedure.binding
    control = CompanyControl(
        company_id=admission.company_id,
        owner_id=bound.actor_id,
        policy_version="fixture",
        price_version=catalog.models.pricebook_version,
        paused=False,
        daily_cap_usd=admission.procedure.allocation_usd,
        work_cap_usd=admission.procedure.allocation_usd,
    )
    db = MetadataSession(ordinary_fixture())
    identity = VerifiedIdentity(principal_id=bound.actor_id, workspace_id=bound.workspace_id)
    scope = CompanyControlScope(
        company_id=admission.company_id,
        principal_id=bound.actor_id,
        operation_id=UUID(int=7),
        trace_id=UUID(int=8),
    )
    with pytest.raises(ManagementDeniedError):
        await capture_plan_admission_locked(
            db.session,
            control,
            scope,
            identity,
            declared(admission, 2),
            catalog,
            qualifier(db.data),
            credential=await bound_witness(bound),
        )
    assert db.body_reads == 0

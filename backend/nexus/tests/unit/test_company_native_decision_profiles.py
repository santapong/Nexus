"""Decision deadlines retain exact native identity and ordinary model evidence gates."""

# TASK: Qualify each actual child before collecting model-only deadline windows.
# FILES: native_fact_admission.py and this focused test file.
# DONE: Exact configured native children need no fake model; other profiles remain gated.
# RISK: Admission boundary; retain complete tuple validation and actual PG denial receipt.

from datetime import timedelta

import pytest

from nexus.company.brain.native_fact_admission import registered_profile_deadline
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.tests.unit.test_company_model_observations import catalog, child, observed
from nexus.tests.unit.test_company_model_registry import NOW
from nexus.tests.unit.test_company_native_execution_profiles import mechanical
from nexus.tests.unit.test_company_notification_native_profiles import notification_plan


@pytest.mark.parametrize("kind", ["notification", "author", "verifier"])
def test_exact_configured_native_child_needs_no_model_deadline(kind: str) -> None:
    configured, payload = notification_plan() if kind == "notification" else mechanical()
    selected = payload.children[1 if kind == "verifier" else 0]
    assert configured.models.models == ()
    assert registered_profile_deadline(configured, selected, NOW) is None


@pytest.mark.parametrize("kind", ["notification", "author", "verifier"])
def test_native_profile_name_without_exact_configuration_does_not_bypass(kind: str) -> None:
    configured, payload = notification_plan() if kind == "notification" else mechanical()
    selected = payload.children[1 if kind == "verifier" else 0]
    missing = configured.model_copy(update={"native_profiles": (), "notification_profiles": ()})
    with pytest.raises(ValueError):
        registered_profile_deadline(missing, selected, NOW)


def test_corrupt_unselected_native_tuple_still_denies_decision_deadline() -> None:
    configured, payload = mechanical()
    configured = configured.model_copy(
        update={
            "native_profiles": (
                configured.native_profiles[0],
                configured.native_profiles[1].model_copy(update={"registry_sha256": "f" * 64}),
            )
        }
    )
    with pytest.raises(ValueError):
        registered_profile_deadline(configured, payload.children[0], NOW)


def test_ordinary_current_model_keeps_actual_finite_evidence_deadline() -> None:
    configured = catalog()
    expected = configured.models.models[0].health.expires_at
    assert registered_profile_deadline(configured, child(), NOW) == expected
    with pytest.raises(ValueError):
        registered_profile_deadline(configured, child(), expected)


def test_fresh_observation_deadline_does_not_rewrite_original_registration() -> None:
    configured = catalog()
    updated = PlanAdmissionCatalog.model_validate(
        configured.model_dump() | {"model_observations": (observed(),)}
    )
    assert registered_profile_deadline(updated, child(), NOW + timedelta(minutes=10)) == (
        observed().health.expires_at
    )
    assert updated.models == configured.models

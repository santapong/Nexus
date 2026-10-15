"""Native leaves have no model evaluations; ordinary full-plan profiles still require them."""

from datetime import timedelta

import pytest

from nexus.company.notifications.managed_sources import profile_deadlines
from nexus.tests.unit.strategy_transition_observation_fixture import transition_case


def test_full_plan_retains_ordinary_model_windows_without_native_evaluations() -> None:
    case = transition_case(2)
    dates = profile_deadlines(case.payload, case.catalog, case.now)
    assert len(dates) == 8
    assert all(date > case.now for date in dates)


def test_unselected_corrupt_native_profile_denies_before_any_skip() -> None:
    case = transition_case(2)
    profiles = case.catalog.native_profiles
    corrupt = profiles[-1].model_copy(update={"registry_sha256": "f" * 64})
    catalog = case.catalog.model_copy(update={"native_profiles": (*profiles[:-1], corrupt)})
    with pytest.raises(ValueError):
        profile_deadlines(case.payload, catalog, case.now)


def test_native_skip_cannot_rescue_expired_ordinary_profiles() -> None:
    case = transition_case(2)
    expired = max(row.health.expires_at for row in case.catalog.models.models) + timedelta(
        seconds=1
    )
    with pytest.raises(ValueError):
        profile_deadlines(case.payload, case.catalog, expired)

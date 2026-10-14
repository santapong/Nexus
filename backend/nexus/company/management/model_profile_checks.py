"""Current exact managed profile eligibility, independent of immutable work binding."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from nexus.company.management.model_observations import effective_model_registration
from nexus.company.management.native_execution_profiles import native_execution_profile
from nexus.company.management.plans import ChildAllocation
from nexus.company.management.transactions import ManagementDeniedError
from nexus.company.notifications.native_profile_checks import native_notification_profile

if TYPE_CHECKING:
    from nexus.company.management.plan_support import PlanAdmissionCatalog


def validate_model_profile(
    catalog: PlanAdmissionCatalog, child: ChildAllocation, now: datetime
) -> None:
    """Recheck explicit current evidence without renewing any registration or allowance."""
    engineering = native_execution_profile(catalog, child)
    notification = native_notification_profile(catalog, child)
    if engineering is not None or notification is not None:
        return
    binding = child.binding
    if (
        binding.model_registry_version != catalog.models.revision
        or binding.model_profile not in catalog.admitted_profiles
    ):
        raise ManagementDeniedError("Plan model/profile is not exactly registered")
    if not any(
        model.enabled
        and model.health.status == "healthy"
        and model.health.checked_at <= now < model.health.expires_at
        and any(
            e.profile == binding.model_profile
            and e.conformance_passed
            and e.evaluated_at <= now < e.expires_at
            for e in model.evaluations
        )
        for original in catalog.models.models
        for model in (
            effective_model_registration(catalog.models, catalog.model_observations, original),
        )
    ):
        raise ManagementDeniedError("Plan profile has no current registered model evidence")

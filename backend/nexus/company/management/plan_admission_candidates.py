"""Retain eligible alternatives; native/sender profiles never invent model evidence."""

from datetime import datetime

from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.model_observations import effective_model_registration
from nexus.company.management.model_profile_checks import validate_model_profile
from nexus.company.management.native_execution_profiles import native_execution_profile
from nexus.company.management.plan_admission_window import (
    PlanChildWindow,
    PlanModelCandidateWindow,
    require_window,
)
from nexus.company.management.plan_catalog import PlanAdmissionCatalog
from nexus.company.management.plans import ChildAllocation
from nexus.company.notifications.native_profile_checks import native_notification_profile
from nexus.execution.runtime_contracts import AttemptQuota


def capture_child_window(
    catalog: PlanAdmissionCatalog,
    child: ChildAllocation,
    now: datetime,
) -> PlanChildWindow:
    """Pure qualified observations, never a fallback selector/client or execution price quote."""
    # This >50-line closed branch preserves complete raw validation before no-model selection.
    AttemptQuota.model_validate(
        {name: getattr(child.quota, name) for name in AttemptQuota.model_fields}
    )
    checked = PlanAdmissionCatalog.model_validate(catalog.model_dump(warnings=False))
    child = ChildAllocation.model_validate(child.model_dump(warnings=False))
    require_window(len(checked.models.models) <= 32)
    validate_model_profile(checked, child, now)
    native = native_execution_profile(checked, child)
    sender = native_notification_profile(checked, child)
    if native is not None:
        return PlanChildWindow(child.binding, child.quota, "native", canonical_sha256(native), ())
    if sender is not None:
        return PlanChildWindow(child.binding, child.quota, "sender", canonical_sha256(sender), ())
    candidates = []
    for original in checked.models.models:
        effective = effective_model_registration(
            checked.models, checked.model_observations, original
        )
        if not effective.enabled or effective.health.status != "healthy":
            continue
        for evaluation in effective.evaluations:
            if evaluation.profile != child.binding.model_profile:
                continue
            candidate = PlanModelCandidateWindow(
                original.registry_id,
                canonical_sha256(original),
                canonical_sha256(effective),
                effective.health,
                evaluation,
            )
            if candidate.eligible_at(now):
                candidates.append(candidate)
    require_window(bool(candidates))
    return PlanChildWindow(child.binding, child.quota, "ordinary", None, tuple(candidates))

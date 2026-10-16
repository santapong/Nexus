"""Server-owned exact plan catalogs; constructor validation confers no live permission."""

from typing import Self

from pydantic import Field, model_validator

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.management.base import (
    ManagementContract,
    Name,
    Symbol,
    ValueContract,
    require_company,
)
from nexus.company.management.cycle_admission_contracts import StockFlowCycleAdmission
from nexus.company.management.cycle_catalog_checks import validate_cycle_catalog
from nexus.company.management.model_observations import (
    ModelEligibilityObservation,
    validate_model_observations,
)
from nexus.company.management.native_execution_profiles import (
    NativeExecutionProfile,
    validate_native_profiles,
)
from nexus.company.management.nexus_cycle_admission import (
    NexusCycleAdmission,
    validate_nexus_catalog,
)
from nexus.company.notifications.native_profile_checks import validate_notification_profiles
from nexus.company.notifications.native_profile_contracts import NativeNotificationProfile
from nexus.core.llm.company_registry import ModelRegistry, Profile
from nexus.harness.standing_contracts import ToolPermission


class NamedPlanResource(ValueContract):
    """A server-owned exact symbol mapping; user strings cannot select arbitrary resources."""

    symbol: Name
    resource: ResourceRef


class PlanAdmissionCatalog(ManagementContract):
    """Constructor configuration, no default or anonymous eligibility affirmation."""

    tools: tuple[ToolPermission, ...] = Field(default=(), max_length=32)
    resources: tuple[NamedPlanResource, ...] = Field(default=(), max_length=32)
    models: ModelRegistry
    admitted_profiles: frozenset[Profile]
    check_recipes: frozenset[Symbol]
    model_observations: tuple[ModelEligibilityObservation, ...] = Field(
        default=(), max_length=32, exclude_if=lambda value: not value
    )
    native_profiles: tuple[NativeExecutionProfile, ...] = Field(
        default=(), max_length=2, exclude_if=lambda value: not value
    )
    notification_profiles: tuple[NativeNotificationProfile, ...] = Field(
        default=(), max_length=1, exclude_if=lambda value: not value
    )

    cycle_admission: StockFlowCycleAdmission | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    nexus_cycle_admission: NexusCycleAdmission | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def exact_catalog(self) -> Self:
        require_company(self.company_id, self.models, *(row.resource for row in self.resources))
        validate_model_observations(self.models, self.model_observations)
        validate_native_profiles(self.models, self.native_profiles)
        validate_notification_profiles(self.models, self.notification_profiles)
        if len({row.tool for row in self.tools}) != len(self.tools):
            raise ValueError("One exact configured tool version per admission symbol is required")
        if len({row.symbol for row in self.resources}) != len(self.resources):
            raise ValueError("Admission resources must have unique exact symbols")
        validate_cycle_catalog(self.cycle_admission, self)
        validate_nexus_catalog(self.nexus_cycle_admission, self)
        return self

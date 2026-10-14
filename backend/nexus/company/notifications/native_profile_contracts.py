"""Explicit no-model sender identity; decoded configuration is not owner authority."""

from typing import Literal, Self

from pydantic import model_validator

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.management.base import SHA256, ManagementContract, Name, require_company

NOTIFICATION_PROFILE = "notification.native.v1"
NOTIFICATION_WORKFLOW = "internal.owner-notification"
NOTIFICATION_VERSION = "v1"
NOTIFICATION_TOOL = "company.owner-notification.send.v1"


class NativeNotificationProfile(ManagementContract):
    """Pin one fixed sender and resource without inventing model or credential evidence."""

    execution_profile: Literal["notification.native.v1"]
    workflow_name: Literal["internal.owner-notification"]
    workflow_version: Literal["v1"] = "v1"
    registry_revision: Name
    registry_sha256: SHA256
    target_symbol: Name
    target_resource: ResourceRef

    @model_validator(mode="after")
    def scoped_target(self) -> Self:
        """The exact resource is descriptive and must retain its declaring company."""
        require_company(self.company_id, self.target_resource)
        return self

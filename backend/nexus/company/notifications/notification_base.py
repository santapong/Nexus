"""Shared notification declaration base; compatibility public module identity is retained."""

from typing import Literal
from uuid import UUID

from nexus.company.management.base import ValueContract


class NotificationContract(ValueContract):
    __module__ = "nexus.company.notifications.contracts"
    schema_version: Literal["nexus.company.notification.v1"] = "nexus.company.notification.v1"
    company_id: UUID

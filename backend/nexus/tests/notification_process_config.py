"""Closed TEST-only notification OS descriptors; no token, permit or native authority."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, model_validator

from nexus.company.brain.native_fact_contracts import DecisionSelector
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.base import SHA256, ValueContract
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.company.notifications.contracts import NotificationPolicy
from nexus.company.notifications.managed_contracts import (
    NativeNotificationSelection,
    NotificationPreparationPolicy,
)
from nexus.company.notifications.worker_config import WorkerRegistrationSnapshot
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.notification_dispatch_read import require_notification_command

NotificationBarrier = Literal["intent", "response", "receipt", "observation"]
NotificationProcessDatabase = Literal[
    "nexus_company_test_notification_process_intent",
    "nexus_company_test_notification_process_response",
    "nexus_company_test_notification_process_receipt",
    "nexus_company_test_notification_process_observation",
]
PROCESS_ROOTS = {
    f"nexus_company_test_notification_process_{phase}": Path(
        "/home/santapong/.codex/nexus-local-release-fixtures-20261014-continued"
    )
    / f"notification-process-{phase}-20261015-1"
    for phase in ("intent", "response", "receipt", "observation")
}


def require_notification_process_root(database: str, root: Path, *, existing: bool) -> None:
    """Exact owned namespace; no arbitrary path or silent existing-root removal."""
    if PROCESS_ROOTS.get(database) != root or root.resolve() != root or root.is_symlink():
        raise ValueError("Notification process fixture scope differs")
    if existing:
        info = root.stat()
        if not root.is_dir() or info.st_uid != os.getuid() or info.st_mode & 0o777 != 0o700:
            raise ValueError("Notification process fixture root is unavailable")
    elif root.exists():
        raise ValueError("Notification process preparation requires a new root")


class NotificationProcessConfig(ValueContract):
    """Portable fixture metadata narrows reconstruction; actual native records remain mandatory."""

    database: NotificationProcessDatabase
    root: Path
    barrier: NotificationBarrier
    catalog: PlanAdmissionCatalog
    registration: WorkerRegistrationSnapshot
    recipient_file_sha256: SHA256
    command: SegmentCommand
    action: ActionProposal
    selection: NativeNotificationSelection
    notification_policy: NotificationPolicy
    preparation_policy: NotificationPreparationPolicy
    source_action_id: UUID
    lease_ttl_seconds: Literal[30] = 30
    credential_issued_at: AwareDatetime
    credential_expires_at: AwareDatetime
    response_uuid: UUID
    response_sha256: SHA256
    application_name: Literal["nexus-owner-notifications"] = "nexus-owner-notifications"
    queue_name: Literal["nexus.notifications.v1"] = "nexus.notifications.v1"

    @model_validator(mode="after")
    def exact_original_binding(self) -> Self:
        """Full command, role, registration and response pins precede reconstruction."""
        # Cohesive descriptor boundary: all original pins refer to one closed
        # process case; none of these checks replaces native admission/ownership.
        if (
            PROCESS_ROOTS.get(self.database) != self.root
            or self.database.rsplit("_", 1)[-1] != self.barrier
        ):
            raise ValueError("Notification process fixture scope differs")
        saved = self.registration.value.registration
        params = require_notification_command(
            saved.sender, self.action, self.command, self.preparation_policy.resource_symbol
        )
        if (
            self.catalog.company_id != self.command.company_id
            or saved.company_id != self.command.company_id
            or self.selection.company_id != self.command.company_id
            or self.selection.draft_id != params.draft_id
            or self.selection.sender_task_id != self.command.task_id
            or self.selection.plan != saved.plan
            or canonical_sha256(self.catalog) != saved.catalog_sha256
            or canonical_sha256(self.notification_policy) != saved.notification_policy_sha256
            or canonical_sha256(self.preparation_policy) != saved.preparation_policy_sha256
            or len(saved.subjects) != 1
            or not isinstance(saved.subjects[0].selector, DecisionSelector)
            or saved.subjects[0].selector.action_id != self.source_action_id
            or not self.credential_issued_at < self.credential_expires_at
        ):
            raise ValueError("Notification process metadata binding differs")
        raw = json.dumps({"id": str(self.response_uuid)}, separators=(",", ":")).encode()
        if hashlib.sha256(raw).hexdigest() != self.response_sha256:
            raise ValueError("Notification process response hash differs")
        return self

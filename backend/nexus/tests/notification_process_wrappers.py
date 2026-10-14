"""TEST-only post-commit barriers; all native admission and effects remain delegated unchanged."""

from __future__ import annotations

import asyncio
import json
import os
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from pydantic import StrictBool

from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.actions import ResourceRevision
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.canonical import canonical_sha256
from nexus.company.notifications.delivery_contracts import SubmissionResult
from nexus.company.notifications.managed_effects import ManagedNotificationEffectStore
from nexus.company.notifications.worker_dispatch import AuthenticatedManagedNotificationDispatcher
from nexus.company.notifications.worker_intent import CredentialNotificationIntentCheck
from nexus.execution.intent_checks import BeforeIntentCheck
from nexus.execution.runtime_contracts import AttemptKind, EffectRecord, EffectStart, ExecutionLease
from nexus.tests.notification_process_config import NotificationBarrier


def append_process_marker(root: Path, name: str, record: dict[str, object]) -> None:
    """Fixed trusted names and bounded safe metadata; no token, key, body or SQL."""
    if name not in {
        "barrier-events.jsonl",
        "acquisition-observations.jsonl",
        "http-transcript.jsonl",
    }:
        raise ValueError("Notification marker name is unavailable")
    raw = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(raw) > 32768:
        raise ValueError("Notification process marker exceeds bound")
    fd = os.open(root / name, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_size + len(raw) > 1048576
        ):
            raise ValueError("Notification process marker is unavailable")
        assert os.write(fd, raw) == len(raw)
        os.fsync(fd)
    finally:
        os.close(fd)


@dataclass
class NotificationProcessBarrier:
    root: Path
    selected: NotificationBarrier | None

    async def checkpoint(self, event: NotificationBarrier, metadata: dict[str, object]) -> None:
        """Bounded pause after delegated return; a marker confers no permit."""
        append_process_marker(
            self.root,
            "barrier-events.jsonl",
            metadata
            | {
                "event": event,
                "pid": os.getpid(),
                "host_observed_at": datetime.now(UTC).isoformat(),
            },
        )
        if event == self.selected:
            async with asyncio.timeout(120):
                await asyncio.Event().wait()


class InstrumentedNotificationEffects(ManagedNotificationEffectStore):
    barrier: NotificationProcessBarrier

    async def begin(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        action_id: UUID,
        *,
        resources: tuple[ResourceRevision, ...] = (),
        kind: AttemptKind = "tool_attempts",
        before_intent: BeforeIntentCheck | None = None,
    ) -> EffectStart:
        result = await super().begin(
            lease, identity, action_id, resources=resources, kind=kind, before_intent=before_intent
        )
        if result.permit_external_call:
            await self.barrier.checkpoint(
                "intent",
                {
                    "action_id": str(action_id),
                    "original_fence": result.record.intent_fence,
                    "worker_id": str(lease.worker_id),
                    "intent_created_at": result.record.created_at.isoformat(),
                    "command_scope": lease.model_dump(mode="json"),
                },
            )
        return result

    async def record_receipt(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        receipt: ActionReceipt,
        *,
        actual_usd: Decimal | None = None,
        blocked: StrictBool = False,
    ) -> EffectRecord:
        result = await super().record_receipt(
            lease, identity, receipt, actual_usd=actual_usd, blocked=blocked
        )
        await self.barrier.checkpoint(
            "receipt",
            {
                "action_id": str(receipt.action_id),
                "receipt_sha256": canonical_sha256(receipt),
                "original_fence": result.intent_fence,
                "worker_id": str(lease.worker_id),
            },
        )
        return result


class InstrumentedNotificationDispatcher(AuthenticatedManagedNotificationDispatcher):
    barrier: NotificationProcessBarrier

    async def _submit(
        self, check: CredentialNotificationIntentCheck, action_id: UUID
    ) -> SubmissionResult:
        result = await super()._submit(check, action_id)
        await self.barrier.checkpoint(
            "response",
            {
                "action_id": str(action_id),
                "response_sha256": result.response_sha256,
                "provider_id": str(result.provider_id) if result.provider_id else None,
                "outcome": result.outcome,
                "worker_id": str(check.lease.worker_id),
            },
        )
        return result

    async def _record(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        draft_id: UUID,
        receipt: ActionReceipt,
        result: SubmissionResult,
    ) -> None:
        await super()._record(lease, identity, draft_id, receipt, result)
        await self.barrier.checkpoint(
            "observation",
            {
                "action_id": str(receipt.action_id),
                "draft_id": str(draft_id),
                "receipt_sha256": canonical_sha256(receipt),
                "response_sha256": result.response_sha256,
                "worker_id": str(lease.worker_id),
            },
        )

"""TEST-only actual public pending sender setup; owner decision/deadline is added separately."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import httpx
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.management.scheduling_contracts import SchedulerPolicy
from nexus.company.management.scheduling_support import SchedulerServices
from nexus.company.notifications.dispatch_store import NotificationTransportConfiguration
from nexus.company.notifications.managed_contracts import NativeNotificationSelection
from nexus.company.notifications.managed_effects import ManagedNotificationEffectStore
from nexus.company.notifications.worker_config import WorkerRegistrationSnapshot
from nexus.company.notifications.worker_dispatch import AuthenticatedManagedNotificationDispatcher
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.company.notifications.worker_services import NotificationWorkerServices
from nexus.company.notifications.worker_tick import NotificationReadPreparationWorker
from nexus.execution.notification_worker_services import (
    NotificationDispatchWorkerServices,
    notification_workflow_registration,
)
from nexus.execution.runtime_store import ExecutionStore
from nexus.tests.notification_worker_tick_fixture import worker_tick_native_case
from nexus.tests.notification_worker_tick_services_fixture import configured_tick_services


@dataclass(frozen=True)
class StagedAtomicCase:
    """Actual staged native identities; no owner approval, hold or queue at construction."""

    services: NotificationDispatchWorkerServices
    selection: NativeNotificationSelection
    credential: AuthenticatedWorkerIdentity
    snapshot: WorkerRegistrationSnapshot
    action_id: UUID
    source_action_id: UUID
    http_calls: list[str]


async def staged_atomic_case(
    factory: async_sessionmaker[AsyncSession],
    root: Path,
) -> StagedAtomicCase:
    """Use unchanged public source/tick helpers, leaving the original owner decision absent."""
    native = await worker_tick_native_case(factory, root / "blobs")
    reads = await configured_tick_services(factory, root, native)
    staged = await NotificationReadPreparationWorker(reads, enabled=True).tick()
    assert len(staged.draft_ids) == len(staged.action_ids) == 1
    snapshot = reads.registrations.snapshot()
    binding = snapshot.value.registration.sender
    credential = await reads.identities.current(expected_binding=binding)
    selection = NativeNotificationSelection(
        company_id=binding.company_id,
        sender_task_id=binding.task_id,
        draft_id=staged.draft_ids[0],
        plan=snapshot.value.registration.plan,
    )
    calls: list[str] = []
    return StagedAtomicCase(
        compose_staged_services(reads, calls),
        selection,
        credential,
        snapshot,
        staged.action_ids[0],
        native.source_action.action_id,
        calls,
    )


def compose_staged_services(
    reads: NotificationWorkerServices,
    calls: list[str],
) -> NotificationDispatchWorkerServices:
    """Reuse the fixed common-dependency composition; any HTTP call remains a failing sentinel."""
    # Cohesive >50-line test composition exception: all constructor pins share
    # the exact actual reader/factory/policy and remain free of activation/effects.

    def unexpected_http(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        raise AssertionError("Postqueue expiry must issue no HTTP method")

    factory, facts = reads.factory, reads.facts
    effects = ManagedNotificationEffectStore(
        factory,
        reads.drafts,
        facts.catalog,
        facts.artifacts,
        facts.freshness,
        policy=reads.preparation.policy,
    )
    dispatcher = AuthenticatedManagedNotificationDispatcher(
        factory,
        reads.drafts,
        effects,
        enabled=True,
        configuration=NotificationTransportConfiguration(
            enabled=True,
            api_key=SecretStr("synthetic-unused-postqueue-only"),
            http_transport=httpx.MockTransport(unexpected_http),
        ),
    )
    execution = ExecutionStore(
        factory,
        management_catalog=facts.catalog,
        management_artifacts=facts.artifacts,
        management_freshness=facts.freshness,
    )
    scheduler = SchedulerServices(
        SchedulerPolicy(
            recipe_version="notification-dispatch-v1",
            max_tasks=1,
            workflows=(notification_workflow_registration(),),
        ),
        facts.catalog,
        facts.artifacts,
        facts.freshness,
        facts.scheduler.identities,
        facts.scheduler.resources,
    )
    return NotificationDispatchWorkerServices(
        reads,
        execution,
        dispatcher,
        scheduler,
        worker_id=UUID(int=870),
        enabled=True,
    )

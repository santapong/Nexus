"""Public owner approval/claim and explicit mock-only managed notification fixture helpers."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.company.notifications.dispatch_store import NotificationTransportConfiguration
from nexus.company.notifications.managed_contracts import PreparedNotification
from nexus.company.notifications.managed_dispatch import ManagedNotificationDispatchStore
from nexus.company.notifications.managed_effects import ManagedNotificationEffectStore
from nexus.company.notifications.managed_preparation import ManagedNotificationPreparation
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_store import ExecutionStore
from nexus.harness.canonical import action_hash
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import LedgerScope
from nexus.tests.integration.test_company_directory import OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.notification_managed_fixture import ManagedNotificationCase


def configure_catalog(
    factory: async_sessionmaker[AsyncSession],
    case: ManagedNotificationCase,
    catalog: PlanAdmissionCatalog,
) -> ManagedNotificationCase:
    args = (factory, case.drafts, catalog, case.metric.store.artifacts, case.metric.store.freshness)
    return replace(
        case,
        preparation=ManagedNotificationPreparation(*args, policy=case.policy),
        effects=ManagedNotificationEffectStore(*args, policy=case.policy),
        execution=ExecutionStore(
            factory,
            management_catalog=catalog,
            management_artifacts=case.metric.store.artifacts,
            management_freshness=case.metric.store.freshness,
        ),
    )


def expiring_profile(case: ManagedNotificationCase, seconds: float) -> PlanAdmissionCatalog:
    now = datetime.now(UTC)
    catalog = case.plans.catalog
    models = tuple(
        row.model_copy(
            update={
                "health": row.health.model_copy(
                    update={
                        "checked_at": now - timedelta(minutes=1),
                        "expires_at": now + timedelta(seconds=seconds),
                    }
                )
            }
        )
        for row in catalog.models.models
    )
    return PlanAdmissionCatalog.model_validate_json(
        catalog.model_copy(
            update={"models": catalog.models.model_copy(update={"models": models})}
        ).model_dump_json()
    )


async def approved_sender(
    factory: async_sessionmaker[AsyncSession], case: ManagedNotificationCase
) -> tuple[PreparedNotification, ExecutionLease]:
    prepared = await case.preparation.prepare(control(), identity(OWNER), case.selection)
    sender, proposal = prepared.sender, prepared.action.proposal
    scope = LedgerScope(
        company_id=sender.company_id,
        task_id=sender.task_id,
        trace_id=sender.trace_id,
        principal_id=OWNER,
    )
    journal = CompanyJournal(factory)
    await journal.approve_registered(
        scope,
        proposal.action_id,
        action_hash(proposal),
        datetime.now(UTC),
        identity=identity(OWNER),
    )
    await journal.authorize_registered(
        scope, proposal.action_id, datetime.now(UTC), (), identity=identity(OWNER)
    )
    return prepared, await case.execution.claim(scope, identity(OWNER), uuid4(), ttl_seconds=60)


def mock_dispatch(
    factory: async_sessionmaker[AsyncSession], case: ManagedNotificationCase, calls: list[str]
) -> ManagedNotificationDispatchStore:
    def response(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return httpx.Response(200, json={"id": str(UUID(int=8411))})

    return ManagedNotificationDispatchStore(
        factory,
        case.drafts,
        case.effects,
        configuration=NotificationTransportConfiguration(
            enabled=True,
            api_key=SecretStr("fixture-only"),
            http_transport=httpx.MockTransport(response),
        ),
    )

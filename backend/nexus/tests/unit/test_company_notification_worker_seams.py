"""None defaults preserve old paths; genuine guards bind every public company scope."""

from pathlib import Path
from typing import cast
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.native_fact_contracts import DecisionSelector
from nexus.company.brain.native_fact_emitter import NativeFactEmitter
from nexus.company.brain.native_fact_reader import NativeFactReader
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.notifications.managed_contracts import (
    NativeNotificationSelection,
    NotificationPreparationPolicy,
)
from nexus.company.notifications.managed_preparation import ManagedNotificationPreparation
from nexus.company.notifications.qualified_consumer import QualifiedNotificationConsumer
from nexus.company.notifications.qualified_store import QualifiedNotificationDraftStore
from nexus.company.notifications.worker_config import WorkerConfigurationError
from nexus.company.notifications.worker_guard import NotificationOperationGuard
from nexus.harness.journal_models import CompanyControl
from nexus.tests.unit.test_company_notification_native_profiles import notification_plan
from nexus.tests.unit.test_company_notification_worker_guard import operation_guard


def prepared_services(
    guard: NotificationOperationGuard | None,
) -> tuple[
    MagicMock, NativeFactEmitter, QualifiedNotificationConsumer, ManagedNotificationPreparation
]:
    factory = MagicMock(spec=async_sessionmaker)
    factory.side_effect = RuntimeError("Unexpected database acquisition")
    actual_factory = cast(async_sessionmaker[AsyncSession], factory)
    drafts = MagicMock(spec=QualifiedNotificationDraftStore)
    catalog, _ = notification_plan()
    drafts.loader = MagicMock()
    drafts.loader.catalog = catalog
    policy = NotificationPreparationPolicy(
        target=catalog.notification_profiles[0].target_resource,
        resource_symbol=catalog.notification_profiles[0].target_symbol,
    )
    reader = MagicMock(spec=NativeFactReader)
    reader.load_locked.side_effect = RuntimeError("Unexpected native source read")
    drafts.prepare_recipient.side_effect = RuntimeError("Unexpected recipient read")
    return (
        factory,
        NativeFactEmitter(actual_factory, reader, operation_guard=guard),
        QualifiedNotificationConsumer(
            drafts, consumer="fixture", recipe_version="v1", operation_guard=guard
        ),
        ManagedNotificationPreparation(
            actual_factory,
            drafts,
            catalog,
            MagicMock(spec=BoundedArtifactReader),
            MagicMock(spec=RegisteredSourceFreshness),
            policy=policy,
            operation_guard=guard,
        ),
    )


def test_none_default_preserves_constructor_values_without_database_acquisition() -> None:
    factory, emitter, consumer, prepared = prepared_services(None)
    assert emitter.operation_guard is consumer.operation_guard is prepared.operation_guard is None
    catalog, _ = notification_plan()
    assert prepared.catalog.model_dump_json() == catalog.model_dump_json()
    factory.assert_not_called()


@pytest.mark.parametrize("boundary", ["emit", "consume", "prepare"])
def test_constructor_seams_reject_arbitrary_callable(boundary: str) -> None:
    factory, _, consumer, prepared = prepared_services(None)
    invalid = cast(NotificationOperationGuard, lambda now: None)
    with pytest.raises(ValueError):
        if boundary == "emit":
            NativeFactEmitter(
                cast(async_sessionmaker[AsyncSession], factory),
                MagicMock(spec=NativeFactReader),
                operation_guard=invalid,
            )
        elif boundary == "consume":
            QualifiedNotificationConsumer(
                consumer.store, consumer="fixture", recipe_version="v1", operation_guard=invalid
            )
        else:
            ManagedNotificationPreparation(
                prepared.factory,
                prepared.drafts,
                prepared.catalog,
                prepared.artifacts,
                prepared.freshness,
                policy=prepared.policy,
                operation_guard=invalid,
            )
    factory.assert_not_called()


@pytest.mark.parametrize(
    "boundary", ["emit", "locked_scope", "locked_control", "locked_selector", "consume", "prepare"]
)
async def test_same_identity_guard_denies_foreign_company_before_native_reads(
    tmp_path: Path, boundary: str
) -> None:
    guard, _ = await operation_guard(tmp_path)
    factory, emitter, consumer, prepared = prepared_services(guard)
    company = guard.registration.company_id
    foreign = UUID(int=999)
    identity = guard.witness.identity
    scope = CompanyControlScope(
        company_id=foreign,
        principal_id=identity.principal_id,
        operation_id=UUID(int=801),
        trace_id=UUID(int=802),
    )
    brain = BrainReadScope(
        company_id=foreign if boundary in {"emit", "locked_scope"} else company,
        workspace_id=identity.workspace_id,
        principal_id=identity.principal_id,
        operation_id=scope.operation_id,
        trace_id=scope.trace_id,
    )
    selector = DecisionSelector(
        company_id=foreign if boundary == "locked_selector" else company, action_id=UUID(int=803)
    )
    control = CompanyControl(company_id=foreign if boundary == "locked_control" else company)
    with pytest.raises(WorkerConfigurationError):
        if boundary == "emit":
            await emitter.emit(brain, identity, selector)
        elif boundary.startswith("locked_"):
            await emitter.emit_locked(
                MagicMock(spec=AsyncSession), control, brain, identity, selector
            )
        elif boundary == "consume":
            await consumer.consume(scope, identity)
        else:
            await prepared.prepare(
                scope,
                identity,
                NativeNotificationSelection(
                    company_id=company,
                    draft_id=UUID(int=804),
                    sender_task_id=guard.registration.sender.task_id,
                    plan=guard.registration.plan,
                ),
            )
    factory.assert_not_called()
    cast(MagicMock, emitter.reader).load_locked.assert_not_called()
    cast(MagicMock, consumer.store).prepare_recipient.assert_not_called()

"""Process dependency/config pins are mandatory and never synthesize current permission."""

from dataclasses import replace
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.native_fact_reader import NativeFactReader
from nexus.company.brain.native_fact_services import NativeFactServices
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.scheduling_support import SchedulerServices
from nexus.company.notifications.managed_contracts import NotificationPreparationPolicy
from nexus.company.notifications.managed_preparation import ManagedNotificationPreparation
from nexus.company.notifications.native_loader import NativeNotificationFactLoader
from nexus.company.notifications.qualified_adapter import QualifiedNotificationFactAdapter
from nexus.company.notifications.qualified_store import QualifiedNotificationDraftStore
from nexus.company.notifications.recipient_registry import RegisteredOwnerRecipients
from nexus.company.notifications.worker_config import FileNotificationWorkerRegistration
from nexus.company.notifications.worker_contracts import (
    NotificationWorkerConfiguration,
    NotificationWorkerRegistrationFile,
)
from nexus.company.notifications.worker_guard import NotificationOperationGuard
from nexus.company.notifications.worker_identity import NotificationWorkerIdentities
from nexus.company.notifications.worker_services import NotificationWorkerServices
from nexus.tests.unit.test_company_notification_native_profiles import notification_plan
from nexus.tests.unit.test_company_notification_worker_config import registration
from nexus.tests.unit.test_company_notification_worker_identity import adapter, signed


def services(tmp_path: Path) -> NotificationWorkerServices:
    factory = cast(async_sessionmaker[AsyncSession], MagicMock(spec=async_sessionmaker))
    catalog, _ = notification_plan()
    artifacts = MagicMock(spec=BoundedArtifactReader)
    freshness = MagicMock(spec=RegisteredSourceFreshness)
    scheduler = MagicMock(spec=SchedulerServices)
    scheduler.catalog = catalog
    facts = NativeFactServices(
        catalog, artifacts, freshness, scheduler, catalog.notification_profiles[0].target_resource
    )
    reader = NativeFactReader(facts)
    drafts = QualifiedNotificationDraftStore(
        factory,
        QualifiedNotificationFactAdapter(
            NativeNotificationFactLoader(catalog, artifacts, freshness), reader
        ),
        MagicMock(spec=RegisteredOwnerRecipients),
    )
    preparation = ManagedNotificationPreparation(
        factory,
        drafts,
        catalog,
        artifacts,
        freshness,
        policy=NotificationPreparationPolicy(
            target=facts.resource, resource_symbol=catalog.notification_profiles[0].target_symbol
        ),
    )
    return NotificationWorkerServices(
        factory,
        NotificationWorkerIdentities(),
        FileNotificationWorkerRegistration(tmp_path / "unread.json"),
        facts,
        drafts,
        preparation,
    )


async def guarded_services(
    tmp_path: Path,
) -> tuple[NotificationWorkerServices, NotificationOperationGuard]:
    value = services(tmp_path)
    original = registration()
    pinned = original.model_copy(
        update={
            "catalog_sha256": canonical_sha256(value.facts.catalog),
            "sender": original.sender.model_copy(
                update={
                    "model_registry_version": value.facts.catalog.models.revision,
                }
            ),
            "notification_policy_sha256": canonical_sha256(value.drafts.policy),
            "preparation_policy_sha256": canonical_sha256(value.preparation.policy),
            "subjects": (),
        }
    )
    path = tmp_path / "unread.json"
    path.write_text(
        NotificationWorkerRegistrationFile(
            registration=pinned,
            configuration=NotificationWorkerConfiguration(enabled=True),
        ).model_dump_json()
    )
    path.chmod(0o600)
    ids, _ = adapter(signed())
    return value, NotificationOperationGuard(
        await ids.current(), value.registrations.snapshot(), value.registrations
    )


def test_worker_service_construction_is_pure_without_config_credentials_or_database(
    tmp_path: Path,
) -> None:
    value = services(tmp_path)
    assert not (tmp_path / "unread.json").exists()
    cast(MagicMock, value.factory).assert_not_called()


@pytest.mark.parametrize("field", ["factory", "reader", "artifacts", "freshness"])
def test_mixed_process_dependencies_cannot_create_worker_services(
    tmp_path: Path, field: str
) -> None:
    value = services(tmp_path)
    if field == "factory":
        value.preparation.factory = cast(async_sessionmaker[AsyncSession], MagicMock())
    elif field == "reader":
        value.drafts.loader.reader = NativeFactReader(replace(value.facts))
    else:
        setattr(value.preparation, field, MagicMock())
    with pytest.raises(ValueError):
        NotificationWorkerServices(
            value.factory,
            value.identities,
            value.registrations,
            value.facts,
            value.drafts,
            value.preparation,
        )


def test_full_snapshot_policy_or_catalog_drift_denies_before_guarded_service_creation(
    tmp_path: Path,
) -> None:
    value = services(tmp_path)
    original = registration()
    pinned = original.model_copy(
        update={
            "catalog_sha256": canonical_sha256(value.facts.catalog),
            "sender": original.sender.model_copy(
                update={"model_registry_version": value.facts.catalog.models.revision}
            ),
            "notification_policy_sha256": canonical_sha256(value.drafts.policy),
            "preparation_policy_sha256": canonical_sha256(value.preparation.policy),
            "subjects": (),
        }
    )
    path = tmp_path / "unread.json"
    path.write_text(NotificationWorkerRegistrationFile(registration=pinned).model_dump_json())
    path.chmod(0o600)
    snapshot = value.registrations.snapshot()
    value.require_registration(snapshot)
    value.preparation.policy = value.preparation.policy.model_copy(update={"enabled": True})
    with pytest.raises(ValueError):
        value.require_registration(snapshot)

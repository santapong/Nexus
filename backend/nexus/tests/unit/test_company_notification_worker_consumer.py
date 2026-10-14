"""Per-call captured sender windows narrow the inherited final clock, never authorize it."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nexus.company.access import CompanyControlScope
from nexus.company.notifications.contracts import OwnerRecipientPolicy
from nexus.company.notifications.qualified_consumer import _QualifiedHandler
from nexus.company.notifications.worker_config import WorkerConfigurationError
from nexus.company.notifications.worker_consumer import (
    WorkerNotificationConsumer,
    WorkerSenderFinalGuard,
)
from nexus.company.notifications.worker_services import WorkerSenderAdmission
from nexus.tests.unit.test_company_notification_native_profiles import notification_plan
from nexus.tests.unit.test_company_notification_worker_seams import prepared_services
from nexus.tests.unit.test_company_notification_worker_services import guarded_services


def test_default_factory_preserves_the_original_handler_and_none_guard() -> None:
    _, _, consumer, _ = prepared_services(None)
    scope = MagicMock(spec=CompanyControlScope)
    identity = MagicMock()
    recipient = MagicMock(spec=OwnerRecipientPolicy)
    handler = consumer._handler(scope, identity, recipient)
    assert type(handler) is _QualifiedHandler and handler.operation_guard is None
    assert (
        handler.store is consumer.store
        and handler.scope is scope
        and handler.recipient is recipient
    )


async def test_worker_consumer_factory_has_distinct_per_operation_captures(tmp_path: Path) -> None:
    services, guard = await guarded_services(tmp_path)
    consumer = WorkerNotificationConsumer(
        services.drafts,
        consumer=guard.registration.consumer,
        recipe_version=guard.registration.recipe_version,
        operation_guard=guard,
        services=services,
    )
    scope = MagicMock(spec=CompanyControlScope)
    recipient = MagicMock(spec=OwnerRecipientPolicy)
    one = consumer._handler(scope, guard.witness.identity, recipient)
    two = consumer._handler(scope, guard.witness.identity, recipient)
    assert one is not two and one.operation_guard is not two.operation_guard
    assert isinstance(one.operation_guard, WorkerSenderFinalGuard)
    assert isinstance(two.operation_guard, WorkerSenderFinalGuard)
    with pytest.raises(WorkerConfigurationError):
        one.operation_guard.require_time(datetime.now(UTC))
    with pytest.raises(WorkerConfigurationError):
        two.operation_guard.require_time(datetime.now(UTC))


async def test_captured_expired_sender_window_is_denied_at_final_clock(tmp_path: Path) -> None:
    services, base = await guarded_services(tmp_path)
    guard = WorkerSenderFinalGuard(base, services)
    _, payload = notification_plan()
    admitted = WorkerSenderAdmission(
        MagicMock(),
        payload,
        MagicMock(),
        (datetime.now(UTC) - timedelta(seconds=1),),
    )
    guard.capture(admitted)
    with pytest.raises(WorkerConfigurationError):
        guard.require_time(datetime.now(UTC))

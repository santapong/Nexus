"""Final credential dispatcher retains its specialized intent check before native begin."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from nexus.company.notifications.worker_dispatch import AuthenticatedManagedNotificationDispatcher
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.company.notifications.worker_intent import CredentialNotificationIntentCheck
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.tests.unit.test_company_notification_worker_identity import adapter, signed
from nexus.tests.unit.test_company_notification_worker_wrappers import dispatcher, lease


async def test_specialized_intent_factory_denial_stops_before_native_begin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ClosedFactory(AuthenticatedManagedNotificationDispatcher):
        def _intent_check(
            self,
            lease: ExecutionLease,
            witness: AuthenticatedWorkerIdentity,
            draft_id: UUID,
            action_id: UUID,
        ) -> CredentialNotificationIntentCheck:
            raise ValueError("specialized intent is unavailable")

    base, _ = dispatcher(enabled=True)
    actual = ClosedFactory(
        base.factory,
        base.drafts,
        base.managed_effects,
        enabled=True,
        configuration=base.configuration,
    )
    native_begin = AsyncMock(return_value=SimpleNamespace(permit_external_call=False))
    monkeypatch.setattr(actual, "_existing", AsyncMock(return_value=False))
    monkeypatch.setattr(actual.effects, "begin", native_begin)
    identities, _ = adapter(signed())
    witness = await identities.current()
    with pytest.raises(ValueError, match="specialized intent is unavailable"):
        await actual.dispatch_with_credential(lease(), witness, UUID(int=904), UUID(int=905))
    native_begin.assert_not_awaited()

"""Pure credential wrapper boundaries; real source/intent conservation has separate PG proof."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import MagicMock
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.notifications.contracts import NotificationPayload, OwnerRecipientPolicy
from nexus.company.notifications.dispatch_store import NotificationTransportConfiguration
from nexus.company.notifications.draft_store import NotificationDraftStore
from nexus.company.notifications.managed_contracts import NotificationPreparationPolicy
from nexus.company.notifications.managed_effects import ManagedNotificationEffectStore
from nexus.company.notifications.worker_dispatch import AuthenticatedManagedNotificationDispatcher
from nexus.company.notifications.worker_identity import (
    AuthenticatedWorkerIdentity,
    WorkerIdentityDeniedError,
)
from nexus.company.notifications.worker_intent import require_credential_lease
from nexus.company.notifications.worker_transport import CredentialedResendTransport
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.tests.unit.test_company_management_contracts import binding
from nexus.tests.unit.test_company_notification_worker_identity import adapter, signed


def lease() -> ExecutionLease:
    """A declared lease is only fixture data; no real native claim or allowance is implied."""
    row = binding()
    return ExecutionLease(
        company_id=row.company_id,
        workspace_id=row.workspace_id,
        actor_id=row.actor_id,
        task_id=row.task_id,
        trace_id=row.trace_id,
        run_id=row.run_id,
        workflow_version="v1",
        segment_id=UUID(int=901),
        worker_id=UUID(int=902),
        fence=1,
        mode="execute",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )


def dispatcher(
    *, enabled: bool = False
) -> tuple[AuthenticatedManagedNotificationDispatcher, MagicMock]:
    factory = MagicMock(spec=async_sessionmaker)
    drafts = MagicMock(spec=NotificationDraftStore)
    effects = MagicMock(spec=ManagedNotificationEffectStore)
    effects.preparation = MagicMock()
    effects.preparation.policy = NotificationPreparationPolicy(
        target=ResourceRef(company_id=binding().company_id, resource_id=UUID(int=903)),
        resource_symbol="owner.notifications",
        enabled=True,
    )
    return AuthenticatedManagedNotificationDispatcher(
        cast(async_sessionmaker[AsyncSession], factory),
        drafts,
        effects,
        enabled=enabled,
        configuration=NotificationTransportConfiguration(
            enabled=True, api_key=SecretStr("mock-only")
        ),
    ), factory


async def test_disabled_wrapper_denies_before_any_native_query() -> None:
    ids, _ = adapter(signed())
    witness = await ids.current()
    dispatch, factory = dispatcher()
    with pytest.raises(ValueError):
        await dispatch.dispatch_with_credential(lease(), witness, UUID(int=904), UUID(int=905))
    factory.assert_not_called()


async def test_inherited_bare_identity_dispatch_is_closed_even_when_explicitly_enabled() -> None:
    ids, _ = adapter(signed())
    witness = await ids.current()
    dispatch, factory = dispatcher(enabled=True)
    with pytest.raises(ValueError):
        await dispatch.dispatch(lease(), witness.identity, UUID(int=904), UUID(int=905))
    factory.assert_not_called()


@pytest.mark.parametrize("field", ["actor_id", "workspace_id"])
async def test_credential_lease_metadata_mismatch_denies_without_work_authority(field: str) -> None:
    ids, _ = adapter(signed())
    witness = await ids.current()
    changed = lease().model_copy(update={field: UUID(int=999)})
    with pytest.raises(ValueError):
        require_credential_lease(changed, witness)


async def test_bare_verified_identity_cannot_replace_actual_credential_witness() -> None:
    ids, _ = adapter(signed())
    witness = await ids.current()
    with pytest.raises(ValueError):
        require_credential_lease(lease(), cast(AuthenticatedWorkerIdentity, witness.identity))


def recipient() -> OwnerRecipientPolicy:
    now = datetime.now(UTC)
    return OwnerRecipientPolicy(
        company_id=binding().company_id,
        owner_id=binding().actor_id,
        policy_id=UUID(int=906),
        version="credential-wrapper-unit-v1",
        sender="system@example.invalid",
        recipient="owner@example.invalid",
        registered_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
    )


async def test_opt_in_transport_keeps_one_mock_request_and_disabled_default() -> None:
    ids, _ = adapter(signed())
    witness = await ids.current()
    policy = recipient()
    payload = NotificationPayload(
        sender=policy.sender,
        recipient=policy.recipient,
        subject="Synthetic transport boundary",
        text="This is no native permission proof.",
    )
    calls: list[str] = []

    def response(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return httpx.Response(200, json={"id": str(UUID(int=907))})

    transport = httpx.MockTransport(response)
    async with CredentialedResendTransport(
        policy, SecretStr("mock-only"), witness, transport=transport
    ) as client:
        result = await client.submit(payload, "credential-wrapper-unit")
    assert result.outcome == "blocked" and calls == []
    async with CredentialedResendTransport(
        policy, SecretStr("mock-only"), witness, enabled=True, transport=transport
    ) as client:
        result = await client.submit(payload, "credential-wrapper-unit")
    assert result.outcome == "accepted" and calls == ["POST"]


async def test_transport_request_guard_denies_expiry_after_actual_client_context_await() -> None:
    now = int(datetime.now(UTC).timestamp())
    ids, _ = adapter(signed({"iat": now - 1, "exp": now + 2}))
    witness = await ids.current()
    policy = recipient()
    payload = NotificationPayload(
        sender=policy.sender,
        recipient=policy.recipient,
        subject="Synthetic expiry boundary",
        text="No native permission is implied.",
    )
    calls: list[str] = []

    def response(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return httpx.Response(200, json={"id": str(UUID(int=908))})

    class SlowContext(CredentialedResendTransport):
        async def __aenter__(self) -> CredentialedResendTransport:
            await asyncio.sleep(
                max(0, (self.witness.expires_at - datetime.now(UTC)).total_seconds()) + 0.03
            )
            await super().__aenter__()
            return self

    async with SlowContext(
        policy,
        SecretStr("mock-only"),
        witness,
        enabled=True,
        transport=httpx.MockTransport(response),
    ) as client:
        with pytest.raises(WorkerIdentityDeniedError):
            await client.submit(payload, "credential-wrapper-expired-unit")
    assert calls == []

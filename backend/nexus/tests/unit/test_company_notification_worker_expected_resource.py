"""A typed qualified second-resource frame cannot contradict the configured worker subject."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope
from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.native_fact_contracts import (
    DecisionSelector,
    DecisionState,
    FailedReceiptSelector,
    NativeFactProjection,
)
from nexus.company.brain.native_fact_reader import NativeFactReader
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.plan_support import NamedPlanResource
from nexus.company.notifications import worker_tick
from nexus.company.notifications.managed_preparation import ManagedNotificationPreparation
from nexus.company.notifications.native_loader import NativeNotificationFactLoader
from nexus.company.notifications.qualified_adapter import QualifiedNotificationFactAdapter
from nexus.company.notifications.qualified_store import QualifiedNotificationDraftStore
from nexus.company.notifications.worker_config import WorkerConfigurationError
from nexus.company.notifications.worker_contracts import (
    NotificationWorkerConfiguration,
    NotificationWorkerRegistrationFile,
    WorkerSubject,
)
from nexus.company.notifications.worker_guard import NotificationOperationGuard
from nexus.company.notifications.worker_services import (
    NotificationWorkerServices,
    WorkerSenderAdmission,
)
from nexus.company.notifications.worker_tick import NotificationReadPreparationWorker
from nexus.harness.canonical import action_hash
from nexus.harness.journal_contracts import ActionRecord
from nexus.harness.journal_models import CompanyControl
from nexus.harness.lifecycle import ActionState
from nexus.tests.unit.test_company_foundation import proposal
from nexus.tests.unit.test_company_notification_native_profiles import notification_plan
from nexus.tests.unit.test_company_notification_worker_config import registration
from nexus.tests.unit.test_company_notification_worker_identity import adapter, signed
from nexus.tests.unit.test_company_notification_worker_services import services


async def second_resource_services(
    tmp_path: Path, kind: str
) -> tuple[
    NotificationWorkerServices,
    NotificationOperationGuard,
    ResourceRef,
]:
    value, other = configured_second_resource(tmp_path)
    facts, catalog, drafts, preparation = (
        value.facts,
        value.facts.catalog,
        value.drafts,
        value.preparation,
    )
    initial = registration()
    selector = (
        DecisionSelector(company_id=initial.company_id, action_id=UUID(int=806))
        if kind == "decision"
        else FailedReceiptSelector(company_id=initial.company_id, action_id=UUID(int=806))
    )
    pinned = initial.model_copy(
        update={
            "catalog_sha256": canonical_sha256(catalog),
            "sender": initial.sender.model_copy(
                update={"model_registry_version": catalog.models.revision}
            ),
            "notification_policy_sha256": canonical_sha256(drafts.policy),
            "preparation_policy_sha256": canonical_sha256(preparation.policy),
            "subjects": (WorkerSubject(selector=selector, resource=facts.resource),),
        }
    )
    path = tmp_path / "unread.json"
    path.write_text(
        NotificationWorkerRegistrationFile(
            registration=pinned, configuration=NotificationWorkerConfiguration(enabled=True)
        ).model_dump_json()
    )
    path.chmod(0o600)
    ids, _ = adapter(signed())
    guard = NotificationOperationGuard(
        await ids.current(), value.registrations.snapshot(), value.registrations
    )
    value.require_registration(guard.snapshot)
    return value, guard, other


def configured_second_resource(tmp_path: Path) -> tuple[NotificationWorkerServices, ResourceRef]:
    original = services(tmp_path)
    other = ResourceRef(company_id=original.facts.catalog.company_id, resource_id=UUID(int=888))
    catalog = original.facts.catalog.model_copy(
        update={
            "resources": (
                *original.facts.catalog.resources,
                NamedPlanResource(symbol="second.readable", resource=other),
            ),
        }
    )
    cast(MagicMock, original.facts.scheduler).catalog = catalog
    facts = replace(original.facts, catalog=catalog)
    drafts = QualifiedNotificationDraftStore(
        original.factory,
        QualifiedNotificationFactAdapter(
            NativeNotificationFactLoader(catalog, facts.artifacts, facts.freshness),
            NativeFactReader(facts),
        ),
        original.drafts.recipients,
        policy=original.drafts.policy,
    )
    preparation = ManagedNotificationPreparation(
        original.factory,
        drafts,
        catalog,
        facts.artifacts,
        facts.freshness,
        policy=original.preparation.policy,
    )
    value = NotificationWorkerServices(
        original.factory, original.identities, original.registrations, facts, drafts, preparation
    )
    return value, other


def returned_projection(
    guard: NotificationOperationGuard, resource: ResourceRef
) -> NativeFactProjection:
    selector = guard.registration.subjects[0].selector
    if isinstance(selector, DecisionSelector):
        state: DecisionState | ActionReceipt = returned_decision(guard, selector, resource)
    else:
        assert isinstance(selector, FailedReceiptSelector)
        state = ActionReceipt(
            company_id=resource.company_id,
            receipt_id=UUID(int=807),
            action_id=selector.action_id,
            task_id=UUID(int=804),
            trace_id=UUID(int=805),
            proposal_hash="a" * 64,
            outcome="failed",
            recorded_at=datetime.now(UTC),
        )
    return NativeFactProjection(
        company_id=resource.company_id,
        selector=selector,
        state=state,
        resource=resource,
        required_resource_ids=(resource.resource_id,),
        source_recorded_at=datetime.now(UTC),
    )


def returned_decision(
    guard: NotificationOperationGuard,
    selector: DecisionSelector,
    resource: ResourceRef,
) -> DecisionState:
    bound = guard.registration.sender.model_copy(
        update={
            "task_id": UUID(int=804),
            "trace_id": UUID(int=805),
            "model_profile": "engineering.native.v1",
            "workflow_name": "engineering.change",
        }
    )
    action = proposal().model_copy(
        update={
            "task_id": bound.task_id,
            "trace_id": bound.trace_id,
            "action_id": selector.action_id,
            "actor_id": bound.actor_id,
        }
    )
    return DecisionState(
        company_id=resource.company_id,
        action=ActionRecord(
            company_id=resource.company_id,
            proposal=action,
            proposal_hash=action_hash(action),
            state=ActionState.AWAITING_APPROVAL,
            approval=None,
            consumed_at=None,
        ),
        work=bound,
        registration_sha256="a" * 64,
        plan=guard.registration.plan,
        policy_version=action.policy_version,
        price_version=action.price_version,
    )


@pytest.mark.parametrize("kind", ["decision", "failed_receipt"])
async def test_qualified_second_resource_must_deny_before_emission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    value, guard, other = await second_resource_services(tmp_path, kind)
    frame = returned_projection(guard, other)
    assert frame.resource in tuple(row.resource for row in value.facts.catalog.resources)
    assert frame.resource != guard.registration.subjects[0].resource
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=0)
    control = CompanyControl(
        company_id=frame.company_id, owner_id=guard.witness.identity.principal_id
    )

    @asynccontextmanager
    async def transaction(
        *args: object, **kwargs: object
    ) -> AsyncIterator[tuple[AsyncSession, CompanyControl, datetime]]:
        yield session, control, datetime.now(UTC)

    _, payload = notification_plan()
    admitted = WorkerSenderAdmission(MagicMock(), payload, MagicMock(), ())
    monkeypatch.setattr(worker_tick, "management_owner_transaction", transaction)
    monkeypatch.setattr(
        NotificationWorkerServices, "require_sender_locked", AsyncMock(return_value=admitted)
    )
    reader = MagicMock()
    reader.load_locked = AsyncMock(return_value=frame)
    monkeypatch.setattr(worker_tick, "NativeFactReader", MagicMock(return_value=reader))
    emitter = MagicMock()
    emitter.emit_locked = AsyncMock(side_effect=AssertionError("Unexpected mismatched emission"))
    monkeypatch.setattr(worker_tick, "NativeFactEmitter", MagicMock(return_value=emitter))
    scope = CompanyControlScope(
        company_id=frame.company_id,
        principal_id=guard.witness.identity.principal_id,
        operation_id=UUID(int=808),
        trace_id=UUID(int=809),
    )
    with pytest.raises(WorkerConfigurationError):
        await NotificationReadPreparationWorker(value, enabled=True)._emit(scope, guard)
    reader.load_locked.assert_awaited_once()
    emitter.emit_locked.assert_not_awaited()

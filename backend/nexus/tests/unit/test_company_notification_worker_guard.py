"""Concrete final-clock guard narrows a genuine sealed credential and exact local pins only."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from dbos._serialization import DBOSPortableJSON

from nexus.company.access import VerifiedIdentity
from nexus.company.notifications.worker_config import FileNotificationWorkerRegistration
from nexus.company.notifications.worker_contracts import (
    NotificationWorkerConfiguration,
    NotificationWorkerRegistrationFile,
)
from nexus.company.notifications.worker_guard import NotificationOperationGuard
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.tests.unit.test_company_notification_worker_config import registration
from nexus.tests.unit.test_company_notification_worker_identity import adapter, signed


async def operation_guard(tmp_path: Path) -> tuple[NotificationOperationGuard, Path]:
    path = tmp_path / "guard-registration.json"
    path.write_text(
        NotificationWorkerRegistrationFile(
            registration=registration(), configuration=NotificationWorkerConfiguration(enabled=True)
        ).model_dump_json()
    )
    path.chmod(0o600)
    reader = FileNotificationWorkerRegistration(path)
    ids, _ = adapter(signed())
    witness = await ids.current()
    return NotificationOperationGuard(witness, reader.snapshot(), reader), path


async def test_concrete_guard_retains_exact_identity_dates_and_no_wire_authority(
    tmp_path: Path,
) -> None:
    guard, _ = await operation_guard(tmp_path)
    guard.require_identity(guard.witness.identity)
    guard.require_company(guard.registration.company_id)
    guard.require_time(datetime.now(UTC))
    assert not hasattr(guard, "allowed") and not hasattr(guard, "call_permit")
    with pytest.raises(TypeError):
        json.dumps(guard)
    with pytest.raises(TypeError, match="not portable JSON serializable"):
        DBOSPortableJSON.serialize({"positionalArgs": [guard], "namedArgs": {}})


@pytest.mark.parametrize(
    "problem", ["identity", "company", "workspace", "naive", "expired", "registration"]
)
async def test_guard_does_not_accept_foreign_context_or_clock_window(
    tmp_path: Path,
    problem: str,
) -> None:
    guard, _ = await operation_guard(tmp_path)
    with pytest.raises(ValueError):
        if problem == "identity":
            guard.require_identity(
                VerifiedIdentity(
                    principal_id=UUID(int=999), workspace_id=guard.witness.identity.workspace_id
                )
            )
        elif problem == "company":
            guard.require_company(UUID(int=999))
        elif problem == "workspace":
            guard.require_identity(
                VerifiedIdentity(
                    principal_id=guard.witness.identity.principal_id, workspace_id=UUID(int=999)
                )
            )
        elif problem == "naive":
            guard.require_time(datetime.now())
        elif problem == "expired":
            guard.require_time(guard.witness.expires_at)
        else:
            guard.require_time(guard.registration.expires_at)


async def test_guard_cannot_use_bare_identity_as_sealed_credential(tmp_path: Path) -> None:
    guard, path = await operation_guard(tmp_path)
    reader = FileNotificationWorkerRegistration(path)
    with pytest.raises(ValueError):
        NotificationOperationGuard(
            cast(AuthenticatedWorkerIdentity, guard.witness.identity), reader.snapshot(), reader
        )


async def test_config_loss_is_denied_at_final_time_without_refresh(tmp_path: Path) -> None:
    guard, path = await operation_guard(tmp_path)
    path.unlink()
    with pytest.raises(ValueError):
        guard.require_time(datetime.now(UTC))


async def test_same_principal_cannot_guard_a_registration_with_other_sender_workspace(
    tmp_path: Path,
) -> None:
    guard, path = await operation_guard(tmp_path)
    original = registration()
    changed = original.model_copy(
        update={
            "workspace_id": UUID(int=999),
            "sender": original.sender.model_copy(update={"workspace_id": UUID(int=999)}),
        }
    )
    path.write_text(
        NotificationWorkerRegistrationFile(
            registration=changed, configuration=NotificationWorkerConfiguration(enabled=True)
        ).model_dump_json()
    )
    reader = FileNotificationWorkerRegistration(path)
    with pytest.raises(ValueError):
        NotificationOperationGuard(guard.witness, reader.snapshot(), reader)

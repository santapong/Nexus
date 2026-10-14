"""Worker declarations/file pins confer no owner, credential, registration or effect authority."""

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

import pytest
from pydantic import ValidationError

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.native_fact_contracts import DecisionSelector
from nexus.company.management.lifecycle import PlanRevisionRef
from nexus.company.notifications.worker_config import (
    FileNotificationWorkerRegistration,
    WorkerConfigurationError,
)
from nexus.company.notifications.worker_contracts import (
    NotificationWorkerConfiguration,
    NotificationWorkerRegistration,
    NotificationWorkerRegistrationFile,
    WorkerSubject,
)
from nexus.tests.unit.test_company_management_contracts import binding


def registration() -> NotificationWorkerRegistration:
    sender = binding(
        workflow_name="internal.owner-notification",
        workflow_version="v1",
        model_profile="notification.native.v1",
    )
    now = datetime.now(UTC)
    return NotificationWorkerRegistration(
        company_id=sender.company_id,
        workspace_id=sender.workspace_id,
        registration_id=UUID(int=990),
        sender=sender,
        plan=PlanRevisionRef(
            company_id=sender.company_id,
            plan_id=UUID(int=991),
            plan_revision_id=UUID(int=992),
            revision=1,
            sha256="a" * 64,
        ),
        catalog_sha256="b" * 64,
        notification_policy_sha256="c" * 64,
        preparation_policy_sha256="d" * 64,
        registered_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
        subjects=(
            WorkerSubject(
                selector=DecisionSelector(company_id=sender.company_id, action_id=UUID(int=993)),
                resource=ResourceRef(company_id=sender.company_id, resource_id=UUID(int=994)),
            ),
        ),
    )


def saved_file(root: Path) -> Path:
    path = root / "worker-registration.json"
    path.write_text(
        NotificationWorkerRegistrationFile(registration=registration()).model_dump_json()
    )
    path.chmod(0o600)
    assert path.stat().st_mode & 0o777 == 0o600
    return path


def test_worker_controls_default_disabled_and_have_no_authority_flags() -> None:
    config = NotificationWorkerConfiguration()
    assert not any(
        (config.enabled, config.emit_fallback, config.consume_events, config.prepare_pending)
    )
    assert config.max_events <= 32 and config.max_candidates <= 8 and config.timeout_seconds <= 30
    value = registration()
    assert value.sender.model_profile == "notification.native.v1"
    assert not hasattr(value, "approval") and not hasattr(value, "allowance_usd")


@pytest.mark.parametrize(
    "field,value",
    [
        ("enabled", 1),
        ("consume_events", "true"),
        ("max_events", 33),
        ("max_candidates", 9),
        ("timeout_seconds", 31),
        ("max_events", True),
    ],
)
def test_worker_configuration_rejects_coerced_flags_and_unbounded_limits(
    field: str, value: object
) -> None:
    with pytest.raises(ValidationError):
        NotificationWorkerConfiguration.model_validate({field: value})


@pytest.mark.parametrize(
    "problem",
    [
        "company",
        "workspace",
        "workflow",
        "profile",
        "duplicate",
        "resource_company",
        "window",
        "hash",
        "extra",
    ],
)
def test_complete_registration_rejects_malformed_unselected_declarations(problem: str) -> None:
    value = registration()
    data = value.model_dump()
    if problem == "company":
        data["company_id"] = UUID(int=999)
    elif problem == "workspace":
        data["workspace_id"] = UUID(int=999)
    elif problem in {"workflow", "profile"}:
        field = "workflow_name" if problem == "workflow" else "model_profile"
        data["sender"] = value.sender.model_dump() | {field: "internal.report"}
    elif problem == "duplicate":
        data["subjects"] = (value.subjects[0], value.subjects[0])
    elif problem == "resource_company":
        data["subjects"] = (
            value.subjects[0].model_dump()
            | {"resource": ResourceRef(company_id=UUID(int=999), resource_id=UUID(int=994))},
        )
    elif problem == "window":
        data["expires_at"] = value.registered_at
    elif problem == "hash":
        data["catalog_sha256"] = "not-a-sha"
    else:
        data["approved"] = True
    with pytest.raises(ValueError):
        NotificationWorkerRegistration.model_validate(data)


def test_declared_subject_maximum_is_bounded_and_unique() -> None:
    value = registration()
    rows = tuple(
        WorkerSubject(
            selector=DecisionSelector(company_id=value.company_id, action_id=UUID(int=1000 + i)),
            resource=value.subjects[0].resource,
        )
        for i in range(33)
    )
    with pytest.raises(ValueError):
        NotificationWorkerRegistration.model_validate(value.model_dump() | {"subjects": rows})


def test_registration_reader_constructor_performs_no_filesystem_access(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    reader = FileNotificationWorkerRegistration(missing)
    assert not missing.exists()
    with pytest.raises(WorkerConfigurationError):
        reader.snapshot()


def test_snapshot_is_exact_and_detects_content_or_inode_replacement(tmp_path: Path) -> None:
    path = saved_file(tmp_path)
    reader = FileNotificationWorkerRegistration(path)
    snapshot = reader.snapshot()
    reader.require_current(snapshot)
    replacement = tmp_path / "replacement.json"
    replacement.write_bytes(path.read_bytes())
    replacement.chmod(0o600)
    os.replace(replacement, path)
    with pytest.raises(WorkerConfigurationError):
        reader.require_current(snapshot)


@pytest.mark.parametrize(
    "problem", ["mode", "symlink", "hardlink", "large", "directory", "malformed"]
)
def test_unsafe_registration_file_is_not_a_current_pin(tmp_path: Path, problem: str) -> None:
    path = saved_file(tmp_path)
    if problem == "mode":
        path.chmod(0o644)
    elif problem == "symlink":
        target = tmp_path / "target.json"
        path.rename(target)
        path.symlink_to(target)
    elif problem == "hardlink":
        os.link(path, tmp_path / "linked.json")
    elif problem == "large":
        path.write_text("x" * 65537)
    elif problem == "directory":
        path.unlink()
        path.mkdir()
    else:
        path.write_text(json.dumps({"approval": True}))
    with pytest.raises(WorkerConfigurationError) as error:
        FileNotificationWorkerRegistration(path).snapshot()
    assert str(path) not in str(error.value)


def test_mode_loss_during_actual_read_cannot_return_a_safe_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = saved_file(tmp_path)
    original = os.read

    def changed(fd: int, count: int) -> bytes:
        raw = original(fd, count)
        path.chmod(0o644)
        return raw

    monkeypatch.setattr(os, "read", changed)
    with pytest.raises(WorkerConfigurationError):
        FileNotificationWorkerRegistration(path).snapshot()


@pytest.mark.parametrize("raw", ["{", "[" * 10000 + "0" + "]" * 10000], ids=["malformed", "deep"])
def test_malformed_or_deep_json_has_the_same_safe_configuration_denial(
    tmp_path: Path, raw: str
) -> None:
    path = saved_file(tmp_path)
    path.write_text(raw)
    with pytest.raises(WorkerConfigurationError) as error:
        FileNotificationWorkerRegistration(path).snapshot()
    assert str(error.value) == "Notification worker configuration is unavailable"


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_nonstandard_json_is_denied_before_declaration_validation(
    tmp_path: Path, constant: str
) -> None:
    path = saved_file(tmp_path)
    path.write_text('{"unselected": ' + constant + "}")
    with (
        patch.object(NotificationWorkerRegistrationFile, "model_validate_json") as decoder,
        pytest.raises(WorkerConfigurationError) as error,
    ):
        FileNotificationWorkerRegistration(path).snapshot()
    decoder.assert_not_called()
    assert str(error.value) == "Notification worker configuration is unavailable"

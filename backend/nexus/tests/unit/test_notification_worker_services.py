"""Mixed policies/runtime dependencies cannot compose a durable notification operation."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

import pytest

from nexus.company.notifications.native_facts import NotificationUnavailableError
from nexus.tests.notification_worker_phase3_unit_fixture import dispatch_services


def test_disabled_construction_does_not_read_config_credentials_or_database(tmp_path: Path) -> None:
    value = dispatch_services(tmp_path)
    assert not value.enabled and value.executor_id == "nexus-owner-notifications-v1-local"
    with pytest.raises(NotificationUnavailableError):
        value.require_enabled()
    cast(MagicMock, value.reads.factory).assert_not_called()
    assert not (tmp_path / "unread.json").exists()


@pytest.mark.parametrize(
    "field,bad",
    [
        ("enabled", 1),
        ("enabled", "true"),
        ("lease_ttl_seconds", True),
        ("lease_ttl_seconds", 0),
        ("lease_ttl_seconds", 301),
        ("executor_id", ""),
    ],
)
def test_unregistered_runtime_controls_are_rejected(
    tmp_path: Path, field: str, bad: object
) -> None:
    with pytest.raises(ValueError):
        value = dispatch_services(tmp_path)
        if field == "enabled":
            replace(value, enabled=cast(bool, bad))
        elif field == "lease_ttl_seconds":
            replace(value, lease_ttl_seconds=cast(int, bad))
        else:
            replace(value, executor_id=cast(str, bad))


@pytest.mark.parametrize(
    "boundary",
    [
        "execution_factory",
        "dispatcher_factory",
        "drafts",
        "policy",
        "effect_factory",
        "effect_catalog",
        "effect_artifacts",
        "effect_freshness",
        "read_artifacts",
    ],
)
def test_mixed_effect_or_runtime_state_is_rejected(tmp_path: Path, boundary: str) -> None:
    value = dispatch_services(tmp_path)
    if boundary == "execution_factory":
        value.execution._factory = MagicMock()
    elif boundary == "dispatcher_factory":
        value.dispatcher.factory = MagicMock()
    elif boundary == "drafts":
        value.dispatcher.drafts = MagicMock()
    elif boundary == "effect_factory":
        value.dispatcher.managed_effects._factory = MagicMock()
    elif boundary == "effect_catalog":
        value.dispatcher.managed_effects._management_catalog = None
    elif boundary == "effect_artifacts":
        value.dispatcher.managed_effects._management_artifacts = None
    elif boundary == "effect_freshness":
        value.dispatcher.managed_effects._management_freshness = None
    elif boundary == "read_artifacts":
        value.reads.preparation.artifacts = MagicMock()
    else:
        preparation = value.dispatcher.managed_effects.preparation
        preparation.policy = preparation.policy.model_copy(update={"resource_symbol": "other"})
    with pytest.raises(ValueError):
        replace(value)


@pytest.mark.parametrize(
    "field,bad",
    [
        ("workflow_name", "internal.report"),
        ("workflow_version", "v2"),
        ("queue_name", "other.queue"),
        ("application_name", "other.app"),
    ],
)
def test_fixed_scheduler_abi_cannot_be_rebound(tmp_path: Path, field: str, bad: str) -> None:
    value = dispatch_services(tmp_path)
    row = value.scheduler.policy.workflows[0].model_copy(update={field: bad})
    policy = value.scheduler.policy.model_copy(update={"workflows": (row,)})
    with pytest.raises(ValueError):
        replace(value, scheduler=replace(value.scheduler, policy=policy))

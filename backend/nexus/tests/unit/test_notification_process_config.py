"""Pure process checks deny corrupt role, command or root; no native authority is inferred."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import UUID

import pytest

from nexus.company.brain.native_fact_contracts import DecisionSelector
from nexus.company.notifications.managed_contracts import NativeNotificationSelection
from nexus.company.notifications.worker_contracts import WorkerSubject
from nexus.tests.notification_durable_unit_fixture import recovery_inputs
from nexus.tests.notification_process_config import PROCESS_ROOTS, NotificationProcessConfig
from nexus.tests.unit.test_notification_durable_dispatch_read import notification_action


async def config(root: Path, monkeypatch: pytest.MonkeyPatch) -> NotificationProcessConfig:
    # Cohesive pure fixture: all descriptive registration/action/catalog pins
    # must describe one coherent example before individual negative mutations.
    item = await recovery_inputs(root, monkeypatch)
    described = item.guard.snapshot.value.model_copy(
        update={
            "registration": item.guard.registration.model_copy(
                update={
                    "subjects": (
                        WorkerSubject(
                            selector=DecisionSelector(
                                company_id=item.command.company_id, action_id=UUID(int=102)
                            ),
                            resource=item.services.reads.facts.resource,
                        ),
                    )
                }
            )
        }
    )
    item.guard.reader._path.write_text(described.model_dump_json())
    snapshot = item.guard.reader.snapshot()
    registration = snapshot.value.registration
    selector = registration.subjects[0].selector
    assert isinstance(selector, DecisionSelector)
    response = UUID(int=991)
    return NotificationProcessConfig(
        database="nexus_company_test_notification_process_intent",
        root=PROCESS_ROOTS["nexus_company_test_notification_process_intent"],
        barrier="intent",
        catalog=item.services.reads.facts.catalog,
        registration=snapshot,
        recipient_file_sha256="a" * 64,
        command=item.command,
        action=notification_action().model_copy(
            update={
                "company_id": item.command.company_id,
                "task_id": item.command.task_id,
                "trace_id": item.command.trace_id,
                "actor_id": item.command.actor_id,
                "action_id": item.command.action_id,
                "resource": item.services.reads.preparation.policy.resource_symbol,
            }
        ),
        selection=NativeNotificationSelection(
            company_id=item.command.company_id,
            draft_id=UUID(int=30),
            sender_task_id=item.command.task_id,
            plan=registration.plan,
        ),
        notification_policy=item.services.reads.drafts.policy,
        preparation_policy=item.services.reads.preparation.policy,
        source_action_id=selector.action_id,
        credential_issued_at=item.guard.witness.issued_at,
        credential_expires_at=item.guard.witness.expires_at,
        response_uuid=response,
        response_sha256=hashlib.sha256(
            json.dumps({"id": str(response)}, separators=(",", ":")).encode()
        ).hexdigest(),
    )


async def test_process_config_roundtrips_only_descriptive_pins_and_no_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = await config(tmp_path, monkeypatch)
    assert NotificationProcessConfig.model_validate_json(value.model_dump_json()) == value
    assert "token" not in value.model_dump() and "key" not in value.model_dump()


@pytest.mark.parametrize(
    "field",
    ["company_id", "task_id", "trace_id", "actor_id", "workspace_id", "run_id", "action_id"],
)
async def test_foreign_command_cannot_choose_other_company_role_or_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    value = await config(tmp_path, monkeypatch)
    raw = value.model_dump(mode="json")
    raw["command"][field] = str(UUID(int=999))
    with pytest.raises(ValueError):
        NotificationProcessConfig.model_validate(raw)


@pytest.mark.parametrize(
    "changes",
    [
        {"root": "/tmp/arbitrary"},
        {"barrier": "response"},
        {"lease_ttl_seconds": 31},
        {"database": "nexus_company_test_notification_enqueue_atomic"},
        {"response_sha256": "0" * 64},
        {"token": "not-allowed"},
    ],
)
async def test_closed_process_case_rejects_extra_or_crossed_fixture_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changes: dict[str, object],
) -> None:
    raw = (await config(tmp_path, monkeypatch)).model_dump(mode="json") | changes
    with pytest.raises(ValueError):
        NotificationProcessConfig.model_validate(raw)

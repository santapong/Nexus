"""Public DBOS client cancellation is terminal metadata; native authorization/history survives."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from dbos import DBOSClient
from sqlalchemy import text
from sqlalchemy.engine import make_url

from nexus.company.management.base import ValueContract
from nexus.company.management.transactions import ManagementDeniedError
from nexus.company.notifications.worker_enqueue import authorize_and_enqueue_prepared_notification
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.notification_worker_services import (
    NOTIFICATION_APPLICATION,
    notification_workflow_registration,
)
from nexus.settings import settings
from nexus.tests.notification_worker_enqueue_pg_fixture import (
    AtomicNotificationDatabases,
    atomic_notification_case,
    atomic_notification_databases,
    enqueue_ledger,
)

__all__ = ["atomic_notification_databases"]


class CancelledQueueObservation(ValueContract):
    """Actual cancelled fixture row keeps immutable input/ABI but explicitly clears its queue."""

    queue_name: None
    immutable_binding: bool


async def cancelled_queue_binding(
    databases: AtomicNotificationDatabases,
    command: SegmentCommand,
) -> CancelledQueueObservation:
    """Read the real public cancellation result without rewriting status or queue metadata."""
    async with databases.admin() as session:
        saved = (
            (
                await session.execute(
                    text(
                        "SELECT ws.name,ws.queue_name,ws.application_version,ws.application_name,"
                        "ws.serialization,wi.inputs FROM dbos.workflow_status ws "
                        "JOIN dbos.workflow_input wi "
                        "ON wi.workflow_uuid=ws.workflow_uuid WHERE ws.workflow_uuid=:workflow_id"
                    ),
                    {"workflow_id": command.workflow_id},
                )
            )
            .mappings()
            .one()
        )
    registered = notification_workflow_registration()
    assert saved["queue_name"] is None
    immutable = (
        saved["name"],
        saved["application_version"],
        saved["application_name"],
        saved["serialization"],
    ) == (
        registered.workflow_name,
        registered.workflow_version,
        registered.application_name,
        "portable_json",
    ) and json.loads(saved["inputs"]) == {
        "positionalArgs": [command.model_dump_json()],
        "namedArgs": {},
    }
    return CancelledQueueObservation(queue_name=None, immutable_binding=immutable)


async def test_public_cancelled_workflow_denies_replay_and_conserves_native_history(
    atomic_notification_databases: AtomicNotificationDatabases,
    tmp_path: Path,
) -> None:
    # Cohesive >50-line process-free scenario exception: one approved native
    # command, its sole public SDK cancellation and all before/after proofs stay together.
    case = await atomic_notification_case(atomic_notification_databases.app, tmp_path)
    first = await authorize_and_enqueue_prepared_notification(
        case.services,
        case.selection,
        case.credential,
        case.snapshot,
    )
    original = await enqueue_ledger(atomic_notification_databases, case, first.command)
    assert original.queue_status == "ENQUEUED" and original.canonical_binding
    url = make_url(settings.company_test_database_url)
    assert (url.drivername, url.username, url.password, url.host, url.port, url.database) == (
        "postgresql+asyncpg",
        "santapong",
        None,
        None,
        None,
        "nexus_company_test_notification_enqueue_atomic",
    )
    assert dict(url.query) == {
        "host": "/tmp/nexus-release-tests-2026-10-13/socket",
        "port": "55438",
    }
    client = await asyncio.to_thread(
        DBOSClient,
        system_database_url=url.set(
            drivername="postgresql+psycopg",
            username="nexus_company_app",
        ).render_as_string(hide_password=False),
        application_name=NOTIFICATION_APPLICATION,
        use_listen_notify=False,
        retry_connection_errors=False,
        system_database_pool_size=1,
        system_database_polling_concurrency=1,
    )
    destroyed = False
    try:
        await client.cancel_workflow_async(first.command.workflow_id, cancel_children=False)
    finally:
        await asyncio.to_thread(client.destroy)
        destroyed = True
    assert destroyed
    cancelled = await enqueue_ledger(atomic_notification_databases, case, first.command)
    assert cancelled.queue_status == "CANCELLED" and not cancelled.canonical_binding
    cleared = await cancelled_queue_binding(atomic_notification_databases, first.command)
    assert cleared.queue_name is None and cleared.immutable_binding
    changing = {"queue_status", "queue_binding_sha256", "canonical_binding"}
    assert cancelled.model_dump(exclude=changing) == original.model_dump(exclude=changing)
    with pytest.raises(ManagementDeniedError, match="Stored DBOS workflow ABI differs"):
        await authorize_and_enqueue_prepared_notification(
            case.services,
            case.selection,
            case.credential,
            case.snapshot,
        )
    assert await enqueue_ledger(atomic_notification_databases, case, first.command) == cancelled
    assert cancelled.hold == ("0.010000", None, "held") and not case.http_calls
    receipt = {
        "scope": "Public cancellation clears queue; generic ABI denial and native conservation",
        "command": first.command.model_dump(mode="json"),
        "before": original.model_dump(mode="json"),
        "cancelled": cancelled.model_dump(mode="json"),
        "cancelled_binding": cleared.model_dump(mode="json"),
        "denial_stage": "generic_queue_ABI_before_targeted_status_guard",
        "client": {
            "role": "nexus_company_app",
            "application_name": NOTIFICATION_APPLICATION,
            "pool": 1,
            "polling_concurrency": 1,
            "use_listen_notify": False,
            "retry_connection_errors": False,
            "cancel_children": False,
            "constructor_to_thread": True,
            "destroy_to_thread": destroyed,
        },
    }
    await asyncio.to_thread(
        (tmp_path / "atomic-cancel-proof.json").write_text,
        json.dumps(receipt, indent=2) + "\n",
    )

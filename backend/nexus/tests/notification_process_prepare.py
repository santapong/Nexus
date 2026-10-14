"""TEST-only public preparation of one new OS case; no worker launch or source refresh."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import jwt
from pydantic import SecretStr, TypeAdapter

from nexus.company.management.native_profile_admission import ledger_scope
from nexus.company.notifications.worker_enqueue import authorize_and_enqueue_prepared_notification
from nexus.company.notifications.worker_identity import NotificationWorkerIdentities
from nexus.harness.journal import CompanyJournal
from nexus.tests.notification_durable_pg_fixture import (
    DurableNotificationCase,
    durable_notification_database_scope,
)
from nexus.tests.notification_durable_pg_proof import durable_queued_window
from nexus.tests.notification_process_config import (
    NotificationBarrier,
    NotificationProcessConfig,
    NotificationProcessDatabase,
    require_notification_process_root,
)
from nexus.tests.notification_worker_credential_fixture import TEST_KEY
from nexus.tests.notification_worker_enqueue_pg_fixture import (
    atomic_notification_case,
    enqueue_ledger,
)
from nexus.tests.notification_worker_tick_services_fixture import SyntheticTickCredential


async def prepare_notification_process_case(
    database: NotificationProcessDatabase,
    root: Path,
) -> tuple[NotificationProcessConfig, SecretStr]:
    """One initial180s worker token before admission; return it in memory, never persist it."""
    # Cohesive preparation exception: fresh public setup/approval/atomicenqueue
    # and exact immutable source/config pins must describe one never-launched case.
    require_notification_process_root(database, root, existing=False)
    root.mkdir(mode=0o700)
    async with durable_notification_database_scope(database) as env:
        initial = await atomic_notification_case(env.databases.app, root)
        binding = initial.snapshot.value.registration.sender
        now = int(datetime.now(UTC).timestamp())
        token = SecretStr(
            jwt.encode(
                {
                    "sub": str(binding.actor_id),
                    "workspace_id": str(binding.workspace_id),
                    "iat": now - 1,
                    "exp": now + 180,
                },
                TEST_KEY,
                algorithm="HS256",
            )
        )
        identities = NotificationWorkerIdentities(
            SyntheticTickCredential(token), SecretStr(TEST_KEY), enabled=True
        )
        reads = replace(initial.services.reads, identities=identities)
        services = replace(initial.services, reads=reads, lease_ttl_seconds=30)
        witness = await identities.current(expected_binding=binding)
        case = replace(initial, services=services, credential=witness)
        queued = await authorize_and_enqueue_prepared_notification(
            services, case.selection, witness, case.snapshot
        )
        observed = await enqueue_ledger(env.databases, case, queued.command)
        assert observed.queue_status == "ENQUEUED" and observed.canonical_binding
        assert observed.effect_counts == (0, 0, 0, 0) and not case.http_calls
        window = await durable_queued_window(env.databases, DurableNotificationCase(case, []))
        record = await CompanyJournal(env.databases.app).get_action(
            ledger_scope(binding), queued.command.action_id
        )
        response = uuid4()
        response_raw = json.dumps({"id": str(response)}, separators=(",", ":")).encode()
        config = NotificationProcessConfig(
            database=database,
            root=root,
            barrier=TypeAdapter(NotificationBarrier).validate_python(
                database.rsplit("_", 1)[-1], strict=True
            ),
            catalog=reads.facts.catalog,
            registration=case.snapshot,
            recipient_file_sha256=hashlib.sha256(
                (root / "synthetic-worker-recipient.json").read_bytes()
            ).hexdigest(),
            command=queued.command,
            action=record.proposal,
            selection=case.selection,
            notification_policy=reads.drafts.policy,
            preparation_policy=reads.preparation.policy,
            source_action_id=case.source_action_id,
            credential_issued_at=witness.issued_at,
            credential_expires_at=witness.expires_at,
            response_uuid=response,
            response_sha256=hashlib.sha256(response_raw).hexdigest(),
        )
        for name, raw in (
            ("notification-process-config.json", config.model_dump_json()),
            ("command.json", queued.command.model_dump_json()),
            (
                "preparation-proof.json",
                json.dumps(
                    {
                        "queued": queued.model_dump(mode="json"),
                        "ledger": observed.model_dump(mode="json"),
                        "initial_window": window,
                        "owner_decision_sha256": case.decision_sha256,
                    },
                    indent=2,
                ),
            ),
        ):
            path = root / name
            path.write_text(raw + "\n")
            path.chmod(0o600)
        # env.complete intentionally stays False: every OS case DB/tree is retained.
        return config, token

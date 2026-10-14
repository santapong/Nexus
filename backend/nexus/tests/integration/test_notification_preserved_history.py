"""Continue original already-issued synthetic history only; no setup, SDK or new HTTP."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from nexus.company.management.canonical import canonical_sha256
from nexus.execution.notification_worker import execute_notification_segment
from nexus.tests.notification_durable_pg_proof import durable_notification_proof
from nexus.tests.notification_preserved_history_fixture import preserved_notification_case


async def test_preserved_actual_sdk_history_native_replay_has_no_new_effects(
    tmp_path: Path,
) -> None:
    # Cohesive history scenario: actual before/after hashes and one new fenced
    # audit lease are evaluated together without another send or private-body read.
    async with preserved_notification_case() as retained:
        before = await durable_notification_proof(
            retained.databases, retained.case, retained.command
        )
        assert before.queue_status == "SUCCESS" and before.receipt.outcome == "succeeded"
        assert before.native_counts == (1, 1, 1, 1) and before.current_fence == 2
        assert before.hold == ("0.010000", None, "unknown") and before.lease_released
        assert canonical_sha256(before.receipt) == retained.original_receipt_sha256
        assert canonical_sha256(before.observation) == retained.original_observation_sha256
        await asyncio.to_thread(
            (tmp_path / "preserved-history-before.json").write_text,
            before.model_dump_json(indent=2) + "\n",
        )
        result = await execute_notification_segment(
            retained.case.atomic.services,
            retained.command,
            workflow_id=retained.command.workflow_id,
        )
        after = await durable_notification_proof(
            retained.databases, retained.case, retained.command
        )
        assert (
            result.status == "submitted"
            and result.receipt_sha256 == retained.original_receipt_sha256
        )
        assert result.observation_sha256 == retained.original_observation_sha256
        assert after.model_dump(exclude={"current_fence"}) == before.model_dump(
            exclude={"current_fence"}
        )
        assert after.current_fence > before.current_fence and after.lease_released
        assert not retained.http_attempts and retained.blobs.reads == retained.blobs.writes == 0
        assert retained.drafts.body_reads == 0
        assert retained.sql_guard.checked > 0 and retained.sql_guard.body_sql_attempts == 0
        proof = {
            "scope": "Original issued native history only; NEW current synthetic audit credential",
            "original_token_expired": retained.original_credential_expires_at
            <= retained.actual_audit_db_clock,
            "original_credential_expires_at": retained.original_credential_expires_at.isoformat(),
            "actual_audit_db_clock": retained.actual_audit_db_clock.isoformat(),
            "original_registration_sha256": retained.original_registration_sha256,
            "original_decision_sha256": retained.original_decision_sha256,
            "original_recipient_sha256": retained.original_recipient_sha256,
            "original_recipient_registered": retained.original_recipient_registered_at.isoformat(),
            "original_recipient_expires_at": retained.original_recipient_expires_at.isoformat(),
            "command": retained.command.model_dump(mode="json"),
            "before": before.model_dump(mode="json"),
            "after": after.model_dump(mode="json"),
            "result": result.model_dump(mode="json"),
            "new_http": 0,
            "blob_reads": 0,
            "draft_body_reads": 0,
            "body_sql_attempts": retained.sql_guard.body_sql_attempts,
            "sql_guard_statements_checked": retained.sql_guard.checked,
            "audit_credential_issued_at": retained.case.atomic.credential.issued_at.isoformat(),
            "audit_credential_expires_at": retained.case.atomic.credential.expires_at.isoformat(),
        }
        await asyncio.to_thread(
            (tmp_path / "preserved-history-replay-proof.json").write_text,
            json.dumps(proof, indent=2) + "\n",
        )

"""Actual fixed SDK execution and native replay with synthetic local HTTP only."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from nexus.company.notifications.worker_enqueue import authorize_and_enqueue_prepared_notification
from nexus.execution.notification_worker import execute_notification_segment
from nexus.tests.notification_durable_pg_fixture import (
    DurableNotificationEnvironment,
    durable_notification_case,
    durable_notification_environment,
    sdk_notification_result,
)
from nexus.tests.notification_durable_pg_proof import (
    durable_notification_proof,
    durable_queued_window,
)
from nexus.tests.notification_worker_enqueue_pg_fixture import enqueue_ledger

__all__ = ["durable_notification_environment"]


@pytest.mark.parametrize(
    "outcome,status",
    [
        ("accepted", "submitted"),
        ("rejected", "rejected"),
        ("unknown", "outcome_unknown"),
    ],
)
async def test_actual_sdk_one_mock_post_and_native_replay_conserve_original_history(
    durable_notification_environment: DurableNotificationEnvironment,
    tmp_path: Path,
    outcome: str,
    status: str,
) -> None:
    # Cohesive scenario exception: real enqueue, SDK native result and separate
    # post-SDK native replay must conserve one original effect and money together.
    env = durable_notification_environment
    async with durable_notification_case(tmp_path, outcome) as case:
        first = await authorize_and_enqueue_prepared_notification(
            case.atomic.services,
            case.atomic.selection,
            case.atomic.credential,
            case.atomic.snapshot,
        )
        before = await enqueue_ledger(env.databases, case.atomic, first.command)
        assert before.queue_status == "ENQUEUED" and before.canonical_binding
        assert before.effect_counts == (0, 0, 0, 0) and not case.requests
        window = await durable_queued_window(env.databases, case)
        await asyncio.to_thread(
            (tmp_path / "durable-phase-proof.json").write_text,
            json.dumps(
                {
                    "phase": "queued_before_sdk",
                    "command": first.command.model_dump(mode="json"),
                    "before": before.model_dump(mode="json"),
                    "window": window,
                },
                indent=2,
            )
            + "\n",
        )
        sdk = await sdk_notification_result(
            case.atomic.services, first.command, root=tmp_path, databases=env.databases
        )
        assert sdk.status == status and sdk.billing == "unconfirmed"
        original = await durable_notification_proof(env.databases, case, first.command)
        await asyncio.to_thread(
            (tmp_path / "durable-sdk-native-proof.json").write_text,
            json.dumps(
                {"sdk": sdk.model_dump(mode="json"), "original": original.model_dump(mode="json")},
                indent=2,
            )
            + "\n",
        )
        assert original.queue_status == "SUCCESS" and original.sdk_output == sdk.model_dump_json()
        assert original.step_names == ("nexus.notification.effect.v1",)
        assert original.native_counts == (1, 1, 1, 1)
        assert original.hold == ("0.010000", None, "unknown")
        assert original.intent_fence == original.slot_intent_fence
        assert original.tool_attempts == 1 and original.model_requests == 0
        assert original.lease_released and original.source_action_state == "awaiting_approval"
        assert len(case.requests) == 1 and case.requests[0].method == "POST"
        replay_services = replace(case.atomic.services, worker_id=uuid4())
        assert replay_services.executor_id == case.atomic.services.executor_id
        replay = await execute_notification_segment(
            replay_services, first.command, workflow_id=first.command.workflow_id
        )
        assert replay.status == status
        assert (
            replay.receipt_id,
            replay.receipt_sha256,
            replay.observation_id,
            replay.observation_sha256,
        ) == (sdk.receipt_id, sdk.receipt_sha256, sdk.observation_id, sdk.observation_sha256)
        after = await durable_notification_proof(env.databases, case, first.command)
        assert after.model_dump(exclude={"current_fence"}) == original.model_dump(
            exclude={"current_fence"}
        )
        assert after.current_fence > original.current_fence and len(case.requests) == 1
        proof = {
            "scope": "Actual synthetic SDK one POST plus native replay; no real delivery",
            "outcome": outcome,
            "command": first.command.model_dump(mode="json"),
            "sdk": sdk.model_dump(mode="json"),
            "native_replay": replay.model_dump(mode="json"),
            "original": original.model_dump(mode="json"),
            "after": after.model_dump(mode="json"),
            "requests": [x.model_dump(mode="json") for x in case.requests],
            "credential_issued_at": case.atomic.credential.issued_at.isoformat(),
            "credential_expires_at": case.atomic.credential.expires_at.isoformat(),
            "initial_window": window,
        }
        await asyncio.to_thread(
            (tmp_path / "durable-notification-proof.json").write_text,
            json.dumps(proof, indent=2) + "\n",
        )
    env.complete = True

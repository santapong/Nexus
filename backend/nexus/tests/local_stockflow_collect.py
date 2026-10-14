"""Read-only collection after the test-only PK error; never claim, issue, reconcile or invoke."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.builder.artifact_publisher import BuilderArtifactPublisher
from nexus.builder.native_state import result_disclosure
from nexus.builder.process import engine_environment
from nexus.builder.result_store import BuilderResultStore
from nexus.builder.source_guard import BuilderSourceGuard, RegisteredBuilderSource
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.execution.effect_support import effect_record
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt
from nexus.execution.runtime_store import ExecutionStore
from nexus.execution.runtime_support import lease_scope, runtime_transaction
from nexus.harness.canonical import action_hash
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_models import CostHold
from nexus.settings import settings
from nexus.tests.builder_stockflow_support import REPOSITORY
from nexus.tests.integration.management_acceptance_source_fixture import Policies
from nexus.tests.integration.test_company_directory import ACTOR
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.local_stockflow_packet import ROOT, write_private
from nexus.tests.stockflow_packet_contracts import PreparedState, ReviewPacket

PACKET_SHA = "320a09aa1c897de63188787b71615430b5d83e6f4b1c27c1dbd5f9df18ce025e"


async def collect() -> None:
    packet_raw = await asyncio.to_thread((ROOT / "prelaunch.json").read_bytes)
    packet = ReviewPacket.model_validate_json(packet_raw)
    raw = await asyncio.to_thread((ROOT / "native-state.json").read_bytes)
    if (
        hashlib.sha256(packet_raw).hexdigest() != PACKET_SHA
        or hashlib.sha256(raw).hexdigest() != packet.state_sha256
    ):
        raise ValueError("Reviewed packet/prepared native state changed")
    state = PreparedState.model_validate_json(raw)
    url = make_url(settings.company_test_database_url)
    if url.database != "nexus_company_test_builder":
        raise ValueError("Only the assigned builder database is supported")
    engine = create_async_engine(url.set(username="nexus_company_app"))
    try:
        await _collect(async_sessionmaker(engine, expire_on_commit=False), state, packet)
    finally:
        await engine.dispose()


async def _collect(
    factory: async_sessionmaker[AsyncSession],
    state: PreparedState,
    packet: ReviewPacket,
    destination: Path | None = None,
) -> None:
    scope = lease_scope(state.released_lease)
    blobs, policies = ProtectedBlobStore(ROOT, storage_symbol="fixture.blobs.v1"), Policies()
    policies.values[state.source_policy.source_symbol] = state.source_policy
    artifacts = BoundedArtifactReader(factory, blobs)
    guard = BuilderSourceGuard(
        state.spec,
        state.policy,
        state.released_lease,
        identity(ACTOR),
        RegisteredBuilderSource(REPOSITORY, state.metadata),
        artifacts,
        RegisteredSourceFreshness(factory, policies),
        state.catalog,
    )
    if not await result_disclosure(factory, state.released_lease, identity(ACTOR), guard):
        raise ValueError("Current complete source READ/freshness denies saved result disclosure")
    result = await BuilderResultStore(ROOT / "results").load(state.spec)
    if result is None:
        raise ValueError("No saved native result")
    current = await ExecutionStore(factory).get(scope, identity(ACTOR))
    action = await CompanyJournal(factory).get_action(scope, state.action.action_id)
    async with runtime_transaction(
        factory, scope, identity(ACTOR), allow_paused=True, allow_inactive=True
    ) as (session, _, _):
        row = await session.get(EffectIntent, (state.spec.job.company_id, state.action.action_id))
        if row is None:
            raise ValueError("Native intent/receipt is absent")
        native = effect_record(row)
        holds = tuple(
            (
                await session.scalars(
                    select(CostHold).where(
                        CostHold.company_id == state.spec.job.company_id,
                        CostHold.task_id == state.spec.job.task_id,
                    )
                )
            ).all()
        )
        attempts = await session.scalar(
            select(func.count())
            .select_from(ExecutionAttempt)
            .where(
                ExecutionAttempt.company_id == state.spec.job.company_id,
                ExecutionAttempt.task_id == state.spec.job.task_id,
            )
        )
    assert state.spec.output_resource is not None
    publisher = BuilderArtifactPublisher(
        factory, blobs, state.spec.output_resource, policies.policy("fixture.source.v1")
    )
    ref = publisher.reference(result)
    protected = await artifacts.bounded_artifact(
        guard.scope(),
        identity(ACTOR),
        ref.artifact_revision_id,
        start_byte=0,
        max_bytes=16384,
        include_history=False,
    )
    if (
        native.proposal_hash != action_hash(state.action)
        or native.intent_fence != result.intent_fence
        or native.receipt is None
        or native.receipt.artifacts[0].sha256 != ref.sha256
        or protected.artifact != ref
        or protected.text.encode() != publisher.payload(result)
        or not await result_disclosure(factory, state.released_lease, identity(ACTOR), guard)
    ):
        raise ValueError("Current saved result/native receipt/protected bytes differ")
    cleanup = await container_absent(result.container_name)
    receipt = {
        "scope": packet.scope,
        "source_event": packet.source_event,
        "source_commit_event": "2026-09-01T13:56:41+07:00",
        "actual_argv": packet.actual_argv,
        "collector": "read-only known saved result; original PK failure retained; no reissue",
        "result": result.model_dump(exclude={"logs", "artifacts"}, mode="json"),
        "logs": [row.metadata.model_dump(mode="json") for row in result.logs],
        "artifacts": [row.metadata.model_dump(mode="json") for row in result.artifacts],
        "result_sha256": BuilderResultStore.digest(result),
        "protected_ref": ref.model_dump(mode="json"),
        "protected_source_state": protected.source_state,
        "native": native.model_dump(mode="json"),
        "current_execution": current.model_dump(mode="json"),
        "journal_state": action.state.value,
        "actual_attempt_rows": attempts,
        "holds": [
            {
                "action_id": str(r.action_id),
                "state": r.state,
                "reserved_usd": str(r.amount_usd),
                "actual_usd": str(r.actual_usd) if r.actual_usd is not None else None,
            }
            for r in holds
        ],
        "cleanup": cleanup,
        "project_reexecutions": 0,
        "work_acceptance": "none",
        "arm64": "unqualified",
        "business_readiness": "not inferred",
        "engineering_patch": "none",
    }
    await asyncio.to_thread(
        write_private,
        destination or ROOT / "first-run-receipt.json",
        json.dumps(receipt, indent=2).encode(),
    )


async def container_absent(name: str) -> dict[str, object]:
    process = await asyncio.create_subprocess_exec(
        "/usr/bin/podman",
        "--remote=false",
        "container",
        "exists",
        name,
        env=engine_environment(),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    async with asyncio.timeout(5):
        code = await process.wait()
    return {"name": name, "exists_exit": code, "absent": code == 1, "shared_prune": False}


if __name__ == "__main__":
    asyncio.run(collect())

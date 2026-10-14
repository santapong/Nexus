"""Manual reviewed packet execution: actual current native claim/intent, never a worker default."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.builder.artifact_publisher import BuilderArtifactPublisher
from nexus.builder.execution_contracts import BuilderExecutionSpec, BuilderRunResult
from nexus.builder.node_runner import NodeNativeBuilderRunner
from nexus.builder.node_runtime_plan import node_argv
from nexus.builder.result_store import BuilderResultStore
from nexus.builder.runtime_plan import PreparedSources
from nexus.builder.source_guard import BuilderSourceGuard, RegisteredBuilderSource
from nexus.company.access import VerifiedIdentity
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.execution.effect_store import EffectStore
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt
from nexus.execution.runtime_store import ExecutionStore
from nexus.execution.runtime_support import lease_scope, runtime_transaction
from nexus.harness.canonical import action_hash
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import CostHold
from nexus.settings import settings
from nexus.tests.builder_node_support import IMAGE_ID
from nexus.tests.builder_stockflow_support import REPOSITORY, public_config
from nexus.tests.integration.management_acceptance_source_fixture import Policies
from nexus.tests.integration.test_company_directory import ACTOR
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.local_stockflow_packet import ROOT, write_private
from nexus.tests.stockflow_packet_contracts import PreparedState, ReviewPacket


class PacketRunner(NodeNativeBuilderRunner):
    expected_argv: tuple[str, ...] = ()
    actual_argv: tuple[str, ...] = ()
    calls: int = 0

    async def invoke(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        action: ActionProposal,
        spec: BuilderExecutionSpec,
        guard: BuilderSourceGuard,
        base: Path,
    ) -> BuilderRunResult:
        argv = node_argv(
            spec,
            self.policy,
            self.capabilities,
            PreparedSources(base / "baseline", base / "post"),
            base,
            self.config,
        )
        if argv != self.expected_argv or self.calls:
            raise ValueError("Actual one-process engine argv differs from reviewed packet")
        self.calls += 1
        self.actual_argv = argv
        return await super().invoke(lease, identity, action, spec, guard, base)


async def execute(expected_packet_sha256: str) -> None:
    packet_raw = await asyncio.to_thread((ROOT / "prelaunch.json").read_bytes)
    if hashlib.sha256(packet_raw).hexdigest() != expected_packet_sha256:
        raise ValueError("Reviewed exact prelaunch packet changed")
    packet = ReviewPacket.model_validate_json(packet_raw)
    raw = await asyncio.to_thread((ROOT / "native-state.json").read_bytes)
    if hashlib.sha256(raw).hexdigest() != packet.state_sha256:
        raise ValueError("Prepared native state differs from reviewed packet")
    state = PreparedState.model_validate_json(raw)
    url = make_url(settings.company_test_database_url)
    if url.database != "nexus_company_test_builder":
        raise ValueError("Only assigned disposable builder database is supported")
    engine = create_async_engine(url.set(username="nexus_company_app"))
    try:
        await _run(async_sessionmaker(engine, expire_on_commit=False), state, packet)
    finally:
        await engine.dispose()


async def _run(
    factory: async_sessionmaker[AsyncSession],
    state: PreparedState,
    packet: ReviewPacket,
    observation_root: Path = ROOT,
) -> None:
    spec, action, policy, catalog = state.spec, state.action, state.policy, state.catalog
    if action_hash(action) != packet.action_sha256 or action.parameters != spec.model_dump(
        mode="json"
    ):
        raise ValueError("Native exact approval/proposal descriptor differs")
    config = public_config()
    if config.pins != spec.runtime_inputs or state.source_repository != str(REPOSITORY):
        raise ValueError("Server-qualified Node/source inputs differ from reviewed proposal")
    blobs, policies = ProtectedBlobStore(ROOT, storage_symbol="fixture.blobs.v1"), Policies()
    source_policy = state.source_policy
    policies.values[source_policy.source_symbol] = source_policy
    artifacts = BoundedArtifactReader(factory, blobs)
    freshness = RegisteredSourceFreshness(factory, policies)
    execution = ExecutionStore(
        factory,
        management_catalog=catalog,
        management_artifacts=artifacts,
        management_freshness=freshness,
    )
    effects = EffectStore(
        factory,
        management_catalog=catalog,
        management_artifacts=artifacts,
        management_freshness=freshness,
    )
    scope = LedgerScope(
        company_id=spec.job.company_id,
        task_id=spec.job.task_id,
        trace_id=spec.job.trace_id,
        principal_id=ACTOR,
    )
    lease = await execution.claim(scope, identity(ACTOR), uuid4(), ttl_seconds=60)
    guard = BuilderSourceGuard(
        spec,
        policy,
        lease,
        identity(ACTOR),
        RegisteredBuilderSource(REPOSITORY, state.metadata),
        artifacts,
        freshness,
        catalog,
    )
    assert spec.output_resource is not None
    publisher = BuilderArtifactPublisher(
        factory, blobs, spec.output_resource, policies.policy("fixture.source.v1")
    )
    runner = PacketRunner(
        factory,
        execution,
        effects,
        policy,
        state.capabilities,
        IMAGE_ID,
        BuilderResultStore(ROOT / "results"),
        ROOT / "jobs",
        publisher,
        config,
    )
    await _invoke_exact(factory, runner, lease, action, spec, guard, packet, observation_root)


async def _invoke_exact(
    factory: async_sessionmaker[AsyncSession],
    runner: PacketRunner,
    lease: ExecutionLease,
    action: ActionProposal,
    spec: BuilderExecutionSpec,
    guard: BuilderSourceGuard,
    packet: ReviewPacket,
    observation_root: Path = ROOT,
) -> None:
    runner.expected_argv = packet.actual_argv
    result = await runner.run(lease, identity(ACTOR), action, spec, guard)
    async with runtime_transaction(
        factory, lease_scope(guard.lease), identity(ACTOR), allow_paused=True
    ) as (session, _, _):
        row = await session.get(EffectIntent, (spec.job.company_id, action.action_id))
        hold = await session.get(CostHold, action.action_id)
        native = {
            "intent_state": row.state if row else None,
            "receipt_present": row.receipt_json is not None if row else False,
            "actual_usd": str(hold.actual_usd) if hold and hold.actual_usd is not None else None,
            "hold_usd": str(hold.amount_usd) if hold else None,
            "hold_state": hold.state if hold else None,
            "attempts": await session.scalar(
                select(func.count())
                .select_from(ExecutionAttempt)
                .where(
                    ExecutionAttempt.company_id == spec.job.company_id,
                    ExecutionAttempt.task_id == spec.job.task_id,
                )
            ),
        }
    receipt = {
        "scope": packet.scope,
        "source_event": packet.source_event,
        "action_sha256": action_hash(action),
        "actual_argv": runner.actual_argv,
        "process_calls": runner.calls,
        "native": native,
        "current_source_disclosure": result is not None,
        "outcome": result.outcome if result else "source_disclosure_unavailable",
        "commands": [row.model_dump(mode="json") for row in result.commands] if result else [],
        "result_sha256": BuilderResultStore.digest(result) if result else None,
        "work_acceptance": "not published",
        "arm64": "not qualified",
        "business_readiness": "not inferred",
        "engineering_patch": "none",
    }
    await asyncio.to_thread(
        write_private,
        observation_root / "first-run-receipt.json",
        json.dumps(receipt, indent=2).encode(),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet-sha256", required=True)
    asyncio.run(execute(parser.parse_args().packet_sha256))

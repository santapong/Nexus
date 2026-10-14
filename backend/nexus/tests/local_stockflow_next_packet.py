"""Exact v2 packet on genuinely partitioned sibling; no project process or intent."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from nexus.builder.execution_contracts import BuilderExecutionSpec
from nexus.builder.native_state import current_source
from nexus.builder.node_recipe import loopback_hosts
from nexus.builder.node_runtime_plan import node_argv
from nexus.builder.runtime_plan import PreparedSources
from nexus.builder.snapshot import committed_archive
from nexus.builder.source_guard import BuilderSourceGuard, RegisteredBuilderSource
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.lifecycle import PlanRevision
from nexus.company.management.owner_view_store import ManagementOwnerViews
from nexus.execution.runtime_models import EffectIntent
from nexus.execution.runtime_store import ExecutionStore
from nexus.execution.runtime_support import lease_scope, runtime_transaction
from nexus.harness.canonical import action_hash
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import CostHold
from nexus.settings import settings
from nexus.tests.builder_stockflow_support import REPOSITORY, public_config
from nexus.tests.integration.management_acceptance_source_fixture import Policies
from nexus.tests.integration.test_company_directory import ACTOR, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.local_stockflow_packet import ROOT, inspection_files, write_private
from nexus.tests.stockflow_packet_contracts import PreparedState

NEXT_ROOT = ROOT / "node-v2-sibling"


async def prepare(
    *,
    preparation_state: Path = ROOT / "accepted-preparation-state.json",
    partition_receipt: Path = ROOT / "sibling-revision-receipt.json",
    destination: Path = NEXT_ROOT,
    policy_symbol: str = "stockflow.nominated.node.v2",
    model_receipt: Path = ROOT / "model-requalification-receipt.json",
    source_receipt: Path = ROOT / "source-reobservation-accepted-receipt.json",
) -> None:
    state = PreparedState.model_validate_json(await asyncio.to_thread(preparation_state.read_bytes))
    revisions = json.loads(await asyncio.to_thread(partition_receipt.read_bytes))
    approved = PlanRevision.model_validate_json(json.dumps(revisions["approved"]))
    binding = approved.payload.children[-2].binding
    pins = public_config().pins
    policy = state.policy.model_copy(
        update={"runtime_inputs": pins, "policy_symbol": policy_symbol}
    )
    job = state.spec.job.model_copy(
        update={
            "task_id": binding.task_id,
            "trace_id": binding.trace_id,
            "run_id": binding.run_id,
            "workspace_id": binding.workspace_id,
            "actor_id": binding.actor_id,
            "action_id": uuid4(),
            "policy_symbol": policy.policy_symbol,
        }
    )
    spec = BuilderExecutionSpec(
        job=job,
        policy_sha256=canonical_sha256(policy),
        runtime_inputs=pins,
        output_resource=state.spec.output_resource,
    )
    action = state.action.model_copy(
        update={
            "action_id": job.action_id,
            "task_id": job.task_id,
            "trace_id": job.trace_id,
            "actor_id": job.actor_id,
            "parameters": spec.model_dump(mode="json"),
        }
    )
    url = make_url(settings.company_test_database_url)
    if url.database != "nexus_company_test_builder":
        raise ValueError("Assigned retained builder DB only")
    engine = create_async_engine(url.set(username="nexus_company_app"))
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        view = await ManagementOwnerViews(factory).plan(
            control(), identity(OWNER), approved.plan_id
        )
        if view.reference.plan_revision_id != approved.plan_revision_id or view.state != "approved":
            raise ValueError("Exact sibling approved plan no longer current")
        scope = LedgerScope(
            company_id=job.company_id,
            task_id=job.task_id,
            trace_id=job.trace_id,
            principal_id=ACTOR,
        )
        journal = CompanyJournal(factory)
        await journal.submit(action, scope)
        await journal.approve_registered(
            scope.model_copy(update={"principal_id": OWNER}),
            action.action_id,
            action_hash(action),
            datetime.now(UTC),
            identity=identity(OWNER),
        )
        await journal.authorize_registered(
            scope, action.action_id, datetime.now(UTC), (), identity=identity(ACTOR)
        )
        policies = Policies()
        policies.values[state.source_policy.source_symbol] = state.source_policy
        artifacts = BoundedArtifactReader(
            factory, ProtectedBlobStore(ROOT, storage_symbol="fixture.blobs.v1")
        )
        freshness = RegisteredSourceFreshness(factory, policies)
        execution = ExecutionStore(
            factory,
            management_catalog=state.catalog,
            management_artifacts=artifacts,
            management_freshness=freshness,
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
            state.catalog,
        )
        await current_source(factory, lease, identity(ACTOR), action, guard, issued=False)
        await execution.release(lease, identity(ACTOR))
        destination.mkdir(mode=0o700, exist_ok=True)
        base = destination / "argv-inspection"
        raw = await committed_archive(REPOSITORY, job.source)
        await asyncio.to_thread(
            inspection_files, base, raw, spec.model_dump_json(), policy.model_dump_json()
        )
        await asyncio.to_thread(write_private, base / "loopback-hosts", loopback_hosts().encode())
        argv = node_argv(
            spec,
            policy,
            state.capabilities,
            PreparedSources(base / "baseline", base / "post"),
            base,
            public_config(),
        )
        actual_base = ROOT / "jobs" / f"{job.company_id.hex}-{job.action_id.hex}"
        argv = tuple(value.replace(str(base), str(actual_base)) for value in argv)
        current = PreparedState.model_validate_json(
            state.model_copy(
                update={"spec": spec, "policy": policy, "action": action, "released_lease": lease}
            ).model_dump_json()
        )
        state_raw = current.model_dump_json(indent=2).encode()
        await asyncio.to_thread(write_private, destination / "native-state.json", state_raw)
        async with runtime_transaction(
            factory, lease_scope(lease), identity(ACTOR), allow_paused=True
        ) as (session, _, _):
            intents = await session.scalar(
                select(func.count())
                .select_from(EffectIntent)
                .where(EffectIntent.task_id == job.task_id)
            )
            holds = tuple(
                (
                    await session.scalars(
                        select(CostHold).where(CostHold.company_id == job.company_id)
                    )
                ).all()
            )
        packet = {
            "scope": "same-root sibling; actual nominated historical source, prepared only",
            "source_event": "Sep1 bb7 commit; unchanged baseline/post qualification",
            "state_sha256": hashlib.sha256(state_raw).hexdigest(),
            "action_sha256": action_hash(action),
            "action": action.model_dump(mode="json"),
            "spec": spec.model_dump(mode="json"),
            "policy": policy.model_dump(mode="json"),
            "actual_argv": argv,
            "current_plan": view.reference.model_dump(mode="json"),
            "prepared_native_intents": intents,
            "lease_released": True,
            "project_processes_started": 0,
            "parent_and_old_children_preserved": True,
            "sibling_partition_receipt_sha256": hashlib.sha256(
                await asyncio.to_thread(partition_receipt.read_bytes)
            ).hexdigest(),
            "holds": [
                {
                    "action_id": str(row.action_id),
                    "state": row.state,
                    "reserved_usd": str(row.amount_usd),
                    "actual_usd": str(row.actual_usd) if row.actual_usd is not None else None,
                }
                for row in holds
            ],
            "model_requalification_receipt_sha256": hashlib.sha256(
                await asyncio.to_thread(model_receipt.read_bytes)
            ).hexdigest(),
            "model_expiry": state.catalog.model_observations[0].health.expires_at.isoformat(),
            "source_reobservation_receipt_sha256": hashlib.sha256(
                await asyncio.to_thread(source_receipt.read_bytes)
            ).hexdigest(),
        }
        await asyncio.to_thread(
            write_private, destination / "prelaunch.json", json.dumps(packet, indent=2).encode()
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(prepare())

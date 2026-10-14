"""Actual public claim/known-receipt recovery; project invocation is forbidden."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from nexus.builder.artifact_publisher import BuilderArtifactPublisher
from nexus.builder.execution_contracts import BuilderRunResult
from nexus.builder.node_runner import NodeNativeBuilderRunner
from nexus.builder.result_store import BuilderResultStore
from nexus.builder.source_guard import BuilderSourceGuard, RegisteredBuilderSource
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.execution.effect_store import EffectStore
from nexus.execution.runtime_store import ExecutionStore
from nexus.execution.runtime_support import lease_scope
from nexus.settings import settings
from nexus.tests.builder_node_support import IMAGE_ID
from nexus.tests.builder_stockflow_support import REPOSITORY, public_config
from nexus.tests.integration.management_acceptance_source_fixture import Policies
from nexus.tests.integration.test_company_directory import ACTOR
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.local_stockflow_packet import ROOT, write_private
from nexus.tests.stockflow_packet_contracts import PreparedState

ORIGINAL_RESULT_SHA256 = "861ae1b8ba91a935619c8bc76bdbdc72f9dd70c80733dc976be0d6f6bf764195"


class RecoveryOnly(NodeNativeBuilderRunner):
    async def prepare(self, *args: object, **kwargs: object) -> Path:
        raise AssertionError("Known recovery cannot prepare a new project run")

    async def invoke(self, *args: object, **kwargs: object) -> BuilderRunResult:
        raise AssertionError("Known recovery cannot invoke a project process")


async def recover(
    state_path: Path = ROOT / "native-state.json",
    catalog_path: Path | None = None,
    receipt_path: Path = ROOT / "v1-recovery-receipt.json",
    expected_result_sha256: str = ORIGINAL_RESULT_SHA256,
) -> None:
    state = PreparedState.model_validate_json(await asyncio.to_thread(state_path.read_bytes))
    if catalog_path is not None:
        catalog = PlanAdmissionCatalog.model_validate_json(
            await asyncio.to_thread(catalog_path.read_bytes)
        )
        if state.catalog.models != catalog.models:
            raise ValueError("Current observation changed immutable model registrations")
        state = state.model_copy(update={"catalog": catalog})
    url = make_url(settings.company_test_database_url)
    if url.database != "nexus_company_test_builder":
        raise ValueError("Only retained builder database is supported")
    engine = create_async_engine(url.set(username="nexus_company_app"))
    lease = None
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        scope = lease_scope(state.released_lease)
        policies = Policies()
        policies.values[state.source_policy.source_symbol] = state.source_policy
        blobs = ProtectedBlobStore(ROOT, storage_symbol="fixture.blobs.v1")
        artifacts = BoundedArtifactReader(factory, blobs)
        freshness = RegisteredSourceFreshness(factory, policies)
        execution = ExecutionStore(
            factory,
            management_catalog=state.catalog,
            management_artifacts=artifacts,
            management_freshness=freshness,
        )
        effects = EffectStore(
            factory,
            management_catalog=state.catalog,
            management_artifacts=artifacts,
            management_freshness=freshness,
        )
        before = await execution.get(scope, identity(ACTOR))
        # Terminal failed is not reconcile_only; this is an actually available ordinary claim.
        lease = await execution.claim(scope, identity(ACTOR), uuid4(), ttl_seconds=60)
        assert state.spec.runtime_inputs is not None and state.spec.output_resource is not None
        current_config = public_config()
        excluded = {"recipe", "command_recipe_sha256"}
        if current_config.pins.model_dump(exclude=excluded) != state.spec.runtime_inputs.model_dump(
            exclude=excluded
        ):
            raise ValueError("Legacy public byte/platform pins differ from server configuration")
        config = replace(current_config, pins=state.spec.runtime_inputs)
        publisher = BuilderArtifactPublisher(
            factory, blobs, state.spec.output_resource, policies.policy("fixture.source.v1")
        )
        runner = RecoveryOnly(
            factory,
            execution,
            effects,
            state.policy,
            state.capabilities,
            IMAGE_ID,
            BuilderResultStore(ROOT / "results"),
            ROOT / "jobs",
            publisher,
            config,
        )
        guard = BuilderSourceGuard(
            state.spec,
            state.policy,
            lease,
            identity(ACTOR),
            RegisteredBuilderSource(REPOSITORY, state.metadata),
            artifacts,
            freshness,
            state.catalog,
        )
        result = await runner.reconcile(lease, identity(ACTOR), state.action, state.spec, guard)
        record = await effects.get(lease, identity(ACTOR), state.action.action_id)
        after = await execution.get(scope, identity(ACTOR))
        assert before.counters == after.counters and result is not None
        assert BuilderResultStore.digest(result) == expected_result_sha256
        observation = {
            "scope": "exact saved recipe current public M1/source/caller recovery; no new commands",
            "result_sha256": BuilderResultStore.digest(result),
            "effect": record.model_dump(mode="json"),
            "before": before.model_dump(mode="json"),
            "after": after.model_dump(mode="json"),
            "actual_claim": lease.model_dump(mode="json"),
            "new_processes": 0,
            "new_intents": 0,
        }
        await asyncio.to_thread(
            write_private,
            receipt_path,
            json.dumps(observation, indent=2).encode(),
        )
    finally:
        if lease is not None:
            await execution.release(lease, identity(ACTOR))
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(recover())

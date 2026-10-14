"""Actual public preparation and native jobs require separate Root-reviewed gates."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.builder.contracts import BuilderCapabilities
from nexus.builder.csv_behavior_wrapper import CASES
from nexus.builder.engineering_acceptance import EngineeringWorkAcceptanceStore
from nexus.builder.engineering_artifacts import EngineeringArtifactPublisher
from nexus.builder.engineering_contracts import EngineeringChangeDeclaration
from nexus.builder.engineering_inputs import RegisteredEngineeringInputs
from nexus.builder.engineering_node_runner import EngineeringNodeBuilderRunner
from nexus.builder.engineering_proof import EngineeringProofStorage
from nexus.builder.execution_contracts import BuilderExecutionSpec
from nexus.builder.node_config import NodeRuntimeConfig
from nexus.builder.node_recipe import command_policies
from nexus.builder.policy import BuilderToolPolicy
from nexus.builder.result_store import BuilderResultStore
from nexus.builder.source_guard import BuilderSourceGuard, RegisteredBuilderSource
from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.artifact_target_store import ArtifactTargetStore
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.company.management.plans import PlanPayload
from nexus.execution.effect_store import EffectStore
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_store import ExecutionStore
from nexus.tests.builder_node_support import IMAGE, IMAGE_ID
from nexus.tests.csv_native_audit import CsvObservedNodeRunner, verify_capture
from nexus.tests.csv_native_plan import (
    RESOURCE_SYMBOL,
    approve_action,
    create_plan,
    ledger_scope,
    native_action,
    native_spec,
)
from nexus.tests.csv_native_scope import NativeCsvConfig, require_assigned_database, require_root
from nexus.tests.csv_native_source import WRITE_PATHS, CsvNativeSource
from nexus.tests.engineering_fixture import EngineeringScenario
from nexus.tests.integration.management_acceptance_source_fixture import Policies, protected_text
from nexus.tests.integration.test_company_brain_ingestion import owner_scope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity


@dataclass(frozen=True)
class PreparedNativeCsv:
    config: NativeCsvConfig
    runner: EngineeringNodeBuilderRunner
    acceptance: EngineeringWorkAcceptanceStore
    artifacts: BoundedArtifactReader
    freshness: RegisteredSourceFreshness
    source: RegisteredBuilderSource


async def prepare_registered(
    factory: async_sessionmaker[AsyncSession],
    root: Path,
    source: CsvNativeSource,
    runtime: NodeRuntimeConfig,
    capabilities: BuilderCapabilities,
) -> PreparedNativeCsv:
    """Only after separate Root setup approval; all actual operative rows use public stores."""
    require_root(root, existing=True)
    await require_assigned_database(factory)
    output, proof = (ResourceRef(company_id=COMPANY, resource_id=uuid4()) for _ in range(2))
    catalog, payload = await _register_plan(factory, root, output, proof)
    metadata, patch = await _protected_sources(factory, root, source)
    policy = BuilderToolPolicy(
        company_id=COMPANY,
        policy_symbol="fixture.csv.native.v4",
        repository_symbol=source.pin.repository_symbol,
        resource_symbol=RESOURCE_SYMBOL,
        image=IMAGE,
        commands=command_policies(),
        write_paths=WRITE_PATHS,
        artifact_paths=("checks",),
        runtime_inputs=runtime.pins,
    )
    specs = tuple(
        native_spec(row.binding, policy, source.pin, patch, output) for row in payload.children
    )
    actions = tuple(native_action(spec) for spec in specs)
    for bound, action in zip((row.binding for row in payload.children), actions, strict=True):
        await approve_action(factory, bound, action)
    config = _registered_config(
        catalog,
        payload,
        policy,
        source,
        runtime,
        capabilities,
        metadata,
        output,
        proof,
        specs,
        actions,
    )
    path = root / "native-registered-config.json"
    with path.open("xb") as stream:
        stream.write(config.model_dump_json().encode())
    path.chmod(0o600)
    return await load_registered(factory, root)


async def load_registered(
    factory: async_sessionmaker[AsyncSession], root: Path
) -> PreparedNativeCsv:
    require_root(root, existing=True)
    await require_assigned_database(factory)
    path = root / "native-registered-config.json"
    assert path.is_file() and not path.is_symlink() and path.stat().st_size <= 65536
    assert path.stat().st_mode & 0o777 == 0o600
    config = NativeCsvConfig.model_validate_json(path.read_bytes())
    public = root / "public"
    runtime = NodeRuntimeConfig(
        config.runtime,
        public / "pnpm-9.12.0.tgz",
        public / "tools",
        public / "cache.tar",
        public / "cache/store",
        public / "manifest.json",
    )
    await runtime.revalidate()
    return _compose(factory, root, config, runtime)


def _policies() -> Policies:
    policies = Policies()
    # Reconstruct declared policies; actual READ remains store-backed.
    for number in (9500, 9900):
        base = policies.policy("fixture.source.v1")
        policies.values[f"acceptance.fixture.{number}"] = base.model_copy(
            update={
                "source_symbol": f"acceptance.fixture.{number}",
                "freshness_seconds": 3600,
                "allowed_external_keys": frozenset({f"source-{number}"}),
            }
        )
    return policies


def _compose(
    factory: async_sessionmaker[AsyncSession],
    root: Path,
    config: NativeCsvConfig,
    runtime: NodeRuntimeConfig,
) -> PreparedNativeCsv:
    blobs = ProtectedBlobStore(root, storage_symbol="fixture.blobs.v1")
    policies = _policies()
    artifacts, freshness = (
        BoundedArtifactReader(factory, blobs),
        RegisteredSourceFreshness(factory, policies),
    )
    execution = ExecutionStore(
        factory,
        management_catalog=config.catalog,
        management_artifacts=artifacts,
        management_freshness=freshness,
    )
    effects = EffectStore(
        factory,
        management_catalog=config.catalog,
        management_artifacts=artifacts,
        management_freshness=freshness,
    )
    jobs = root / "jobs"
    jobs.mkdir(mode=0o700, exist_ok=True)
    runner = _native_runner(factory, root, config, runtime, execution, effects, blobs, policies)
    inputs = RegisteredEngineeringInputs(
        factory, artifacts, runner.results, (config.declaration,), freshness
    )
    acceptance = EngineeringWorkAcceptanceStore(
        factory,
        config.catalog,
        inputs,
        EngineeringProofStorage(blobs, config.proof, policies.policy("fixture.source.v1")),
    )
    return PreparedNativeCsv(
        config,
        runner,
        acceptance,
        artifacts,
        freshness,
        RegisteredBuilderSource(root / "harmless-csv-repository", config.source_metadata),
    )


async def run_pair(item: PreparedNativeCsv) -> EngineeringScenario:
    """Only after separate exact launch packet approval; exactly two real native invocations."""
    results = []
    lease: ExecutionLease | None = None
    guard: BuilderSourceGuard | None = None
    try:
        for index, child in enumerate(item.config.payload.children):
            guard = None
            bound, action, spec = (
                child.binding,
                item.config.actions[index],
                item.config.specs[index],
            )
            lease = await item.runner.execution.claim(
                ledger_scope(bound), identity(bound.actor_id), uuid4(), ttl_seconds=60
            )
            guard = source_guard(item, index, lease)
            result = await item.runner.run(lease, identity(bound.actor_id), action, spec, guard)
            assert result is not None and result.outcome == "commands_succeeded"
            prepared = item.runner.jobs_root / f"{COMPANY.hex}-{action.action_id.hex}"
            verify_capture(result, prepared, item.config.runtime)
            lease = guard.lease
            results.append(result)
            if index == 0:
                await item.runner.execution.release(guard.lease, identity(bound.actor_id))
                lease = None
    except BaseException:
        if lease is not None:
            current = guard.lease if guard is not None else lease
            try:
                await item.runner.execution.release(current, identity(current.actor_id))
            except Exception as cleanup:
                with (item.runner.jobs_root.parent / "pair-lease-cleanup-failed.json").open(
                    "x"
                ) as stream:
                    json.dump(
                        {
                            "exception": type(cleanup).__name__,
                            "lease": current.model_dump(mode="json"),
                        },
                        stream,
                    )
        raise
    assert guard is not None
    return EngineeringScenario(
        item.acceptance,
        item.runner,
        results[0],
        results[1],
        guard.lease,
        item.config.catalog,
        item.config.actions[1],
        guard,
    )


def source_guard(item: PreparedNativeCsv, index: int, lease: ExecutionLease) -> BuilderSourceGuard:
    bound = item.config.payload.children[index].binding
    return BuilderSourceGuard(
        item.config.specs[index],
        item.runner.policy,
        lease,
        identity(bound.actor_id),
        item.source,
        item.artifacts,
        item.freshness,
        item.config.catalog,
    )


def _registered_config(
    catalog: PlanAdmissionCatalog,
    payload: PlanPayload,
    policy: BuilderToolPolicy,
    source: CsvNativeSource,
    runtime: NodeRuntimeConfig,
    capabilities: BuilderCapabilities,
    metadata: ArtifactRevisionRef,
    output: ResourceRef,
    proof: ResourceRef,
    specs: tuple[BuilderExecutionSpec, ...],
    actions: tuple[ActionProposal, ...],
) -> NativeCsvConfig:
    declaration = EngineeringChangeDeclaration(
        company_id=COMPANY,
        goal_id=payload.goal.goal_id,
        procedure_id=payload.procedure.procedure_id,
        policy=policy,
        image_id=IMAGE_ID,
        behavior_case_ids=tuple(row[0] for row in CASES),
        csv_regression=source.csv,
    )
    config = NativeCsvConfig(
        catalog=catalog,
        payload=payload,
        declaration=declaration,
        capabilities=capabilities,
        runtime=runtime.pins,
        source=source.pin,
        source_metadata=metadata,
        output=output,
        proof=proof,
        specs=specs,
        actions=actions,
    )
    return config


async def _register_plan(
    factory: async_sessionmaker[AsyncSession],
    root: Path,
    output: ResourceRef,
    proof: ResourceRef,
) -> tuple[PlanAdmissionCatalog, PlanPayload]:
    plans, payload = await create_plan(factory, root, output)
    proposed = await plans.propose(
        control(), identity(OWNER), payload, expected_current_revision_id=None
    )
    await plans.approve_and_register(
        control(),
        identity(OWNER),
        proposed.plan_revision_id,
        proposed.sha256,
        expected_current_revision_id=proposed.plan_revision_id,
    )
    await ArtifactTargetStore(factory).provision(
        owner_scope(),
        identity(OWNER),
        proof,
        readers=(OWNER, *[row.binding.actor_id for row in payload.children]),
    )
    return plans.catalog, payload


def _native_runner(
    factory: async_sessionmaker[AsyncSession],
    root: Path,
    config: NativeCsvConfig,
    runtime: NodeRuntimeConfig,
    execution: ExecutionStore,
    effects: EffectStore,
    blobs: ProtectedBlobStore,
    policies: Policies,
) -> EngineeringNodeBuilderRunner:
    jobs = root / "jobs"
    publisher = EngineeringArtifactPublisher(
        factory, blobs, config.output, policies.policy("fixture.source.v1"), jobs
    )
    runner = CsvObservedNodeRunner(
        factory,
        execution,
        effects,
        config.declaration.policy,
        config.capabilities,
        IMAGE_ID,
        BuilderResultStore(root / "results"),
        jobs,
        publisher,
        runtime,
    )
    return runner


async def _protected_sources(
    factory: async_sessionmaker[AsyncSession],
    root: Path,
    source: CsvNativeSource,
) -> tuple[ArtifactRevisionRef, ArtifactRevisionRef]:
    blobs, policies = ProtectedBlobStore(root, storage_symbol="fixture.blobs.v1"), Policies()
    metadata = await protected_text(
        factory,
        blobs,
        policies,
        json.dumps({"source": source.pin.model_dump(mode="json")}),
        9900,
        ttl=3600,
    )
    patch = await protected_text(factory, blobs, policies, source.patch.decode(), 9500, ttl=3600)
    return metadata, patch

"""Actual public M1/M3/Brain stores plus a task-owned cached-image builder fixture."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import AsyncIterator
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.builder.artifact_publisher import BuilderArtifactPublisher
from nexus.builder.contracts import (
    BuilderCapabilities,
    BuilderJobSpec,
    BuilderLimits,
    CommandRef,
    RepositoryPin,
)
from nexus.builder.execution_contracts import BuilderExecutionSpec
from nexus.builder.policy import BuilderCommandPolicy, BuilderToolPolicy
from nexus.builder.result_store import BuilderResultStore
from nexus.builder.runner import NativeBuilderRunner
from nexus.builder.source_guard import BuilderSourceGuard, RegisteredBuilderSource
from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.ingestion_store import BrainIngestionStore
from nexus.company.brain.source_registry import SourceRegistry
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.artifact_target_store import ArtifactTargetStore
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.control_store import ManagementControlStore
from nexus.company.management.governance import CharterRevisionRef
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plan_support import NamedPlanResource
from nexus.company.management.plans import PlanPayload, RunBinding
from nexus.execution.effect_store import EffectStore
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_store import ExecutionStore
from nexus.harness.canonical import action_hash
from nexus.harness.journal import CompanyJournal
from nexus.harness.standing_contracts import ToolPermission
from nexus.settings import settings
from nexus.tests.integration.management_acceptance_fixture import ledger
from nexus.tests.integration.management_acceptance_source_fixture import Policies, protected_text
from nexus.tests.integration.test_company_brain_ingestion import Reader, command, owner_scope
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER, control, migrate
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.management_control_support import charter
from nexus.tests.management_plan_support import VERIFIER, configured_plan

IMAGE = (
    "docker.io/library/debian@"
    "sha256:0d3279ff38fb2024358b2f24fbb99122f9a9a40618bb526b614527e998bcda28"
)
IMAGE_ID = "aa1d062ea725d2634ba0f40575b63f44fc8f58cf911ba318f23eaa18ece5369f"


@pytest.fixture
async def builder_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_builder"
    admin = create_async_engine(url)
    app = create_async_engine(url.set(username="nexus_company_app"))
    try:
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "upgrade")
        yield async_sessionmaker(app, expire_on_commit=False)
    finally:
        await app.dispose()
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "downgrade")
        await admin.dispose()


@dataclass(frozen=True)
class BuilderScenario:
    runner: NativeBuilderRunner
    spec: BuilderExecutionSpec
    action: ActionProposal
    lease: ExecutionLease
    guard: BuilderSourceGuard
    verifier_binding: RunBinding


def source_repository(root: Path) -> tuple[Path, RepositoryPin]:
    repository = root / "repository"
    repository.mkdir(mode=0o700)

    def git(*args: str) -> bytes:
        return subprocess.check_output(
            [
                "git",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "commit.gpgsign=false",
                "-C",
                str(repository),
                *args,
            ],
            stderr=subprocess.DEVNULL,
        )

    git("init", "-q")
    (repository / "answer.txt").write_text("actual committed fixture")
    git("add", "answer.txt")
    git(
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "fixture",
    )
    commit = git("rev-parse", "HEAD").decode().strip()
    tree = git("rev-parse", "HEAD^{tree}").decode().strip()
    raw = git("archive", "--format=tar", commit)
    return repository, RepositoryPin(
        repository_symbol="fixture",
        commit=commit,
        tree=tree,
        archive_sha256=hashlib.sha256(raw).hexdigest(),
    )


async def scenario(
    factory: async_sessionmaker[AsyncSession],
    root: Path,
    *,
    argv: tuple[str, ...] | None = None,
    patch_raw: bytes | None = None,
    output_in_descriptor: bool = True,
) -> BuilderScenario:
    from datetime import UTC, datetime

    from nexus.company.brain.artifact_store import BoundedArtifactReader
    from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness

    plans, payload = await configured_plan(factory, root)
    output = ResourceRef(company_id=COMPANY, resource_id=uuid4())
    await ArtifactTargetStore(factory).provision(
        owner_scope(), identity(OWNER), output, readers=(OWNER, ACTOR, VERIFIER)
    )
    catalog = plans.catalog.model_copy(
        update={
            "resources": (NamedPlanResource(symbol="company.report", resource=output),),
            "tools": (
                *plans.catalog.tools,
                ToolPermission(
                    tool="company.builder.run.v1", tool_version="v1", resource="company.report"
                ),
            ),
        }
    )
    revision = await ManagementControlStore(factory).publish_charter(
        control(),
        identity(OWNER),
        charter("builder-v2", verifier=VERIFIER).model_copy(
            update={"allowed_tools": tuple(row.tool for row in catalog.tools)}
        ),
        mandate=payload.mandate,
        expected_revision_id=payload.charters[0].revision_id,
    )
    cref = CharterRevisionRef.model_validate_json(
        revision.model_dump_json(include=set(CharterRevisionRef.model_fields))
    )
    payload = PlanPayload.model_validate_json(
        payload.model_copy(
            update={
                "charters": (cref,),
                "children": tuple(
                    child.model_copy(update={"charter": cref}) for child in payload.children
                ),
            }
        ).model_dump_json(by_alias=True)
    )
    plans = ManagementPlanStore(factory, catalog)
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
    repository, pin = source_repository(root)
    metadata = json.dumps({"source": pin.model_dump(mode="json")}).encode()
    policies = Policies()
    blobs = ProtectedBlobStore(root, storage_symbol="fixture.blobs.v1")
    ingestion = BrainIngestionStore(
        factory,
        SourceRegistry((policies.policy("fixture.source.v1"),), Reader({"r2": metadata})),
        blobs,
    )
    from nexus.company.brain.scope_support import brain_transaction
    from nexus.company.brain.source_models import BrainSourceHead
    from nexus.tests.integration.test_company_brain_ingestion import SOURCE

    async with brain_transaction(factory, owner_scope(), identity(OWNER)) as (session, _, _):
        head = await session.get(BrainSourceHead, (COMPANY, SOURCE))
        assert head is not None
        previous = head.current_revision_id
    ingested = await ingestion.ingest(
        owner_scope(), identity(OWNER), command(metadata, "r2", previous)
    )
    patch = (
        await protected_text(factory, blobs, policies, patch_raw.decode(), 9500)
        if patch_raw is not None
        else None
    )
    artifacts = BoundedArtifactReader(factory, blobs)
    freshness = RegisteredSourceFreshness(factory, policies)
    policy = BuilderToolPolicy(
        company_id=COMPANY,
        policy_symbol="fixture.builder.v1",
        resource_symbol="company.report",
        repository_symbol="fixture",
        image=IMAGE,
        commands=(
            BuilderCommandPolicy(
                command_key="check",
                argv=argv
                or (
                    "/bin/sh",
                    "-c",
                    'mkdir -p "$NEXUS_OUTPUT_DIR/checks"; '
                    'cat answer.txt >"$NEXUS_OUTPUT_DIR/checks/result.txt"',
                ),
                directory=".",
            ),
        ),
        write_paths=("answer.txt",),
        artifact_paths=("checks",),
    )
    child = payload.children[0].binding
    job = BuilderJobSpec(
        company_id=COMPANY,
        task_id=child.task_id,
        trace_id=child.trace_id,
        run_id=child.run_id,
        workspace_id=child.workspace_id,
        actor_id=ACTOR,
        action_id=uuid4(),
        policy_symbol=policy.policy_symbol,
        resource_symbol=policy.resource_symbol,
        architecture="amd64",
        source=pin,
        patch_sha256=patch.sha256 if patch else None,
        write_paths=("answer.txt",),
        artifact_paths=("checks",),
        commands=(
            CommandRef(command_key="check", phase="baseline"),
            CommandRef(command_key="check", phase="post"),
        ),
        limits=BuilderLimits(
            memory_bytes=67108864,
            workspace_bytes=4194304,
            output_bytes=1048576,
            log_bytes=16384,
            command_seconds=5,
            job_seconds=15,
            pids=32,
        ),
    )
    spec = BuilderExecutionSpec(
        job=job,
        policy_sha256=canonical_sha256(policy),
        output_resource=output if output_in_descriptor else None,
        protected_patch=patch,
    )
    action = ActionProposal(
        company_id=COMPANY,
        action_id=job.action_id,
        task_id=job.task_id,
        trace_id=job.trace_id,
        actor_id=ACTOR,
        revision=1,
        tool="company.builder.run.v1",
        tool_version="v1",
        resource="company.report",
        parameters=spec.model_dump(mode="json"),
        policy_version="fixture-policy",
        price_version="fixture-prices",
        estimated_cost_usd=Decimal("0.01"),
    )
    journal = CompanyJournal(factory)
    await journal.submit(action, ledger(child))
    await journal.approve_registered(
        ledger(child).model_copy(update={"principal_id": OWNER}),
        action.action_id,
        action_hash(action),
        datetime.now(UTC),
        identity=identity(OWNER),
    )
    await journal.authorize_registered(
        ledger(child), action.action_id, datetime.now(UTC), (), identity=identity(ACTOR)
    )
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
    lease = await execution.claim(ledger(child), identity(ACTOR), uuid4(), ttl_seconds=60)
    guard = BuilderSourceGuard(
        spec,
        policy,
        lease,
        identity(ACTOR),
        RegisteredBuilderSource(repository, ingested.artifact),
        artifacts,
        freshness,
        catalog,
    )
    jobs = root / "jobs"
    jobs.mkdir(mode=0o700)
    capabilities = BuilderCapabilities(
        architecture="amd64",
        rootless=True,
        cgroup_v2=True,
        controllers=frozenset({"cpu", "memory", "pids"}),
        hard_workspace_quota=True,
        network_none_verified=True,
        image_present=True,
        qualified_image=IMAGE,
    )
    runner = NativeBuilderRunner(
        factory,
        execution,
        effects,
        policy,
        capabilities,
        IMAGE_ID,
        BuilderResultStore(root / "results"),
        jobs,
        BuilderArtifactPublisher(factory, blobs, output, policies.policy("fixture.source.v1")),
    )
    return BuilderScenario(runner, spec, action, lease, guard, payload.children[1].binding)

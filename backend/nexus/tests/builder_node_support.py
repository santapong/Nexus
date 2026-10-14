"""Actual M1 Node fixtures use committed harmless source; empty CAS is synthetic test input."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tarfile
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.builder.contracts import BuilderLimits, RepositoryPin
from nexus.builder.execution_contracts import BuilderExecutionSpec
from nexus.builder.local_toolchain import PNPM_INTEGRITY
from nexus.builder.node_config import NodeRuntimeConfig
from nexus.builder.node_contracts import NodeRuntimeInputs
from nexus.builder.node_recipe import command_policies, command_references, recipe_sha256
from nexus.builder.node_runner import NodeNativeBuilderRunner
from nexus.builder.policy import BuilderToolPolicy
from nexus.builder.public_image import file_sha256
from nexus.builder.public_package_contracts import PublicPackage, PublicPackageManifest, package_url
from nexus.builder.source_guard import BuilderSourceGuard, RegisteredBuilderSource
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.canonical import canonical_sha256
from nexus.harness.canonical import action_hash
from nexus.harness.journal import CompanyJournal
from nexus.settings import settings
from nexus.tests.builder_runtime_support import BuilderScenario, scenario
from nexus.tests.integration.management_acceptance_source_fixture import Policies, protected_text
from nexus.tests.integration.test_company_directory import ACTOR, OWNER, migrate
from nexus.tests.integration.test_company_execution_store import identity

IMAGE = (
    "localhost/nexus-node-22.23.3-bookworm@"
    "sha256:c4d5523090a817b7aa86d2111241fdd4f66d1e27782b44160e6aa63b357ecb2d"
)
IMAGE_ID = "8f3dff4193637723b9f3f4ded64cccf28c7b35dc1c96d3320b1f5a64ff41e76d"
TOOL_ROOT = Path("/tmp/nexus-builder-stockflow-public-cache-20261014-v1/tools")
TOOL_ARCHIVE = Path("/tmp/nexus-builder-node-stage-20261014-v1/pnpm-9.12.0.tgz")
LOCK = (
    "lockfileVersion: '9.0'\nsettings:\n  autoInstallPeers: true\n"
    "  excludeLinksFromLockfile: false\nimporters:\n  .: {}\n"
)


@pytest.fixture
async def node_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_builder_node_hosts"
    admin, app = (
        create_async_engine(url),
        create_async_engine(url.set(username="nexus_company_app")),
    )
    try:
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "upgrade")
        yield async_sessionmaker(app, expire_on_commit=False)
    finally:
        await app.dispose()
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "downgrade")
        await admin.dispose()


def repository(root: Path, *, failed_baseline: bool) -> tuple[Path, RepositoryPin]:
    path = root / "node-repository"
    path.mkdir(mode=0o700)
    scripts = {
        "typecheck": "sh boundary.sh",
        "test": "node -e 'process.exit(0)'",
        "build": "node -e 'process.exit(0)'",
        "preinstall": "node -e 'process.exit(18)'",
        "pretypecheck": "node -e 'process.exit(19)'",
    }
    if failed_baseline:
        scripts["typecheck"] = "node -e 'process.exit(7)'"
    (path / "package.json").write_text(
        json.dumps({"name": "@stockflow/web", "private": True, "scripts": scripts})
    )
    (path / "pnpm-lock.yaml").write_text(LOCK)
    (path / "boundary.sh").write_text(boundary_script())
    (path / ".pnpmfile.cjs").write_text("throw new Error('unapproved implicit hook')\n")
    (path / ".npmrc").write_text("enable-pre-post-scripts=true\n")

    def git(*args: str) -> bytes:
        return subprocess.check_output(
            [
                "git",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "commit.gpgsign=false",
                "-C",
                str(path),
                *args,
            ],
            stderr=subprocess.DEVNULL,
        )

    git("init", "-q")
    git("add", ".")
    git(
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "harmless native Node fixture",
    )
    return path, RepositoryPin(
        repository_symbol="fixture",
        commit=git("rev-parse", "HEAD").decode().strip(),
        tree=git("rev-parse", "HEAD^{tree}").decode().strip(),
        archive_sha256=hashlib.sha256(git("archive", "--format=tar", "HEAD")).hexdigest(),
    )


def boundary_script() -> str:
    return (
        "set -eu\n"
        "node -e \"require('node:dns').lookup('localhost',{all:true},(e,a)=>{"
        "if(e||!a.length||a.some(x=>!['127.0.0.1','::1'].includes(x.address)))process.exit(23)})\"\n"
        "test \"$(awk '{print $2}' /etc/hosts | sort -u)\" = localhost\n"
        "if printf bad >/etc/hosts 2>/dev/null; then exit 22; fi\n"
        "cp /bin/true ./native-probe\n./native-probe\n"
        'for root in /tmp /outputs; do cp /bin/true "$root/noexec-probe"; '
        'if "$root/noexec-probe" 2>/dev/null; then exit 20; fi; done\n'
        "for root in /source/baseline /source/post /cache/store /tools /node-commands; do "
        'if touch "$root/forbidden-write" 2>/dev/null; then exit 21; fi; done\n'
        "test ! -e /var/run/docker.sock; test ! -e /home/santapong; test ! -e /host\n"
        "printf 'actual_scratch_exec_ro_inputs_noexec_neighbors_no_host_mounts\\n'\n"
        "printf 'actual_loopback_lookup_hosts_readonly_no_outside_aliases\\n'\n"
    )


def empty_config(root: Path) -> NodeRuntimeConfig:
    cache_archive = root / "synthetic-empty-cas.tar"
    with tarfile.open(cache_archive, "w", format=tarfile.GNU_FORMAT) as archive:
        for name in ("store", "store/v3", "store/v3/files"):
            row = tarfile.TarInfo(name)
            row.type, row.mode = tarfile.DIRTYPE, 0o700
            archive.addfile(row)
    cache = root / "synthetic-empty-cas"
    (cache / "store" / "v3" / "files").mkdir(mode=0o700, parents=True)
    manifest = root / "synthetic-manifest.json"
    # This schema fixture makes no package completeness claim; the project has no dependencies.
    manifest.write_text(
        PublicPackageManifest(
            lock_sha256=hashlib.sha256(LOCK.encode()).hexdigest(),
            packages=(
                PublicPackage(
                    name="pnpm",
                    version="9.12.0",
                    integrity=PNPM_INTEGRITY,
                    url=package_url("pnpm", "9.12.0"),
                ),
            ),
        ).model_dump_json()
    )
    pins = NodeRuntimeInputs(
        tool_symbol="pnpm.v9_12",
        cache_symbol="synthetic.empty.cas.v1",
        image_id=IMAGE_ID,
        node_version="22.23.3",
        pnpm_version="9.12.0",
        pnpm_archive_sha256=file_sha256(TOOL_ARCHIVE),
        pnpm_integrity=PNPM_INTEGRITY,
        cache_archive_sha256=file_sha256(cache_archive),
        cache_manifest_sha256=file_sha256(manifest),
        lock_sha256=hashlib.sha256(LOCK.encode()).hexdigest(),
        command_recipe_sha256=recipe_sha256(),
    )
    return NodeRuntimeConfig(
        pins, TOOL_ARCHIVE, TOOL_ROOT, cache_archive, cache / "store", manifest
    )


async def node_scenario(
    factory: async_sessionmaker[AsyncSession],
    root: Path,
    *,
    failed_baseline: bool = False,
    qualified: tuple[Path, RepositoryPin, NodeRuntimeConfig] | None = None,
    limits: BuilderLimits | None = None,
) -> BuilderScenario:
    original = await scenario(factory, root)
    if qualified is None:
        repo, pin = repository(root, failed_baseline=failed_baseline)
        config = empty_config(root)
    else:
        repo, pin, config = qualified
    policies, blobs = Policies(), ProtectedBlobStore(root, storage_symbol="fixture.blobs.v1")
    metadata = await protected_text(
        factory,
        blobs,
        policies,
        json.dumps({"source": pin.model_dump(mode="json")}),
        9900,
        ttl=3600 if qualified is not None else 300,
    )
    policy = BuilderToolPolicy(
        company_id=original.spec.job.company_id,
        policy_symbol="fixture.node.v1",
        repository_symbol=pin.repository_symbol,
        resource_symbol="company.report",
        image=IMAGE,
        commands=command_policies(),
        write_paths=("apps/web/src",) if qualified is not None else ("boundary.sh",),
        artifact_paths=("checks",),
        runtime_inputs=config.pins,
    )
    job = original.spec.job.model_copy(
        update={
            "action_id": uuid4(),
            "policy_symbol": policy.policy_symbol,
            "source": pin,
            "write_paths": policy.write_paths,
            "commands": command_references(),
            "limits": limits
            or BuilderLimits(
                memory_bytes=268435456,
                workspace_bytes=67108864,
                output_bytes=1048576,
                log_bytes=65536,
                command_seconds=5,
                job_seconds=30,
                pids=32,
            ),
        }
    )
    spec = BuilderExecutionSpec(
        job=job,
        policy_sha256=canonical_sha256(policy),
        output_resource=original.spec.output_resource,
        runtime_inputs=config.pins,
    )
    action = original.action.model_copy(
        update={
            "action_id": job.action_id,
            "parameters": spec.model_dump(mode="json"),
            "estimated_cost_usd": Decimal("0.01"),
        }
    )
    guard = BuilderSourceGuard(
        spec,
        policy,
        original.lease,
        identity(ACTOR),
        RegisteredBuilderSource(repo, metadata),
        original.guard.artifacts,
        RegisteredSourceFreshness(factory, policies),
        original.guard.catalog,
    )
    from nexus.tests.integration.management_acceptance_fixture import ledger

    ledger_scope = ledger(original.verifier_binding).model_copy(
        update={"task_id": job.task_id, "trace_id": job.trace_id, "principal_id": ACTOR}
    )
    journal = CompanyJournal(factory)
    await journal.submit(action, ledger_scope)
    await journal.approve_registered(
        ledger_scope.model_copy(update={"principal_id": OWNER}),
        action.action_id,
        action_hash(action),
        datetime.now(UTC),
        identity=identity(OWNER),
    )
    await journal.authorize_registered(
        ledger_scope, action.action_id, datetime.now(UTC), (), identity=identity(ACTOR)
    )
    assert original.runner.publisher is not None
    runner = NodeNativeBuilderRunner(
        factory,
        original.runner.execution,
        original.runner.effects,
        policy,
        original.runner.capabilities.model_copy(update={"qualified_image": IMAGE}),
        IMAGE_ID,
        original.runner.results,
        original.runner.jobs_root,
        original.runner.publisher,
        config,
    )
    return BuilderScenario(runner, spec, action, original.lease, guard, original.verifier_binding)

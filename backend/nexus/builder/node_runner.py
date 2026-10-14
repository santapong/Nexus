"""Native Node execution reuses the actual M1 one-permit/lease/recovery/publisher boundary."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid5

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.builder.artifact_publisher import BuilderArtifactPublisher
from nexus.builder.contained_compiler import described_contained_script
from nexus.builder.contained_invocation import invoke_contained
from nexus.builder.contained_plan import describe_contained_selectors
from nexus.builder.contained_services import ContainmentServices
from nexus.builder.contracts import BuilderCapabilities
from nexus.builder.execution_contracts import BuilderExecutionSpec, BuilderRunResult
from nexus.builder.node_capture import node_capture_result
from nexus.builder.node_config import NodeRuntimeConfig
from nexus.builder.node_phase_cleanup import cleanup_script
from nexus.builder.node_recipe import (
    config_text,
    loopback_hosts,
    node_script,
    require_node_recipe,
    wrappers,
)
from nexus.builder.node_runtime_plan import node_argv
from nexus.builder.policy import BuilderToolPolicy
from nexus.builder.process import bounded_call
from nexus.builder.public_image import file_sha256
from nexus.builder.result_store import BuilderResultStore
from nexus.builder.runner import NativeBuilderRunner
from nexus.builder.runner_capture import LeaseWatch
from nexus.builder.runtime_identity import RUNTIME_V2
from nexus.builder.runtime_plan import PreparedSources
from nexus.builder.source_guard import BuilderSourceGuard
from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.actions import ActionProposal
from nexus.execution.effect_store import EffectStore
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_store import ExecutionStore


class NodeNativeBuilderRunner(NativeBuilderRunner):
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        execution: ExecutionStore,
        effects: EffectStore,
        policy: BuilderToolPolicy,
        capabilities: BuilderCapabilities,
        image_id: str,
        results: BuilderResultStore,
        jobs_root: Path,
        publisher: BuilderArtifactPublisher,
        config: NodeRuntimeConfig,
        *,
        containment: ContainmentServices | None = None,
    ) -> None:
        super().__init__(
            factory,
            execution,
            effects,
            policy,
            capabilities,
            image_id,
            results,
            jobs_root,
            publisher,
            containment=containment,
        )
        if (
            policy.runtime_inputs != config.pins
            or image_id != config.pins.image_id
            or capabilities.architecture != config.pins.architecture
        ):
            raise ValueError("Native Node runtime qualification does not match fixed policy/image")
        self.config = config

    async def prepare(self, spec: BuilderExecutionSpec, guard: BuilderSourceGuard) -> Path:
        self.require_node_execution_recipe(spec)
        if spec.runtime_inputs != self.config.pins:
            raise ValueError("Native Node runtime pins changed before preparation")
        await self.config.revalidate()
        base = await super().prepare(spec, guard)
        for phase in ("baseline", "post"):
            if (
                await asyncio.to_thread(file_sha256, base / phase / "pnpm-lock.yaml")
                != self.config.pins.lock_sha256
            ):
                raise ValueError("Native Node committed/post lock differs from qualified cache")
        await asyncio.to_thread(self._prepare_commands, base, spec)
        return base

    def require_binding(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        spec: BuilderExecutionSpec,
        guard: BuilderSourceGuard,
    ) -> None:
        super().require_binding(lease, identity, spec, guard)
        if spec.job.architecture != self.config.pins.architecture:
            raise ValueError("Native Node job differs from qualified cache/tool platform")
        if spec.runtime_recipe == RUNTIME_V2:
            describe_contained_selectors(spec, self.policy)
        else:
            require_node_recipe(spec, self.policy, execution=False)

    def _prepare_commands(self, base: Path, spec: BuilderExecutionSpec) -> None:
        root = base / "node-commands"
        root.mkdir(mode=0o700)
        assets = wrappers()
        if (
            spec.runtime_inputs is not None
            and spec.runtime_inputs.recipe == "nexus.builder.node.v4"
        ):
            from nexus.builder.node_v4_assets import csv_wrapper_source
            from nexus.builder.node_v4_recipe import v4_wrappers

            assets = v4_wrappers()
            assert spec.runtime_inputs.csv_regression is not None
            (root / "csv-test-wrapper.cjs").write_text(csv_wrapper_source())
            (root / "csv-test-wrapper.cjs").chmod(0o600)
            (root / "csv-regression-pins.json").write_text(
                spec.runtime_inputs.csv_regression.model_dump_json()
            )
            (root / "csv-regression-pins.json").chmod(0o600)
        for key, value in assets.items():
            path = root / f"{key}.sh"
            path.write_text(value)
            path.chmod(0o600)
        (root / "offline.npmrc").write_text(config_text())
        cleanup = root / "phase-cleanup.py"
        cleanup.write_text(cleanup_script())
        cleanup.chmod(0o600)
        hosts = base / "loopback-hosts"
        hosts.write_text(loopback_hosts())
        hosts.chmod(0o600)
        (base / "entrypoint.sh").write_text(
            described_contained_script(spec, self.policy)
            if spec.runtime_recipe == RUNTIME_V2
            else node_script(spec, self.policy)
        )

    async def invoke(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        action: ActionProposal,
        spec: BuilderExecutionSpec,
        guard: BuilderSourceGuard,
        base: Path,
    ) -> BuilderRunResult:
        self.require_node_execution_recipe(spec)
        if spec.runtime_recipe == RUNTIME_V2:
            return await invoke_contained(
                self, lease, identity, action, spec, guard, base, node_config=self.config
            )
        argv = node_argv(
            spec,
            self.policy,
            self.capabilities,
            PreparedSources(base / "baseline", base / "post"),
            base,
            self.config,
        )
        name = "nexus-builder-" + uuid5(spec.job.company_id, str(spec.job.action_id)).hex
        watch = LeaseWatch(self.factory, self.execution, identity, action, guard)
        await watch.check()
        capture = await bounded_call(
            argv,
            name=name,
            action_id=str(action.action_id),
            company_id=str(action.company_id),
            seconds=spec.job.limits.job_seconds,
            stdout_limit=(spec.job.limits.output_bytes + 262144) * 2
            + spec.job.limits.log_bytes * 24,
            stderr_limit=spec.job.limits.log_bytes,
            watchdog=watch.check,
        )
        return node_capture_result(capture, spec, action, lease.fence, self.image_id, name)

    def require_node_execution_recipe(self, spec: BuilderExecutionSpec) -> None:
        """Retain existing recipes; contained execution supports only its complete fixed Nodev4."""
        if spec.runtime_recipe == RUNTIME_V2:
            self.require_execution_policy(spec)
            describe_contained_selectors(spec, self.policy)
        else:
            require_node_recipe(spec, self.policy, execution=True)

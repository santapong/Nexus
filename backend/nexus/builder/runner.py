"""One newly committed M1 permit surrounds one bounded native container invocation."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid5

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.builder.artifact_publisher import BuilderArtifactPublisher
from nexus.builder.contracts import BuilderCapabilities
from nexus.builder.execution_contracts import BuilderExecutionSpec, BuilderRunResult
from nexus.builder.native_state import (
    actual_action,
    current_source,
    require_record_result,
    result_disclosure,
)
from nexus.builder.patch_inventory import inventory, verify_snapshots
from nexus.builder.policy import BuilderToolPolicy, require_preparation
from nexus.builder.process import bounded_call, remove_known_owned
from nexus.builder.protected_patch import apply_patch, load_protected_patch, parse_patch
from nexus.builder.result_store import BuilderResultStore
from nexus.builder.runner_capture import LeaseWatch, capture_result
from nexus.builder.runtime_plan import PreparedSources, runtime_argv, runtime_script
from nexus.builder.snapshot import committed_archive, extract_source
from nexus.builder.source_guard import BuilderSourceGuard
from nexus.company.access import VerifiedIdentity
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.contracts.results import ActionReceipt
from nexus.execution.effect_store import EffectStore
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_store import ExecutionStore
from nexus.harness.canonical import action_hash


class NativeBuilderRunner:
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
        publisher: BuilderArtifactPublisher | None = None,
    ) -> None:
        self.factory, self.execution, self.effects, self.policy = (
            factory,
            execution,
            effects,
            policy,
        )
        self.capabilities, self.image_id, self.results, self.jobs_root = (
            capabilities,
            image_id,
            results,
            jobs_root,
        )
        self.publisher = publisher

    async def run(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        action: ActionProposal,
        spec: BuilderExecutionSpec,
        guard: BuilderSourceGuard,
    ) -> BuilderRunResult | None:
        spec = BuilderExecutionSpec.model_validate_json(spec.model_dump_json())
        self.require_binding(lease, identity, spec, guard)
        previous, _ = await actual_action(self.factory, lease, identity, action, spec)
        if previous is not None:
            return await self.reconcile(lease, identity, action, spec, guard)
        require_preparation(spec.job, self.policy, self.capabilities)
        await current_source(self.factory, lease, identity, action, guard, issued=False)
        with self.results.slot():
            base = await self.prepare(spec, guard)
            begin = await self.effects.begin(lease, identity, action.action_id, before_intent=guard)
            if not begin.permit_external_call:
                return await self.reconcile(lease, identity, action, spec, guard)
            result = await self.invoke(lease, identity, action, spec, guard, base)
            await self.results.save(result)
            if result.outcome != "outcome_unknown":
                protected = (
                    await self.publisher.publish(result, guard.lease, identity, guard)
                    if self.publisher
                    else None
                )
                await self.effects.record_receipt(
                    guard.lease, identity, self.receipt(result, protected), actual_usd=None
                )
                await remove_known_owned(
                    result.container_name, str(action.action_id), str(action.company_id)
                )
            disclosed = await result_disclosure(self.factory, guard.lease, identity, guard)
            return result if disclosed else None

    async def prepare(self, spec: BuilderExecutionSpec, guard: BuilderSourceGuard) -> Path:
        raw = await committed_archive(guard.source.repository, spec.job.source)
        patch = await load_protected_patch(guard)
        base = self.jobs_root / f"{spec.job.company_id.hex}-{spec.job.action_id.hex}"

        def write() -> None:
            base.mkdir(mode=0o700, parents=False, exist_ok=False)
            extract_source(raw, spec.job.source, base / "baseline")
            extract_source(raw, spec.job.source, base / "post")
            before = inventory(base / "baseline")
            if patch is not None:
                assert spec.job.patch_sha256 is not None
                apply_patch(
                    base / "post", parse_patch(patch, spec.job.patch_sha256, spec.job.write_paths)
                )
            verify_snapshots(base / "baseline", base / "post", before, spec.job.write_paths)
            entry = base / "entrypoint.sh"
            with entry.open("x") as stream:
                stream.write(runtime_script(spec, self.policy))
            entry.chmod(0o600)
            resolver = base / "resolv.conf"
            with resolver.open("x"):
                pass
            resolver.chmod(0o600)

        await asyncio.to_thread(write)
        return base

    async def invoke(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        action: ActionProposal,
        spec: BuilderExecutionSpec,
        guard: BuilderSourceGuard,
        base: Path,
    ) -> BuilderRunResult:
        argv = runtime_argv(
            spec,
            self.policy,
            self.capabilities,
            PreparedSources(base / "baseline", base / "post"),
            base / "entrypoint.sh",
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
        return capture_result(capture, spec, action, lease.fence, self.image_id, name)

    async def reconcile(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        action: ActionProposal,
        spec: BuilderExecutionSpec,
        guard: BuilderSourceGuard,
    ) -> BuilderRunResult | None:
        spec = BuilderExecutionSpec.model_validate_json(spec.model_dump_json())
        self.require_binding(lease, identity, spec, guard)
        await actual_action(self.factory, lease, identity, action, spec)
        record = await self.effects.get(lease, identity, action.action_id)
        require_record_result(record, action_hash(action), lease.run_id)
        result = await self.results.load(spec)
        if result is None or result.outcome == "outcome_unknown":
            return (
                result
                if result is None or await result_disclosure(self.factory, lease, identity, guard)
                else None
            )
        if (
            result.proposal_sha256 != record.proposal_hash
            or result.intent_fence != record.intent_fence
        ):
            raise ValueError("Saved builder result differs from native issuance")
        protected = self.publisher.reference(result) if self.publisher else None
        if self.publisher and record.receipt is None:
            protected = await self.publisher.publish(result, lease, identity, guard)
        receipt = self.receipt(result, protected)
        if record.receipt is not None:
            if record.receipt != receipt:
                raise ValueError("Native receipt differs from saved builder result")
        elif record.state == "outcome_unknown" and lease.mode == "reconcile":
            await self.effects.reconcile(lease, identity, receipt, actual_usd=None)
        elif record.state == "intent" and lease.fence == record.intent_fence:
            await self.effects.record_receipt(lease, identity, receipt, actual_usd=None)
        return result if await result_disclosure(self.factory, lease, identity, guard) else None

    def require_binding(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        spec: BuilderExecutionSpec,
        guard: BuilderSourceGuard,
    ) -> None:
        if (
            guard.spec != spec
            or guard.policy != self.policy
            or guard.identity != identity
            or (
                guard.lease.model_dump(exclude={"expires_at"})
                != lease.model_dump(exclude={"expires_at"})
            )
        ):
            raise ValueError("Builder source guard binds another native execution")
        spec.require_policy(self.policy)
        if self.publisher is not None and spec.output_resource != self.publisher.target:
            raise ValueError(
                "Configured builder publishing needs its exact output target before intent"
            )

    def receipt(
        self, result: BuilderRunResult, protected: ArtifactRevisionRef | None = None
    ) -> ActionReceipt:
        if result.outcome == "outcome_unknown":
            raise ValueError("Unknown builder outcome has no terminal receipt")
        job = result.spec.job
        return ActionReceipt(
            company_id=job.company_id,
            receipt_id=uuid5(job.action_id, "native-builder-receipt-v1"),
            action_id=job.action_id,
            task_id=job.task_id,
            trace_id=job.trace_id,
            proposal_hash=result.proposal_sha256,
            outcome="succeeded" if result.outcome == "commands_succeeded" else "failed",
            recorded_at=result.recorded_at,
            artifacts=(
                ArtifactRef(
                    company_id=job.company_id,
                    artifact_id=protected.artifact_id
                    if protected
                    else uuid5(job.action_id, "native-builder-result-v1"),
                    reference=f"native-builder:{job.action_id}",
                    sha256=protected.sha256 if protected else self.results.digest(result),
                    revision=protected.revision if protected else "v1",
                ),
            ),
        )

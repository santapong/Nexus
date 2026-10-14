"""Engineering preserves native permits and restores witness pins before known-output replay."""

from __future__ import annotations

import asyncio
from pathlib import Path

from nexus.builder.engineering_artifacts import EngineeringArtifactPublisher
from nexus.builder.engineering_cleanup import cleanup_known_engineering_container
from nexus.builder.engineering_witness import capture_witness
from nexus.builder.execution_contracts import BuilderExecutionSpec, BuilderRunResult
from nexus.builder.native_state import actual_action, require_record_result
from nexus.builder.runner import NativeBuilderRunner
from nexus.builder.source_guard import BuilderSourceGuard
from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.actions import ActionProposal
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.harness.canonical import action_hash


class EngineeringNativeBuilderRunner(NativeBuilderRunner):
    async def prepare(self, spec: BuilderExecutionSpec, guard: BuilderSourceGuard) -> Path:
        base = await super().prepare(spec, guard)
        await asyncio.to_thread(capture_witness, base, spec)
        return base

    async def reconcile(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        action: ActionProposal,
        spec: BuilderExecutionSpec,
        guard: BuilderSourceGuard,
    ) -> BuilderRunResult | None:
        """License the native identity before restoring a durable witness into transient cache."""
        spec = BuilderExecutionSpec.model_validate_json(spec.model_dump_json())
        self.require_binding(lease, identity, spec, guard)
        await actual_action(self.factory, lease, identity, action, spec)
        record = await self.effects.get(lease, identity, action.action_id)
        require_record_result(record, action_hash(action), lease.run_id)
        result = await self.results.load(spec)
        publisher = self.publisher
        if not isinstance(publisher, EngineeringArtifactPublisher):
            raise ValueError("Engineering recovery needs its exact configured publisher")
        if result is not None and result.outcome != "outcome_unknown":
            if (result.proposal_sha256, result.intent_fence) != (
                record.proposal_hash,
                record.intent_fence,
            ):
                raise ValueError("Saved engineering result differs from native issuance")
            await publisher.prepare_witness(result)
        try:
            disclosed = await super().reconcile(lease, identity, action, spec, guard)
            if result is not None and result.outcome != "outcome_unknown":
                await cleanup_known_engineering_container(
                    self.factory,
                    lease,
                    identity,
                    action,
                    spec,
                    result,
                    self.receipt(result, publisher.reference(result)),
                )
            return disclosed
        finally:
            publisher.witnesses.pop(action.action_id, None)

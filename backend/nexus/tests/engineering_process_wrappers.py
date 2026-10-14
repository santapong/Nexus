"""Trusted process-only barrier wrappers delegate original storage and effect boundaries."""

from pathlib import Path
from typing import Any

from nexus.builder.engineering_runner import EngineeringNativeBuilderRunner
from nexus.builder.execution_contracts import BuilderExecutionSpec, BuilderRunResult
from nexus.builder.result_store import BuilderResultStore
from nexus.builder.source_guard import BuilderSourceGuard
from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.results import ActionReceipt
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.effect_store import EffectStore
from nexus.execution.engineering_worker_services import EngineeringWorkerHook
from nexus.execution.runtime_contracts import EffectRecord, ExecutionLease


class ObservedResults(BuilderResultStore):
    def __init__(self, root: Path, hook: EngineeringWorkerHook, command: SegmentCommand) -> None:
        super().__init__(root)
        self.hook, self.command = hook, command

    async def save(self, result: BuilderRunResult) -> None:
        await super().save(result)
        await self.hook("result_stored", self.command)


class ObservedEffects(EffectStore):
    def __init__(
        self, *args: Any, hook: EngineeringWorkerHook, command: SegmentCommand, **kwargs: Any
    ) -> None:
        # Test-only delegation preserves the public constructor's current keyword composition.
        super().__init__(*args, **kwargs)
        self.hook, self.command = hook, command

    async def record_receipt(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        receipt: ActionReceipt,
        **kwargs: Any,
    ) -> EffectRecord:
        result = await super().record_receipt(lease, identity, receipt, **kwargs)
        await self.hook("receipt_recorded", self.command)
        return result


class ObservedEngineeringRunner(EngineeringNativeBuilderRunner):
    def __init__(
        self, *args: Any, hook: EngineeringWorkerHook, command: SegmentCommand, **kwargs: Any
    ) -> None:
        # Only test instrumentation is added; all one-time permit/storage logic stays inherited.
        super().__init__(*args, **kwargs)
        self.hook, self.command = hook, command

    async def invoke(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        action: ActionProposal,
        spec: BuilderExecutionSpec,
        guard: BuilderSourceGuard,
        base: Path,
    ) -> BuilderRunResult:
        await self.hook("intent_committed", self.command)
        with (base.parent / "invocations.jsonl").open("a") as stream:
            stream.write(action.action_id.hex + "\n")
        return await super().invoke(lease, identity, action, spec, guard, base)

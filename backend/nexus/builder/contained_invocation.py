"""One permitted contained call becomes an original-fence result only with actual host evidence."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid5

from nexus.builder.contained_compiler import described_contained_argv
from nexus.builder.contained_diagnostic_wiring import persist_final, persist_raw
from nexus.builder.contained_diagnostics import (
    DiagnosticIdentity,
    FinalizationDiagnostic,
    error_kind,
)
from nexus.builder.contained_observer import ContainmentObserver
from nexus.builder.contained_observer_io import OwnedObservationIO
from nexus.builder.contained_process import ProcessOwnershipUnresolvedError
from nexus.builder.contained_process_contracts import (
    ContainedRunCapture,
    PreparedContainedLaunch,
    ProcessRunBinding,
    sample_trace,
)
from nexus.builder.contained_query import clock_us
from nexus.builder.contained_results import result_evidence_identity
from nexus.builder.contained_services import ContainmentServices
from nexus.builder.contained_watch import ContainedSourceWatch
from nexus.builder.execution_contracts import BuilderExecutionSpec, BuilderRunResult
from nexus.builder.node_capture import node_capture_result
from nexus.builder.node_config import NodeRuntimeConfig
from nexus.builder.runner_capture import LeaseWatch, capture_result
from nexus.builder.runtime_identity import RUNTIME_V1
from nexus.builder.runtime_plan import PreparedSources
from nexus.builder.source_guard import BuilderSourceGuard
from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.canonical import canonical_sha256
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.harness.canonical import action_hash

if TYPE_CHECKING:
    from nexus.builder.runner import NativeBuilderRunner


async def invoke_contained(
    runner: NativeBuilderRunner,
    lease: ExecutionLease,
    identity: VerifiedIdentity,
    action: ActionProposal,
    spec: BuilderExecutionSpec,
    guard: BuilderSourceGuard,
    base: Path,
    *,
    node_config: NodeRuntimeConfig | None = None,
) -> BuilderRunResult:
    """The native runner owns issuance; this private adapter never creates another permit."""
    services = runner.containment
    if services is None or services.deadline is None:
        raise ValueError("Contained fresh execution services are unavailable")
    services.require_policy(spec, runner.policy)
    launch = _launch(runner, spec, action, lease, base, services, node_config)
    binding, limits = launch.binding, spec.job.limits
    watch = ContainedSourceWatch(
        LeaseWatch(runner.factory, runner.execution, identity, action, guard),
        operation_end_us=services.deadline.end_us,
    )
    try:
        raw = await services.process.run(
            launch,
            binding,
            services.expectation,
            watch,
            services.deadline,
            stdout_limit=(limits.output_bytes + 262144) * 2 + limits.log_bytes * 24,
            stderr_limit=limits.log_bytes,
        )
    except ProcessOwnershipUnresolvedError as failure:
        services.retain_unresolved(failure)
        raise
    expected = DiagnosticIdentity.model_validate(
        {key: getattr(binding, key) for key in DiagnosticIdentity.model_fields}
    )
    await persist_raw(raw, expected, services)
    return await _finish(runner, spec, action, lease, raw, services, node_config)


def _launch(
    runner: NativeBuilderRunner,
    spec: BuilderExecutionSpec,
    action: ActionProposal,
    lease: ExecutionLease,
    base: Path,
    services: ContainmentServices,
    node_config: NodeRuntimeConfig | None,
) -> PreparedContainedLaunch:
    binding = ProcessRunBinding(
        company_id=spec.job.company_id,
        action_id=spec.job.action_id,
        task_id=spec.job.task_id,
        trace_id=spec.job.trace_id,
        run_id=spec.job.run_id,
        original_intent_fence=lease.fence,
        image_id=runner.image_id,
        spec_sha256=canonical_sha256(spec),
        proposal_sha256=action_hash(action),
        execution_method_sha256=services.method_sha256,
        container_name="nexus-builder-" + uuid5(spec.job.company_id, str(spec.job.action_id)).hex,
    )
    argv = described_contained_argv(
        spec,
        runner.policy,
        runner.capabilities,
        PreparedSources(base / "baseline", base / "post"),
        base / "entrypoint.sh",
        node_config=node_config,
    )
    limits = spec.job.limits
    return PreparedContainedLaunch(
        binding=binding,
        argv=argv,
        argv_sha256=hashlib.sha256(json.dumps(argv, separators=(",", ":")).encode()).hexdigest(),
        memory_bytes=limits.memory_bytes,
        cpu_quota_us=limits.cpu_millis * 100,
        cpu_period_us=100_000,
        pids=limits.pids,
    )


async def _finish(
    runner: NativeBuilderRunner,
    spec: BuilderExecutionSpec,
    action: ActionProposal,
    lease: ExecutionLease,
    raw: ContainedRunCapture,
    services: ContainmentServices,
    node_config: NodeRuntimeConfig | None,
) -> BuilderRunResult:
    # This >50-line conversion binds raw output, historical host samples and
    # original-fence sidecar bytes before constructing a valid terminal result.
    assert services.deadline is not None
    # Pydantic strict dataclass fields require the original typed ProcessCapture;
    # reconstruct every model field while retaining that native producer value.
    raw = ContainedRunCapture.model_validate(raw.model_dump() | {"capture": raw.capture})
    name = "nexus-builder-" + uuid5(spec.job.company_id, str(spec.job.action_id)).hex
    # Decode only command/output mechanics in an internal view; restore the actual
    # spec before any immutable result hash, sidecar or native publication exists.
    view = spec.model_copy(update={"runtime_recipe": RUNTIME_V1})
    decoder = node_capture_result if node_config else capture_result
    decoded = decoder(raw.capture, view, action, lease.fence, runner.image_id, name)
    result = decoded.model_copy(update={"spec": spec, "contained_runtime": raw.runtime})
    if raw.infrastructure != "known" or raw.sealed_container is None or not raw.samples:
        assert raw.diagnostic is not None
        await persist_final(
            FinalizationDiagnostic(
                identity=raw.diagnostic.identity,
                status="unproven",
                diagnostics=("no_samples",)
                if not raw.samples
                else tuple(dict.fromkeys(d for row in raw.samples for d in row.diagnostics)),
                sample_count=len(raw.samples),
                sample_chain_sha256=sample_trace(raw.samples).chain_sha256,
                error_type=raw.diagnostic.error_type,
                errno=raw.diagnostic.errno,
            ),
            services,
        )
        return BuilderRunResult.model_validate(
            result.model_copy(
                update={
                    "outcome": "outcome_unknown",
                    "limitations": (*result.limitations, "host_containment_unproven"),
                }
            ).model_dump()
        )
    assert raw.diagnostic is not None
    try:
        observation = await ContainmentObserver(OwnedObservationIO()).finish(
            raw.samples,
            result_evidence_identity(result, services.method_sha256),
            spec_sha256=canonical_sha256(spec),
            proposal_sha256=action_hash(action),
            selector_sha256=runner.policy.runtime_method_sha256 or "",
            deadline=services.deadline,
        )
    except (OSError, ValueError, TimeoutError) as failure:
        await persist_final(
            FinalizationDiagnostic(
                identity=raw.diagnostic.identity,
                status="unproven",
                diagnostics=("io_unavailable",),
                sample_count=len(raw.samples),
                sample_chain_sha256=sample_trace(raw.samples).chain_sha256,
                error_type=error_kind(failure),
                errno=failure.errno if isinstance(failure, OSError) else None,
            ),
            services,
        )
        raise
    await persist_final(
        FinalizationDiagnostic(
            identity=raw.diagnostic.identity,
            status=observation.status,
            diagnostics=observation.diagnostics,
            sample_count=observation.sample_count,
            sample_chain_sha256=observation.sample_chain_sha256,
        ),
        services,
    )
    if observation.status != "observed_contained":
        return BuilderRunResult.model_validate(
            result.model_copy(
                update={
                    "outcome": "outcome_unknown",
                    "limitations": (*result.limitations, "host_containment_unproven"),
                }
            ).model_dump()
        )
    remaining = (services.deadline.end_us - clock_us()) / 1_000_000
    if remaining <= 0:
        raise ValueError("Contained evidence publication crossed the original job end")
    async with asyncio.timeout(remaining):
        reference = await services.store.save_once(observation)
    if clock_us() >= services.deadline.end_us:
        raise ValueError("Contained sidecar write crossed the original job end")
    final = BuilderRunResult.model_validate(
        result.model_copy(update={"containment": reference}).model_dump()
    )
    if clock_us() >= services.deadline.end_us:
        raise ValueError("Contained result validation crossed the original job end")
    return final

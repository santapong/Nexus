"""Metadata producers preserve actual raw capture and sample chain; they grant no authority."""

from __future__ import annotations

import hashlib
from collections import Counter
from typing import TYPE_CHECKING

from nexus.builder.contained_diagnostics import (
    Count,
    DiagnosticIdentity,
    OutputDigest,
    ProcessDiagnostic,
    RuntimeDiagnostic,
    SampleSummary,
    SampleTrace,
    interruption_kind,
)
from nexus.builder.contained_evidence_types import ObservedSample

if TYPE_CHECKING:
    from nexus.builder.contained_process_contracts import (
        ContainedRunCapture,
        ProcessRunBinding,
        ProcessSampling,
    )


def process_diagnostic(
    binding: ProcessRunBinding, raw: ContainedRunCapture, state: ProcessSampling
) -> ProcessDiagnostic:
    """No sandbox output body is copied into the diagnostic metadata contract."""
    identity = DiagnosticIdentity(
        company_id=binding.company_id,
        action_id=binding.action_id,
        task_id=binding.task_id,
        trace_id=binding.trace_id,
        run_id=binding.run_id,
        original_intent_fence=binding.original_intent_fence,
        spec_sha256=binding.spec_sha256,
        proposal_sha256=binding.proposal_sha256,
        execution_method_sha256=binding.execution_method_sha256,
    )
    return ProcessDiagnostic(
        identity=identity,
        parent_sha256=hashlib.sha256(raw.parent.model_dump_json().encode()).hexdigest(),
        deadline_end_us=raw.deadline.end_us,
        infrastructure=raw.infrastructure,
        runtime=RuntimeDiagnostic.model_validate(raw.runtime.model_dump()),
        sealed_container=raw.sealed_container,
        stdout=OutputDigest(
            observed_bytes=len(raw.capture.stdout),
            observed_sha256=hashlib.sha256(raw.capture.stdout).hexdigest(),
        ),
        stderr=OutputDigest(
            observed_bytes=len(raw.capture.stderr),
            observed_sha256=hashlib.sha256(raw.capture.stderr).hexdigest(),
        ),
        exit_code=raw.capture.exit_code,
        interruption=interruption_kind(raw.capture.interruption),
        phase=state.phase,
        error_type=state.error_type,
        errno=state.errno,
        discovery=state.discovery.snapshot(),
        samples=sample_trace(raw.samples),
        parent_attempt=raw.parent_attempt,
        issued_identity=raw.issued_identity,
        issued_cleanup=raw.issued_cleanup,
    )


def sample_trace(samples: tuple[ObservedSample, ...]) -> SampleTrace:
    status = Counter(row.status for row in samples)
    diagnostics = Counter(key for row in samples for key in row.diagnostics)
    chain = b""
    for row in samples:
        chain = hashlib.sha256(chain + row.model_dump_json().encode()).digest()
    return SampleTrace(
        total=len(samples),
        status_counts=tuple(Count(key=key, count=count) for key, count in sorted(status.items())),
        diagnostic_counts=tuple(
            Count(key=key, count=count) for key, count in sorted(diagnostics.items())
        ),
        chain_sha256=chain.hex() if samples else hashlib.sha256(b"").hexdigest(),
        first=_sample_summary(samples[0]) if samples else None,
        last=_sample_summary(samples[-1]) if samples else None,
        omitted=max(0, len(samples) - 2),
    )


def _sample_summary(row: ObservedSample) -> SampleSummary:
    return SampleSummary(
        started_us=row.started_us,
        finished_us=row.finished_us,
        status=row.status,
        diagnostics=row.diagnostics,
        sample_sha256=hashlib.sha256(row.model_dump_json().encode()).hexdigest(),
        process_count=len(row.processes),
        retired_count=len(row.retired_processes),
        tree_complete=row.tree_complete,
        subtree_count=row.subtree_count,
        memory_bytes=row.memory_bytes,
        cpu_quota_us=row.cpu_quota_us,
        cpu_period_us=row.cpu_period_us,
        pids=row.pids,
    )

"""Actual private diagnostic persistence preserves the original job end and confers no authority."""

from __future__ import annotations

import asyncio
import hashlib
from typing import TYPE_CHECKING

from nexus.builder.contained_diagnostics import (
    ContainmentDiagnosticStore,
    DiagnosticIdentity,
    DiagnosticRef,
    FinalizationDiagnostic,
    OutputDigest,
    ProcessDiagnostic,
    interruption_kind,
)
from nexus.builder.contained_process_contracts import ContainedRunCapture, sample_trace
from nexus.builder.contained_query import clock_us

if TYPE_CHECKING:
    from nexus.builder.contained_services import ContainmentServices


def _remaining(services: ContainmentServices) -> float:
    if services.deadline is None:
        raise ValueError("Contained diagnostic original end is unavailable")
    remaining = services.deadline.end_us - clock_us()
    if remaining <= 0:
        raise ValueError("Contained diagnostic original job end expired")
    return remaining / 1_000_000


def _digest(raw: bytes) -> OutputDigest:
    return OutputDigest(observed_bytes=len(raw), observed_sha256=hashlib.sha256(raw).hexdigest())


async def persist_raw(
    raw: ContainedRunCapture,
    expected: DiagnosticIdentity,
    services: ContainmentServices,
) -> DiagnosticRef:
    """A supplied metadata object cannot replace comparison against the actual capture."""
    value = raw.diagnostic
    if value is None:
        raise ValueError("Contained raw diagnostic is unavailable")
    record = ProcessDiagnostic.model_validate(value.model_dump())
    if (
        record.identity != expected
        or services.deadline is None
        or raw.deadline != services.deadline
        or record.deadline_end_us != raw.deadline.end_us
        or record.parent_sha256 != hashlib.sha256(raw.parent.model_dump_json().encode()).hexdigest()
        or record.runtime.model_dump() != raw.runtime.model_dump()
        or record.infrastructure != raw.infrastructure
        or record.sealed_container != raw.sealed_container
        or record.stdout != _digest(raw.capture.stdout)
        or record.stderr != _digest(raw.capture.stderr)
        or record.exit_code != raw.capture.exit_code
        or record.interruption != interruption_kind(raw.capture.interruption)
        or record.samples != sample_trace(raw.samples)
    ):
        raise ValueError("Contained raw diagnostic differs from original issued capture")
    return await _persist(record, services)


async def persist_final(
    record: FinalizationDiagnostic,
    services: ContainmentServices,
) -> DiagnosticRef:
    return await _persist(FinalizationDiagnostic.model_validate(record.model_dump()), services)


async def _persist(
    record: ProcessDiagnostic | FinalizationDiagnostic,
    services: ContainmentServices,
) -> DiagnosticRef:
    if type(services.diagnostics) is not ContainmentDiagnosticStore:
        raise ValueError("Contained diagnostic concrete store differs")
    async with asyncio.timeout(_remaining(services)):
        reference = await services.diagnostics.save_once(record)
    if _remaining(services) <= 0:
        raise ValueError("Contained diagnostic write crossed original job end")
    return reference

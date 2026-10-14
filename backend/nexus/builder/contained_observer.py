"""One bounded actual sample cannot replace an incomplete/raced inventory with claimed success."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from itertools import pairwise
from typing import Protocol

from nexus.builder.contained_contracts import ContainedEvidenceIdentity, ParentObservation
from nexus.builder.contained_evidence_types import (
    ContainedObservation,
    Diagnostic,
    ExactContainer,
    ObservationDeadline,
    ObservedSample,
    ProcessIdentity,
    parent_identity,
    process_key,
)
from nexus.builder.contained_query import clock_us


class ObservationIO(Protocol):
    """Trusted fixed host reader; no sandbox-provided success flag or authority callback."""

    async def observe(
        self,
        parent: ParentObservation,
        container: ExactContainer,
        deadline: ObservationDeadline,
        previous: tuple[ProcessIdentity, ...],
    ) -> ObservedSample:
        """Return actual complete current host facts or explicit uncertainty."""
        ...


class ContainmentObserver:
    """Samples/finalization retain one absolute end, with no budget replenishment."""

    def __init__(self, io: ObservationIO, *, clock_us: Callable[[], int] = clock_us) -> None:
        self.io, self._clock = io, clock_us
        self._previous: tuple[ProcessIdentity, ...] = ()
        self._deadline: int | None = None

    async def sample(
        self,
        parent: ParentObservation,
        container: ExactContainer,
        deadline: ObservationDeadline,
    ) -> ObservedSample:
        """Any IO race/overflow/timeout remains unproven rather than shortened success."""
        start = self._clock()
        if self._deadline is not None and self._deadline != deadline.end_us:
            raise ValueError("Observer series cannot replenish its absolute deadline")
        self._deadline = deadline.end_us
        remaining = deadline.remaining_us(start, parent)
        if remaining == 0:
            return self._uncertain(parent, container, deadline, start, start, "deadline")
        try:
            async with asyncio.timeout(remaining / 1_000_000):
                value = await self.io.observe(parent, container, deadline, self._previous)
            final = self._clock()
            if deadline.remaining_us(final, parent) == 0:
                return self._uncertain(parent, container, deadline, start, final, "deadline")
            value = ObservedSample.model_validate(value.model_dump())
            if (
                value.parent != parent
                or value.container != container
                or value.deadline_end_us != deadline.end_us
            ):
                return self._uncertain(
                    parent, container, deadline, start, final, "identity_mismatch"
                )
            self._previous = tuple(
                {process_key(row): row for row in (*self._previous, *value.processes)}.values()
            )
            if len(self._previous) > 256:
                self._previous = self._previous[:256]
                return self._uncertain(parent, container, deadline, start, final, "overflow")
            final = self._clock()
            if deadline.remaining_us(final, parent) == 0:
                return self._uncertain(parent, container, deadline, start, final, "deadline")
            return value
        except (ValueError, OSError, TimeoutError):
            return self._uncertain(
                parent, container, deadline, start, self._clock(), "io_unavailable"
            )

    async def finish(
        self,
        samples: tuple[ObservedSample, ...],
        identity: ContainedEvidenceIdentity,
        *,
        spec_sha256: str,
        proposal_sha256: str,
        selector_sha256: str,
        deadline: ObservationDeadline,
    ) -> ContainedObservation:
        """Bind actual samples to original result identity; no ignored failing samples."""
        samples = _sequence(samples, deadline)
        last = samples[-1]
        captured, retired, diagnostics = _aggregate(samples)
        good = all(row.status == "observed_contained" for row in samples) and not diagnostics
        chain = b""
        for row in samples:
            chain = hashlib.sha256(chain + row.model_dump_json().encode()).digest()
        good = good and deadline.remaining_us(self._clock(), last.parent) > 0
        if not good and not diagnostics:
            diagnostics = ("deadline",)
        result = _assemble(
            samples,
            identity,
            (spec_sha256, proposal_sha256, selector_sha256),
            captured,
            retired,
            diagnostics,
            good,
            chain.hex(),
        )
        if (
            result.status == "observed_contained"
            and deadline.remaining_us(self._clock(), last.parent) == 0
        ):
            return ContainedObservation.model_validate(
                result.model_dump()
                | {
                    "status": "unproven",
                    "diagnostics": ("deadline",),
                }
            )
        return result

    @staticmethod
    def _uncertain(
        parent: ParentObservation,
        container: ExactContainer,
        deadline: ObservationDeadline,
        start: int,
        end: int,
        diagnostic: str,
    ) -> ObservedSample:
        return ObservedSample.model_validate(
            {
                "parent": parent,
                "container": container,
                "started_us": start,
                "finished_us": end,
                "deadline_end_us": deadline.end_us,
                "status": "unproven",
                "diagnostics": (diagnostic,),
            }
        )


def _aggregate(
    samples: tuple[ObservedSample, ...],
) -> tuple[
    tuple[ProcessIdentity, ...],
    tuple[ProcessIdentity, ...],
    tuple[Diagnostic, ...],
]:
    captured: dict[tuple[object, int, int], ProcessIdentity] = {}
    retired: dict[tuple[object, int, int], ProcessIdentity] = {}
    diagnostics = list(dict.fromkeys(d for sample in samples for d in sample.diagnostics))
    seen: dict[tuple[object, int], int] = {}
    for sample in samples:
        for row in sample.processes:
            key = process_key(row)
            reuse = (row.boot_id, row.pid)
            if reuse in seen and seen[reuse] != row.start_ticks:
                diagnostics.append("process_race")
            seen[reuse] = row.start_ticks
            captured.setdefault(key, row)
        for row in sample.retired_processes:
            retired[process_key(row)] = row
    current = {process_key(row) for row in samples[-1].processes}
    if set(captured) - current - set(retired):
        diagnostics.append("tree_incomplete")
    if len(captured) > 256:
        diagnostics.append("overflow")
    return (
        tuple(captured.values())[:256],
        tuple(retired.values())[:256],
        tuple(dict.fromkeys(diagnostics)),
    )


def _assemble(
    samples: tuple[ObservedSample, ...],
    identity: ContainedEvidenceIdentity,
    hashes: tuple[str, str, str],
    captured: tuple[ProcessIdentity, ...],
    retired: tuple[ProcessIdentity, ...],
    diagnostics: tuple[Diagnostic, ...],
    good: bool,
    chain: str,
) -> ContainedObservation:
    first, last = samples[0], samples[-1]
    return ContainedObservation(
        identity=identity,
        spec_sha256=hashes[0],
        proposal_sha256=hashes[1],
        selector_sha256=hashes[2],
        provider_method_sha256=first.parent.provider_method_sha256,
        container=last.container,
        parent=last.parent,
        processes=captured,
        retired_processes=retired,
        last_sample=last,
        sample_count=len(samples),
        sample_chain_sha256=chain,
        first_sample_us=first.started_us,
        final_sample_us=last.finished_us,
        status="observed_contained" if good else "unproven",
        diagnostics=diagnostics,
    )


def _sequence(
    samples: tuple[ObservedSample, ...], deadline: ObservationDeadline
) -> tuple[ObservedSample, ...]:
    if not samples or len(samples) > 12001:
        raise ValueError("Observer complete bounded sample sequence is unavailable")
    samples = tuple(ObservedSample.model_validate(row.model_dump()) for row in samples)
    first = samples[0]
    if any(
        parent_identity(row.parent) != parent_identity(first.parent)
        or row.container != first.container
        or row.deadline_end_us != deadline.end_us
        for row in samples
    ):
        raise ValueError("Observer sequence splices parent or object identity")
    if any(a.finished_us > b.started_us for a, b in pairwise(samples)):
        raise ValueError("Observer sample sequence clock regressed")
    return samples

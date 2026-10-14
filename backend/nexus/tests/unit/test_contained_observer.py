"""Fake transport supplies generated facts; observer union/deadline logic is real."""

from collections.abc import Sequence

import pytest

from nexus.builder.contained_contracts import ParentObservation
from nexus.builder.contained_evidence_types import (
    Diagnostic,
    ExactContainer,
    ObservationDeadline,
    ObservedSample,
    ProcessIdentity,
)
from nexus.builder.contained_observer import ContainmentObserver
from nexus.tests.contained_observer_fixture import container, identity, parent, process
from nexus.tests.unit.test_contained_evidence_types import sample


class IO:
    def __init__(self, values: Sequence[ObservedSample | Exception]) -> None:
        self.values = list(values)
        self.calls: list[int] = []

    async def observe(
        self,
        expected_parent: ParentObservation,
        exact_container: ExactContainer,
        deadline: ObservationDeadline,
        previous: tuple[ProcessIdentity, ...],
    ) -> ObservedSample:
        self.calls.append(deadline.end_us)
        value = self.values.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


@pytest.mark.asyncio
async def test_sample_and_finish_bind_original_identity() -> None:
    io = IO([sample()])
    clock = iter((12_000_000, 12_010_000, 12_015_000, 12_020_000, 12_030_000))
    observer = ContainmentObserver(io, clock_us=lambda: next(clock))
    deadline = ObservationDeadline(end_us=13_000_000)
    row = await observer.sample(parent(), container(), deadline)
    result = await observer.finish(
        (row,),
        identity(),
        spec_sha256="f" * 64,
        proposal_sha256="1" * 64,
        selector_sha256="2" * 64,
        deadline=deadline,
    )
    assert result.status == "observed_contained" and io.calls == [13_000_000]


@pytest.mark.asyncio
@pytest.mark.parametrize("problem", [ValueError("missing"), OSError("race"), TimeoutError("late")])
async def test_io_failure_remains_unproven(problem: Exception) -> None:
    observer = ContainmentObserver(IO([problem]), clock_us=lambda: 12_000_000)
    row = await observer.sample(parent(), container(), ObservationDeadline(end_us=13_000_000))
    assert row.status == "unproven" and row.processes == ()


@pytest.mark.asyncio
async def test_late_return_cannot_finish_as_success() -> None:
    clock = iter((12_020_000, 13_000_001, 13_000_002))
    observer = ContainmentObserver(IO([sample()]), clock_us=lambda: next(clock))
    deadline = ObservationDeadline(end_us=13_000_000)
    row = await observer.sample(parent(), container(), deadline)
    assert row.status == "unproven"
    result = await observer.finish(
        (sample(), row),
        identity(),
        spec_sha256="f" * 64,
        proposal_sha256="1" * 64,
        selector_sha256="2" * 64,
        deadline=deadline,
    )
    assert result.status != "observed_contained"


@pytest.mark.asyncio
async def test_fresh_parent_times_and_retired_union_are_retained() -> None:
    worker = process(104, "descendant")
    first = sample().model_copy(update={"processes": (*sample().processes, worker)})
    fresh = parent().model_copy(
        update={
            "observed_start_us": 12_020_000,
            "observed_end_us": 12_020_000,
            "remaining_us": parent().deadline_us - 12_020_000,
        }
    )
    last = sample().model_copy(
        update={
            "parent": fresh,
            "started_us": 12_020_000,
            "finished_us": 12_030_000,
            "retired_processes": (worker,),
        }
    )
    observer = ContainmentObserver(IO([]), clock_us=lambda: 12_040_000)
    result = await observer.finish(
        (first, last),
        identity(),
        spec_sha256="f" * 64,
        proposal_sha256="1" * 64,
        selector_sha256="2" * 64,
        deadline=ObservationDeadline(end_us=13_000_000),
    )
    assert result.status == "observed_contained"
    assert worker in result.processes and result.retired_processes == (worker,)
    assert result.last_sample == last and result.sample_count == 2


@pytest.mark.asyncio
async def test_late_empty_inventory_does_not_erase_prior_runtime_identity() -> None:
    first = sample().model_copy(
        update={"processes": (*sample().processes, process(103, "runtime"))}
    )
    last = sample().model_copy(
        update={
            "started_us": 12_020_000,
            "finished_us": 12_030_000,
            "processes": (),
            "status": "unproven",
            "diagnostics": ("process_missing",),
        }
    )
    observer = ContainmentObserver(IO([]), clock_us=lambda: 12_040_000)
    result = await observer.finish(
        (first, last),
        identity(),
        spec_sha256="f" * 64,
        proposal_sha256="1" * 64,
        selector_sha256="2" * 64,
        deadline=ObservationDeadline(end_us=13_000_000),
    )
    assert result.status == "unproven"
    assert {p.pid for p in result.processes} == {101, 102, 103}


@pytest.mark.asyncio
async def test_missing_retirement_or_reuse_never_qualifies_complete() -> None:
    first = sample().model_copy(
        update={"processes": (*sample().processes, process(104, "descendant"))}
    )
    for processes in (
        sample().processes,
        (*sample().processes, process(104, "descendant").model_copy(update={"start_ticks": 9999})),
    ):
        last = sample().model_copy(
            update={"started_us": 12_020_000, "finished_us": 12_030_000, "processes": processes}
        )
        observer = ContainmentObserver(IO([]), clock_us=lambda: 12_040_000)
        result = await observer.finish(
            (first, last),
            identity(),
            spec_sha256="f" * 64,
            proposal_sha256="1" * 64,
            selector_sha256="2" * 64,
            deadline=ObservationDeadline(end_us=13_000_000),
        )
        assert result.status == "unproven" and process(104, "descendant") in result.processes


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"processes": ()},
        {"memory_bytes": 1},
        {"retired_processes": (process(104, "descendant", "/foreign"),)},
    ],
)
async def test_finish_revalidates_copied_nested_sample(change: dict[str, object]) -> None:
    observer = ContainmentObserver(IO([]), clock_us=lambda: 12_040_000)
    with pytest.raises(ValueError):
        await observer.finish(
            (sample().model_copy(update=change),),
            identity(),
            spec_sha256="f" * 64,
            proposal_sha256="1" * 64,
            selector_sha256="2" * 64,
            deadline=ObservationDeadline(end_us=13_000_000),
        )


@pytest.mark.asyncio
async def test_cpu_finalization_crossing_deadline_denies(monkeypatch: pytest.MonkeyPatch) -> None:
    import nexus.builder.contained_observer as module

    now = 12_040_000
    original = module._aggregate

    def delayed(
        samples: tuple[ObservedSample, ...],
    ) -> tuple[tuple[ProcessIdentity, ...], tuple[ProcessIdentity, ...], tuple[Diagnostic, ...]]:
        nonlocal now
        value = original(samples)
        now = 13_000_001
        return value

    monkeypatch.setattr(module, "_aggregate", delayed)
    observer = ContainmentObserver(IO([]), clock_us=lambda: now)
    result = await observer.finish(
        (sample(),),
        identity(),
        spec_sha256="f" * 64,
        proposal_sha256="1" * 64,
        selector_sha256="2" * 64,
        deadline=ObservationDeadline(end_us=13_000_000),
    )
    assert result.status == "unproven" and "deadline" in result.diagnostics


@pytest.mark.asyncio
async def test_union_overflow_is_unproven_and_bounded() -> None:
    first = sample().model_copy(
        update={
            "processes": (
                *sample().processes,
                *(process(pid, "descendant") for pid in range(1000, 1253)),
            )
        }
    )
    last = sample().model_copy(
        update={
            "started_us": 12_020_000,
            "finished_us": 12_030_000,
            "processes": (
                *sample().processes,
                *(process(pid, "descendant") for pid in range(1253, 1506)),
            ),
        }
    )
    observer = ContainmentObserver(IO([]), clock_us=lambda: 12_040_000)
    result = await observer.finish(
        (first, last),
        identity(),
        spec_sha256="f" * 64,
        proposal_sha256="1" * 64,
        selector_sha256="2" * 64,
        deadline=ObservationDeadline(end_us=13_000_000),
    )
    assert result.status == "unproven" and "overflow" in result.diagnostics
    assert len(result.processes) <= 256


@pytest.mark.asyncio
async def test_sample_cpu_processing_crossing_deadline_is_unproven() -> None:
    clock = iter((12_000_000, 12_010_000, 13_000_001))
    observer = ContainmentObserver(IO([sample()]), clock_us=lambda: next(clock))
    row = await observer.sample(parent(), container(), ObservationDeadline(end_us=13_000_000))
    assert row.status == "unproven" and row.diagnostics == ("deadline",)

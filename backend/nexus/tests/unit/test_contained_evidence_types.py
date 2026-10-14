"""Pure descriptors separate actual sample caps from expected container limits."""

import pytest
from pydantic import ValidationError

from nexus.builder.contained_evidence_types import (
    ContainedObservation,
    ObservationDeadline,
    ObservedSample,
    ProcessIdentity,
)
from nexus.builder.execution_method import execution_method_candidate
from nexus.tests.contained_observer_fixture import (
    GROUP,
    INVOCATION,
    container,
    identity,
    parent,
    process,
)


def sample() -> ObservedSample:
    return ObservedSample(
        parent=parent(),
        container=container(),
        started_us=12_000_000,
        finished_us=12_010_000,
        deadline_end_us=13_000_000,
        processes=(process(), process(102, "conmon")),
        status="observed_contained",
        diagnostics=(),
        subtree_count=2,
        tree_complete=True,
        memory_bytes=4294967296,
        cpu_quota_us=200000,
        cpu_period_us=100000,
        pids=256,
    )


def observation() -> ContainedObservation:
    row = sample()
    return ContainedObservation(
        identity=identity(),
        spec_sha256="f" * 64,
        proposal_sha256="1" * 64,
        selector_sha256="2" * 64,
        provider_method_sha256=parent().provider_method_sha256,
        container=container(),
        parent=parent(),
        processes=row.processes,
        last_sample=row,
        sample_count=1,
        sample_chain_sha256="5" * 64,
        first_sample_us=12_000_000,
        final_sample_us=12_010_000,
        status="observed_contained",
        diagnostics=(),
    )


def test_generated_description_is_not_activation() -> None:
    assert observation().identity.original_intent_fence == 1
    assert execution_method_candidate().execution_ready is False
    assert "permit" not in observation().model_dump()


@pytest.mark.parametrize(
    "processes", [(), (process(),), (process(102, "conmon"),), (process(), process())]
)
def test_missing_roles_or_duplicate_processes_cannot_claim_complete(
    processes: tuple[ProcessIdentity, ...],
) -> None:
    with pytest.raises(ValidationError):
        ObservedSample.model_validate(sample().model_dump() | {"processes": processes})


@pytest.mark.parametrize(
    "change",
    [
        {"boot_id": INVOCATION},
        {"mount_id": 33},
        {"cgroup_device": 28},
        {"cgroup_path": GROUP + "-sibling/payload"},
    ],
)
def test_foreign_process_identity_denies(change: dict[str, object]) -> None:
    foreign = process().model_copy(update=change)
    with pytest.raises(ValidationError):
        ObservedSample.model_validate(
            sample().model_dump() | {"processes": (foreign, process(102, "conmon"))}
        )


@pytest.mark.parametrize(
    "change",
    [
        {"pids": 255},
        {"cpu_period_us": 50000},
        {"memory_bytes": 1},
        {"finished_us": 1_210_000_000},
        {"tree_complete": False},
        {"diagnostics": ("process_missing",)},
    ],
)
def test_caps_expiry_or_incomplete_tree_denies(change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ObservedSample.model_validate(sample().model_dump() | change)


def test_absolute_deadline_cannot_reset() -> None:
    deadline = ObservationDeadline(end_us=13_000_000)
    assert deadline.remaining_us(12_000_000, parent()) == 1_000_000
    assert deadline.remaining_us(13_000_000, parent()) == 0
    with pytest.raises(ValidationError):
        ObservationDeadline(end_us=True)


@pytest.mark.parametrize(
    "change", [{"processes": ()}, {"memory_bytes": 1}, {"tree_complete": False}]
)
def test_sidecar_rejects_copied_nested_sample(change: dict[str, object]) -> None:
    value = observation().model_dump()
    value["last_sample"] = sample().model_copy(update=change)
    with pytest.raises(ValidationError):
        ContainedObservation.model_validate(value)


def test_expected_runtime_identity_requires_actual_current_row() -> None:
    expected = container().model_copy(update={"runtime_pid": 777})
    with pytest.raises(ValidationError):
        ObservedSample.model_validate(sample().model_dump() | {"container": expected})

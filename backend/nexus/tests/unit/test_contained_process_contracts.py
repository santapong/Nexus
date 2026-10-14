"""Exact generated run binding and final existing time-window checks precede every spawn."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from nexus.builder.contained_process_contracts import PreparedContainedLaunch, require_spawn_ready
from nexus.tests.contained_process_fixture import binding, launch, parent, window


def test_exact_descriptive_launch_and_current_window_are_not_permits() -> None:
    require_spawn_ready(
        launch(),
        binding(),
        parent(),
        window(),
        monotonic_now_us=12_020_000,
        utc_now=datetime(2026, 10, 15, tzinfo=UTC) + timedelta(milliseconds=20),
    )
    assert "permit" not in launch().model_dump()


@pytest.mark.parametrize(
    "argv",
    [
        ("/bin/sh", "-c", "true"),
        ("/usr/bin/podman", "--remote=false", "--cgroup-manager=systemd", "run"),
    ],
)
def test_unknown_or_wrong_runtime_argv_denies(argv: tuple[str, ...]) -> None:
    with pytest.raises(ValidationError):
        PreparedContainedLaunch.model_validate(launch().model_dump() | {"argv": argv})


@pytest.mark.parametrize("changed", ["original_intent_fence", "proposal_sha256"])
def test_binding_copy_or_fence_splice_denies(changed: str) -> None:
    value = 2 if changed == "original_intent_fence" else "f" * 64
    with pytest.raises(ValueError):
        require_spawn_ready(
            launch(),
            binding().model_copy(update={changed: value}),
            parent(),
            window(),
            monotonic_now_us=12_020_000,
            utc_now=datetime(2026, 10, 15, tzinfo=UTC),
        )


def test_source_lease_approval_deadline_crossed_parent_read_denies() -> None:
    with pytest.raises(ValueError):
        require_spawn_ready(
            launch(),
            binding(),
            parent(),
            window(),
            monotonic_now_us=13_000_001,
            utc_now=datetime(2026, 10, 15, tzinfo=UTC) + timedelta(seconds=1),
        )

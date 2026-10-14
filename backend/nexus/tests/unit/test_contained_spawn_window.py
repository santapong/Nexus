"""Pure actual-clock bridge descriptions; no permission or subprocess is issued."""

from datetime import UTC, datetime, timedelta

import pytest

from nexus.builder.contained_spawn_window import SpawnWindow, capture_spawn_window

NOW = datetime(2026, 10, 15, 8, tzinfo=UTC)


def window() -> SpawnWindow:
    return capture_spawn_window(
        database_now=NOW,
        monotonic_before_query_us=1_000_000,
        utc_after_query=NOW,
        deadlines=(NOW + timedelta(seconds=2),),
        operation_end_us=9_000_000,
    )


def test_db_clock_before_query_anchor_is_conservative_and_operation_end_never_extends() -> None:
    value = window()
    assert value.end_us == 3_000_000
    value.require_current(utc_now=NOW + timedelta(seconds=1), monotonic_now_us=2_000_000)
    capped = capture_spawn_window(
        database_now=NOW,
        monotonic_before_query_us=1_000_000,
        utc_after_query=NOW,
        deadlines=(NOW + timedelta(seconds=5),),
        operation_end_us=2_000_000,
    )
    assert capped.end_us == 2_000_000


@pytest.mark.parametrize(
    "utc,mono",
    [
        (NOW + timedelta(seconds=2), 2_500_000),
        (NOW + timedelta(seconds=1), 3_000_000),
        (NOW - timedelta(microseconds=1), 1_500_000),
        (NOW + timedelta(seconds=1), 999_999),
    ],
)
def test_clock_expiry_or_regression_during_parent_read_denies(utc: datetime, mono: int) -> None:
    with pytest.raises(ValueError):
        window().require_current(utc_now=utc, monotonic_now_us=mono)


@pytest.mark.parametrize("offset", [-2, 2])
def test_unsupported_database_to_host_clock_offset_denies_capture(offset: int) -> None:
    with pytest.raises(ValueError):
        capture_spawn_window(
            database_now=NOW,
            monotonic_before_query_us=1_000_000,
            utc_after_query=NOW + timedelta(seconds=offset),
            deadlines=(NOW + timedelta(seconds=5),),
            operation_end_us=9_000_000,
        )


def test_empty_or_expired_source_window_cannot_describe_spawn_eligibility() -> None:
    for deadlines in [(), (NOW,)]:
        with pytest.raises(ValueError):
            capture_spawn_window(
                database_now=NOW,
                monotonic_before_query_us=1_000_000,
                utc_after_query=NOW,
                deadlines=deadlines,
                operation_end_us=9_000_000,
            )


def test_unchecked_model_copy_cannot_extend_monotonic_spawn_deadline() -> None:
    forged = window().model_copy(update={"end_us": 9_000_000})
    with pytest.raises(ValueError, match="extended"):
        forged.require_current(utc_now=NOW + timedelta(seconds=1), monotonic_now_us=2_000_000)

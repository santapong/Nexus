"""Conservative DB-clock/monotonic temporal bridge; a valid window is never permission."""

from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import AwareDatetime, Field, model_validator

from nexus.builder.contained_contracts import ContainedValue, Positive, UInt


class SpawnWindow(ContainedValue):
    """Observed original deadlines, anchored before the last DB clock query; no renewal."""

    database_now: AwareDatetime
    utc_after_query: AwareDatetime
    monotonic_before_query_us: UInt
    deadlines: tuple[AwareDatetime, ...] = Field(min_length=1, max_length=64)
    operation_end_us: Positive
    end_us: Positive

    @model_validator(mode="after")
    def conservative_end(self) -> Self:
        """Reject copied/manufactured extended windows on complete boundary reconstruction."""
        if abs(_microseconds(self.utc_after_query - self.database_now)) > 1_000_000:
            raise ValueError("Builder database/host clock offset is unqualified")
        remaining = min(_microseconds(value - self.database_now) for value in self.deadlines)
        expected = min(self.operation_end_us, self.monotonic_before_query_us + remaining)
        if remaining <= 0 or expected <= self.monotonic_before_query_us or self.end_us != expected:
            raise ValueError("Builder spawn deadline is expired or extended")
        return self

    def require_current(self, *, utc_now: datetime, monotonic_now_us: int) -> None:
        """Run synchronously after final parent IO; keep UTC and monotonic expiry distinct."""
        value = SpawnWindow.model_validate(self.model_dump())
        if (
            utc_now.utcoffset() is None
            or utc_now < value.utc_after_query
            or any(utc_now >= deadline for deadline in value.deadlines)
            or type(monotonic_now_us) is not int
            or not value.monotonic_before_query_us <= monotonic_now_us < value.end_us
        ):
            raise ValueError("Builder final spawn source/lease/approval window expired")
        elapsed_utc = _microseconds(utc_now - value.utc_after_query)
        elapsed_mono = monotonic_now_us - value.monotonic_before_query_us
        if abs(elapsed_utc - elapsed_mono) > 1_000_000:
            raise ValueError("Builder final spawn clock continuity is unqualified")


def capture_spawn_window(
    *,
    database_now: datetime,
    monotonic_before_query_us: int,
    utc_after_query: datetime,
    deadlines: tuple[datetime, ...],
    operation_end_us: int,
) -> SpawnWindow:
    """Actual watcher supplies observed clocks; values alone confer no effect authority."""
    if not deadlines:
        raise ValueError("Builder spawn window requires actual original deadlines")
    remaining = min(_microseconds(value - database_now) for value in deadlines)
    return SpawnWindow(
        database_now=database_now,
        utc_after_query=utc_after_query,
        monotonic_before_query_us=monotonic_before_query_us,
        deadlines=deadlines,
        operation_end_us=operation_end_us,
        end_us=min(operation_end_us, monotonic_before_query_us + remaining),
    )


def _microseconds(value: object) -> int:
    """Datetime arithmetic uses exact integers, avoiding rounded deadlines."""
    from datetime import timedelta

    if not isinstance(value, timedelta):
        raise ValueError("Builder clock difference is unavailable")
    return (value.days * 86_400 + value.seconds) * 1_000_000 + value.microseconds

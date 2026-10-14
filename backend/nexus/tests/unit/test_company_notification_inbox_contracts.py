"""Bounded discovery values do not reinterpret delivery, actual cost or owner authority."""

from __future__ import annotations

import pytest

from nexus.company.notifications.inbox_store import validate_inbox_limit


@pytest.mark.parametrize("value", [False, True, 0, -1, 9, 1.0, "4", None])
def test_server_limit_rejects_non_integer_or_out_of_bound_values(value: object) -> None:
    with pytest.raises(ValueError):
        validate_inbox_limit(value)


@pytest.mark.parametrize("value", [1, 4, 8])
def test_exact_bounded_server_limit(value: int) -> None:
    assert validate_inbox_limit(value) == value

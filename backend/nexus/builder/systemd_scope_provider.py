"""Fresh typed systemd/owned-kernel observations under one bounded monotonic deadline."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Protocol
from uuid import UUID

from nexus.builder.contained_contracts import (
    KernelScopeFacts,
    ObservationBounds,
    ParentObservation,
    ScopeExpectation,
    SystemdScopeFacts,
)
from nexus.builder.contained_kernel import collect_kernel
from nexus.builder.contained_query import (
    PREFIX,
    SCOPE_PROPERTIES,
    SERVICE,
    UNIT_PROPERTIES,
    BusctlReader,
    clock_us,
)
from nexus.builder.contained_scope import validate_current_scope


class ScopeQueryReader(Protocol):
    """Trusted internal read-only transport; no public action-selected callbacks."""

    async def query(self, argv: tuple[str, ...], deadline_us: int) -> bytes:
        """Return bounded actual query bytes by the shared deadline."""
        ...


class SystemdScopeProvider:
    """Historical observations are never cached or promoted into effect permissions."""

    def __init__(
        self,
        *,
        reader: ScopeQueryReader | None = None,
        kernel_reader: Callable[[], Awaitable[KernelScopeFacts]] | None = None,
        clock_us: Callable[[], int] = clock_us,
    ) -> None:
        self._reader = reader if reader is not None else BusctlReader()
        self._kernel_reader = kernel_reader
        self._clock = clock_us

    async def observe(self, expected: ScopeExpectation) -> ParentObservation:
        """Read exact current Unit/Scope and kernel facts again on every call."""
        start = self._clock()
        deadline = start + ObservationBounds().total_io_us
        async with asyncio.timeout(3):
            queries = query_arguments(expected.unit)
            resolved = decode_records(await self._reader.query(queries[0], deadline), ("o",))
            if resolved != ([object_path(expected.unit)],):
                raise ValueError("Resolved systemd object differs from exact expected scope")
            units = decode_records(
                await self._reader.query(queries[1], deadline), ("s", "s", "s", "ay", "t")
            )
            scopes = decode_records(
                await self._reader.query(queries[2], deadline),
                ("s", "t", "t", "b", "t", "t", "t", "t", "s", "b", "t"),
            )
            unit = _scope_facts(units, scopes)
            kernel = (
                await self._kernel_reader()
                if self._kernel_reader is not None
                else await asyncio.to_thread(collect_kernel, expected)
            )
            end = self._clock()
            if end > deadline:
                raise ValueError("Scope observation exceeded the total IO deadline")
            return validate_current_scope(expected, unit, kernel, start, end)


def object_path(unit: str) -> str:
    """Systemd encodes every nonalphanumeric unit byte as underscore plus lower hex."""
    encoded = "".join(
        chr(c) if chr(c).isascii() and chr(c).isalnum() else f"_{c:02x}" for c in unit.encode()
    )
    return "/org/freedesktop/systemd1/unit/" + encoded


def query_arguments(unit: str) -> tuple[tuple[str, ...], ...]:
    """Fixed read-only argv; only the trusted exact unit determines the object path."""
    path = object_path(unit)
    return (
        (
            *PREFIX,
            "call",
            SERVICE,
            "/org/freedesktop/systemd1",
            SERVICE + ".Manager",
            "GetUnit",
            "s",
            unit,
        ),
        (*PREFIX, "get-property", SERVICE, path, SERVICE + ".Unit", *UNIT_PROPERTIES),
        (*PREFIX, "get-property", SERVICE, path, SERVICE + ".Scope", *SCOPE_PROPERTIES),
    )


def decode_records(raw: bytes, signatures: tuple[str, ...]) -> tuple[object, ...]:
    """Exact bounded JSON-lines; duplicate keys/types/unlimited values fail closed."""
    if len(raw) > ObservationBounds().stdout_bytes:
        raise ValueError("Systemd reply exceeds the fixed byte cap")
    lines = raw.splitlines()
    if len(lines) != len(signatures):
        raise ValueError("Systemd reply property count differs")
    values: list[object] = []
    for line, signature in zip(lines, signatures, strict=True):
        row = json.loads(line, object_pairs_hook=_unique_pairs, parse_constant=_reject_constant)
        if not isinstance(row, dict) or set(row) != {"type", "data"} or row["type"] != signature:
            raise ValueError("Systemd reply type/fields differ")
        _require_type(signature, row["data"])
        values.append(row["data"])
    return tuple(values)


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    values: dict[str, object] = {}
    for key, value in pairs:
        if key in values:
            raise ValueError("Duplicate systemd JSON field")
        values[key] = value
    return values


def _reject_constant(value: str) -> object:
    raise ValueError("Nonfinite systemd JSON value")


def _require_type(signature: str, value: object) -> None:
    valid = (
        (signature == "s" and type(value) is str)
        or (signature == "b" and type(value) is bool)
        or (signature == "t" and type(value) is int and 0 <= value < 2**64 - 1)
        or (
            signature == "o"
            and isinstance(value, list)
            and len(value) == 1
            and type(value[0]) is str
        )
        or (
            signature == "ay"
            and isinstance(value, list)
            and len(value) == 16
            and all(type(c) is int and 0 <= c <= 255 for c in value)
        )
    )
    if not valid:
        raise ValueError("Systemd native property value differs from exact signature")


def _scope_facts(units: tuple[object, ...], scopes: tuple[object, ...]) -> SystemdScopeFacts:
    invocation = units[3]
    assert isinstance(invocation, list)
    values = dict(
        zip(
            ("unit", "load_state", "active_state", "invocation_id", "active_enter_us"),
            units,
            strict=True,
        )
    )
    values["invocation_id"] = UUID(bytes=bytes(invocation))
    values.update(
        zip(
            (
                "cgroup_path",
                "runtime_us",
                "randomized_extra_us",
                "delegated",
                "memory_bytes",
                "cpu_per_second_us",
                "cpu_period_us",
                "pids",
                "kill_mode",
                "send_sigkill",
                "stop_us",
            ),
            scopes,
            strict=True,
        )
    )
    return SystemdScopeFacts.model_validate(values)

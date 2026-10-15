"""Fresh typed systemd/owned-kernel observations under one bounded monotonic deadline."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from typing import Protocol
from uuid import UUID

from nexus.builder.contained_contracts import (
    KernelScopeFacts,
    ObservationBounds,
    ParentObservation,
    ScopeExpectation,
    SystemdScopeFacts,
    UserManagerObservation,
    require_user_manager,
)
from nexus.builder.contained_kernel import collect_kernel
from nexus.builder.contained_parent_diagnostics import ParentAttempt, ParentRecorder
from nexus.builder.contained_query import (
    DBUS,
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
        self._ordinal = 0
        self.last_diagnostic: ParentAttempt | None = None

    async def observe(self, expected: ScopeExpectation) -> ParentObservation:
        """Read exact current Unit/Scope and kernel facts again on every call."""
        start = self._clock()
        deadline = start + ObservationBounds().total_io_us
        self._ordinal += 1
        recorder = ParentRecorder(self._ordinal, expected, start)
        self.last_diagnostic = None
        end: int | None = None
        # Keep reads, original validation, final clock and exact exception metadata in one
        # >50-line call boundary: a previous observation can never fill this failed attempt.
        try:
            async with asyncio.timeout(3):
                queries = query_arguments(expected.unit)
                manager = await self._read_manager(queries, deadline, expected.uid, recorder)
                recorder.stage = "resolve"
                resolved = decode_records(await self._query(queries, 2, deadline, recorder), ("o",))
                if resolved != ([object_path(expected.unit)],):
                    raise ValueError("Resolved systemd object differs from exact expected scope")
                recorder.stage = "unit"
                units = decode_records(
                    await self._query(queries, 3, deadline, recorder), ("s", "s", "s", "ay", "t")
                )
                recorder.stage = "scope"
                scopes = decode_records(
                    await self._query(queries, 4, deadline, recorder),
                    ("s", "t", "t", "b", "t", "t", "t", "t", "s", "b", "t"),
                )
                recorder.stage = "unit_decode"
                unit = recorder.unit = _scope_facts(units, scopes, manager)
                recorder.stage = "kernel"
                kernel = (
                    await self._kernel_reader()
                    if self._kernel_reader is not None
                    else await asyncio.to_thread(collect_kernel, expected, manager)
                )
                recorder.kernel = kernel
                end = self._clock()
                recorder.stage = "validate"
                if end > deadline:
                    recorder.code = "deadline"
                    raise ValueError("Scope observation exceeded the total IO deadline")
                result = validate_current_scope(expected, unit, kernel, start, end)
                recorder.stage = "complete"
                snapshot = recorder.finish(None, end)
                end = self._clock()
                if end > deadline or end > result.deadline_us - expected.minimum_remaining_us:
                    recorder.code = "deadline"
                    raise ValueError("Scope diagnostic metadata crossed the original deadline")
                self.last_diagnostic = snapshot
                return result
        except BaseException as failure:
            self.last_diagnostic = recorder.finish(
                failure, end if end is not None else self._clock()
            )
            # Preserve the exact exception/type and bind its own call, including concurrent reads.
            failure.__dict__["nexus_parent_attempt"] = self.last_diagnostic
            raise

    async def _query(
        self,
        queries: tuple[tuple[str, ...], ...],
        index: int,
        deadline: int,
        recorder: ParentRecorder,
    ) -> bytes:
        recorder.begin_query(index, queries[index])
        try:
            raw = await self._reader.query(queries[index], deadline)
        except BaseException as failure:
            recorder.query_failed(failure)
            raise
        recorder.reply(raw)
        return raw

    async def _read_manager(
        self,
        queries: tuple[tuple[str, ...], ...],
        deadline: int,
        uid: int,
        recorder: ParentRecorder,
    ) -> UserManagerObservation:
        recorder.stage = "manager_uid"
        owner = decode_records(await self._query(queries, 0, deadline, recorder), ("u",))[0]
        recorder.stage = "manager_version"
        version = decode_records(await self._query(queries, 1, deadline, recorder), ("s",))[0]
        recorder.stage = "manager_validate"
        assert isinstance(owner, list)
        manager = UserManagerObservation.model_validate(
            {
                "manager": "user",
                "version": version,
                "uid": owner[0],
                "query_route": "fixed_local_user_bus",
            }
        )
        require_user_manager(manager, os.geteuid())
        require_user_manager(manager, uid)
        return manager


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
            DBUS,
            "/org/freedesktop/DBus",
            DBUS,
            "GetConnectionUnixUser",
            "s",
            SERVICE,
        ),
        (
            *PREFIX,
            "get-property",
            SERVICE,
            "/org/freedesktop/systemd1",
            SERVICE + ".Manager",
            "Version",
        ),
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
            signature == "u"
            and isinstance(value, list)
            and len(value) == 1
            and type(value[0]) is int
            and 0 <= value[0] < 2**32
        )
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


def _scope_facts(
    units: tuple[object, ...],
    scopes: tuple[object, ...],
    manager: UserManagerObservation,
) -> SystemdScopeFacts:
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
    values["user_manager"] = manager
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

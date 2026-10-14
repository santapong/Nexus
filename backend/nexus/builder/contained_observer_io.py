"""Fixed cgroupfs engine/proc reader rejects missing, raced and incomplete inventories."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Protocol, cast
from uuid import UUID

from nexus.builder.contained_contracts import (
    ContainedValue,
    ParentObservation,
    Positive,
    cgroup_components,
)
from nexus.builder.contained_engine import ContainedEngineReader
from nexus.builder.contained_evidence_types import (
    ExactContainer,
    ObservationDeadline,
    ObservedSample,
    ProcessIdentity,
    ProcessRole,
    process_key,
)
from nexus.builder.contained_kernel import _boot, open_directory, read_bounded, read_uint
from nexus.builder.contained_query import clock_us
from nexus.builder.contracts import Digest

CGROUP_ROOT = Path("/sys/fs/cgroup")
PROC_ROOT = Path("/proc")
INSPECT_JSON = (
    '{"container_id":{{json .Id}},"image_id":{{json .Image}},'
    '"company_id":{{json (index .Config.Labels "nexus.builder.company")}},'
    '"action_id":{{json (index .Config.Labels "nexus.builder.action")}},'
    '"running":{{json .State.Running}},"payload_pid":{{json .State.Pid}},'
    '"conmon_pid":{{json .State.ConmonPid}}}'
)


class EngineObject(ContainedValue):
    """Actual fixed engine fields, separate from the server's expected object/limits."""

    container_id: Digest
    image_id: Digest
    company_id: UUID
    action_id: UUID
    running: bool
    payload_pid: Positive
    conmon_pid: Positive


class EngineReader(Protocol):
    """Trusted fixed reader; existing shared engine execution is unchanged."""

    async def query(self, argv: tuple[str, ...], deadline_us: int, limit: int) -> bytes:
        """Read only the fixed exact immutable engine ID; no action-chosen commands."""
        ...


class OwnedObservationIO:
    """Engine reader is server configured; this adapter never starts/stops/removes containers."""

    def __init__(self, reader: EngineReader | None = None) -> None:
        self.reader = reader if reader is not None else ContainedEngineReader()

    async def observe(
        self,
        parent: ParentObservation,
        container: ExactContainer,
        deadline: ObservationDeadline,
        previous: tuple[ProcessIdentity, ...],
    ) -> ObservedSample:
        """Shared end caps engine plus kernel work; late kernel threads cannot yield success."""
        start = clock_us()
        remaining = deadline.remaining_us(start, parent)
        if remaining <= 0:
            raise TimeoutError("Contained sample absolute deadline expired")
        async with asyncio.timeout(remaining / 1_000_000):
            raw = await self.reader.query(
                inspect_argv(container), min(deadline.end_us, parent.deadline_us), 65536
            )
            engine = decode_engine_object(raw, container)
            return await asyncio.to_thread(
                _inventory, parent, container, engine, previous, deadline, start
            )


def inspect_argv(container: ExactContainer) -> tuple[str, ...]:
    """Exact cgroupfs inspection; full ID is rechecked by the fixed returned fields."""
    value = ExactContainer.model_validate(container.model_dump())
    return (
        "/usr/bin/podman",
        "--remote=false",
        "--cgroup-manager=cgroupfs",
        "inspect",
        "--format",
        INSPECT_JSON,
        value.container_id,
    )


def decode_engine_object(raw: bytes, expected: ExactContainer) -> EngineObject:
    """Complete bounded JSON and immutable labels/image; cached Running is not process evidence."""
    if len(raw) > 65536:
        raise ValueError("Contained engine inspection exceeds65536bytes")
    json.loads(raw, object_pairs_hook=_unique_pairs)
    value = EngineObject.model_validate_json(raw)
    if (value.container_id, value.image_id, value.company_id, value.action_id, value.running) != (
        expected.container_id,
        expected.image_id,
        expected.company_id,
        expected.action_id,
        True,
    ) or value.payload_pid == value.conmon_pid:
        raise ValueError("Actual contained engine immutable identity differs")
    return value


def _inventory(
    parent: ParentObservation,
    expected: ExactContainer,
    engine: EngineObject,
    previous: tuple[ProcessIdentity, ...],
    deadline: ObservationDeadline,
    started: int,
) -> ObservedSample:
    _alive(deadline, parent)
    _require_mount_root(parent)
    if _boot() != parent.kernel.boot_id or os.geteuid() != parent.kernel.uid:
        raise ValueError("Contained host boot/UID differs")
    root = cgroup_components(parent.kernel.cgroup_path)
    with open_directory(CGROUP_ROOT, root) as fd:
        _require_parent(fd, parent)
        groups, members = _walk(fd, root, deadline, parent)
        processes = tuple(
            _process(pid, path, inode, parent, expected, engine) for pid, path, inode in members
        )
        retired = _retire(previous, processes, deadline, parent)
        payload = next((row for row in processes if row.role == "payload"), None)
        if payload is None or not any(row.role == "conmon" for row in processes):
            raise ValueError("Actual live payload/conmon identities were not observed")
        values = _payload_limits(payload, parent)
        _require_parent(fd, parent)
    with open_directory(CGROUP_ROOT, root) as current:
        _require_parent(current, parent)
    finished = clock_us()
    _require_mount_root(parent)
    _alive(deadline, parent)
    return ObservedSample.model_validate(
        {
            "parent": parent,
            "container": expected,
            "started_us": started,
            "finished_us": finished,
            "deadline_end_us": deadline.end_us,
            "processes": processes,
            "retired_processes": retired,
            "status": "observed_contained",
            "diagnostics": (),
            "subtree_count": groups,
            "tree_complete": True,
            **values,
        }
    )


def _require_parent(fd: int, parent: ParentObservation) -> None:
    actual = os.fstat(fd)
    if (actual.st_dev, actual.st_ino, actual.st_uid) != (
        parent.kernel.mount_device,
        parent.kernel.cgroup_inode,
        parent.kernel.uid,
    ):
        raise ValueError("Actual parent owned directory identity changed")
    if _fd_mount_id(fd) != parent.kernel.mount_id:
        raise ValueError("Actual parent mount ID changed")
    if _limits(fd) != {
        "memory_bytes": parent.kernel.memory_bytes,
        "cpu_quota_us": parent.kernel.cpu_quota_us,
        "cpu_period_us": parent.kernel.cpu_period_us,
        "pids": parent.kernel.pids,
    }:
        raise ValueError("Actual parent numeric limits changed")


def _walk(
    fd: int,
    root: tuple[str, ...],
    deadline: ObservationDeadline,
    parent: ParentObservation,
) -> tuple[int, list[tuple[int, str, int]]]:
    pending: list[tuple[str, ...]] = [()]
    count = 0
    members: list[tuple[int, str, int]] = []
    seen = set()
    while pending:
        _alive(deadline, parent)
        parts = pending.pop()
        with open_directory(CGROUP_ROOT, root + parts) as current:
            value = os.fstat(current)
            if (
                value.st_dev != parent.kernel.mount_device
                or _fd_mount_id(current) != parent.kernel.mount_id
            ):
                raise ValueError("Cgroup subtree mount changed")
            count += 1
            if count > 512:
                raise ValueError("Complete cgroup subtree directory cap reached")
            for raw in read_bounded(current, "cgroup.procs").splitlines():
                pid = read_uint(raw)
                if pid == 0 or pid in seen or len(members) >= 256:
                    raise ValueError("Complete cgroup process count/race cap reached")
                seen.add(pid)
                members.append((pid, "/" + "/".join(root + parts), value.st_ino))
            with os.scandir(current) as entries:
                for entry in entries:
                    if entry.is_symlink():
                        raise ValueError("Cgroup subtree symbolic link is unavailable")
                    if entry.is_dir(follow_symlinks=False):
                        if len(pending) + count >= 512:
                            raise ValueError("Complete cgroup subtree directory cap reached")
                        cgroup_components("/" + entry.name)
                        pending.append((*parts, entry.name))
    return count, members


def _process(
    pid: int,
    path: str,
    inode: int,
    parent: ParentObservation,
    expected: ExactContainer,
    engine: EngineObject,
) -> ProcessIdentity:
    start, actual = _proc(pid)
    if actual != path:
        raise ValueError("Process cgroup changed while enumerating complete subtree")
    role = (
        "payload"
        if pid == engine.payload_pid
        else "conmon"
        if pid == engine.conmon_pid
        else "runtime"
        if pid == expected.runtime_pid
        else "descendant"
    )
    with open_directory(CGROUP_ROOT, cgroup_components(path)) as current:
        value = os.fstat(current)
        mount_id = _fd_mount_id(current)
        if (
            value.st_ino != inode
            or value.st_dev != parent.kernel.mount_device
            or mount_id != parent.kernel.mount_id
        ):
            raise ValueError("Observed process group inode changed")
    again, current_path = _proc(pid)
    if again != start or current_path != path:
        raise ValueError("Observed process start/path identity raced")
    return ProcessIdentity(
        boot_id=parent.kernel.boot_id,
        pid=pid,
        start_ticks=start,
        role=cast(ProcessRole, role),
        cgroup_path=path,
        mount_id=mount_id,
        cgroup_device=parent.kernel.mount_device,
        cgroup_inode=inode,
    )


def _proc(pid: int) -> tuple[int, str]:
    with open_directory(PROC_ROOT, (str(pid),)) as fd:
        raw = read_bounded(fd, "stat")
        end = raw.rfind(b")")
        fields = raw[end + 2 :].split()
        if end < 0 or len(fields) < 20 or raw.split(b" ", 1)[0] != str(pid).encode():
            raise ValueError("Owned process stat shape differs")
        start = read_uint(fields[19])
        lines = read_bounded(fd, "cgroup").decode("ascii").splitlines()
    if len(lines) != 1 or not lines[0].startswith("0::"):
        raise ValueError("Owned process unified cgroup is unavailable")
    path = lines[0][3:]
    cgroup_components(path)
    return start, path


def _retire(
    previous: tuple[ProcessIdentity, ...],
    current: tuple[ProcessIdentity, ...],
    deadline: ObservationDeadline,
    parent: ParentObservation,
) -> tuple[ProcessIdentity, ...]:
    keys = {process_key(row) for row in current}
    retired = []
    for row in previous:
        _alive(deadline, parent)
        if process_key(row) in keys:
            continue
        try:
            start, _ = _proc(row.pid)
        except FileNotFoundError:
            # Distinguish vanished PID directory from inaccessible/missing fields.
            if os.path.lexists(PROC_ROOT / str(row.pid)):
                raise ValueError(
                    "Prior process fields disappeared without proving PID absence"
                ) from None
            retired.append(row)
            continue
        if start != row.start_ticks:
            raise ValueError("Prior PID was reused; retirement remains unproven")
        raise ValueError("Prior same process remains live outside complete current inventory")
    return tuple(retired)


def _limits(fd: int) -> dict[str, int]:
    cpu = read_bounded(fd, "cpu.max").strip().split(b" ")
    if len(cpu) != 2:
        raise ValueError("Observed CPU limit shape differs")
    return {
        "memory_bytes": read_uint(read_bounded(fd, "memory.max")),
        "cpu_quota_us": read_uint(cpu[0]),
        "cpu_period_us": read_uint(cpu[1]),
        "pids": read_uint(read_bounded(fd, "pids.max")),
    }


def _alive(deadline: ObservationDeadline, parent: ParentObservation) -> None:
    if deadline.remaining_us(clock_us(), parent) == 0:
        raise TimeoutError("Shared observation absolute deadline reached")


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Engine JSON repeats an observed field")
        result[key] = value
    return result


def _fd_mount_id(fd: int) -> int:
    """Actual Linux fdinfo mount ID detects same-device bind mounts instead of copying a DTO."""
    with open_directory(Path(f"/proc/{os.getpid()}/fdinfo"), ()) as source:
        rows = read_bounded(source, str(fd)).splitlines()
    values = [row.split(b":", 1)[1].strip() for row in rows if row.startswith(b"mnt_id:")]
    if len(values) != 1:
        raise ValueError("Owned descriptor actual mount ID is unavailable")
    return read_uint(values[0])


def _require_mount_root(parent: ParentObservation) -> None:
    with open_directory(CGROUP_ROOT, ()) as fd:
        value = os.fstat(fd)
        if (value.st_dev, value.st_ino, _fd_mount_id(fd)) != (
            parent.kernel.mount_device,
            parent.kernel.mount_inode,
            parent.kernel.mount_id,
        ):
            raise ValueError("Actual owned cgroup mount root identity changed")


def _payload_limits(payload: ProcessIdentity, parent: ParentObservation) -> dict[str, int]:
    with open_directory(CGROUP_ROOT, cgroup_components(payload.cgroup_path)) as child:
        value = os.fstat(child)
        if (value.st_ino, value.st_dev, _fd_mount_id(child)) != (
            payload.cgroup_inode,
            parent.kernel.mount_device,
            payload.mount_id,
        ):
            raise ValueError("Payload cgroup inode/mount changed")
        values = _limits(child)
        if _fd_mount_id(child) != payload.mount_id:
            raise ValueError("Payload cgroup mount changed while observing actual limits")
        return values

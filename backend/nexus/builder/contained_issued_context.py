"""Opaque owned-start/FD lifetime and exact post-seal membership; no action authority."""

from __future__ import annotations

import asyncio
import hashlib
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar, cast

from nexus.builder.contained_contracts import (
    HostPlacementIdentity,
    KernelScopeFacts,
    ParentObservation,
    ScopeExpectation,
    cgroup_components,
)
from nexus.builder.contained_discovery_seal import FixedDiscoverySeal
from nexus.builder.contained_kernel import _boot, _mount_id, open_directory
from nexus.builder.contained_observer_io import _fd_mount_id, _proc
from nexus.builder.contained_query import clock_us
from nexus.builder.contained_scope import require_current_parent_profile
from nexus.builder.issued_diagnostics import (
    FailureRecorder,
    FieldName,
    Step,
)

if TYPE_CHECKING:
    from nexus.builder.contained_process_contracts import ProcessRunBinding

_ISSUER = object()
CGROUP_ROOT = Path("/sys/fs/cgroup")
T = TypeVar("T")


def _remaining(end: int) -> float:
    remaining = end - clock_us()
    if remaining <= 0:
        raise TimeoutError("Issued membership original deadline expired")
    return remaining / 1_000_000


class OwnedStart:
    """A strong actual child and held original directory; portable data cannot construct this."""

    def __init__(
        self, issuer: object, binding: ProcessRunBinding, expected: ScopeExpectation, end: int
    ) -> None:
        if issuer is not _ISSUER:
            raise TypeError("Owned-start contexts cannot be caller constructed")
        self._issuer, self.binding, self.expected, self.end_us = issuer, binding, expected, end
        self.collector_pid, self.collector_start = os.getpid(), 0
        self.process: asyncio.subprocess.Process | None = None
        self.runtime_start: int | None = None
        self._root_fd: int | None = None
        self._leaf_fd: int | None = None
        self._leaf_info: tuple[int, int, int, int] | None = None
        self._closed = False
        self._lock = threading.Lock()
        self._pending: set[asyncio.Task[object]] = set()
        self._sealed = False
        self.identity: HostPlacementIdentity | None = None

    async def _perform(
        self, operation: Callable[[], T], end: int, trace: FailureRecorder | None = None
    ) -> T:
        end = min(end, self.end_us)
        budget = _remaining(end)
        if self._closed if trace is None else trace.remember("closed", self._closed):
            raise ValueError("Issued ownership context is already closed")

        def checked() -> T:
            _remaining(end)  # Scheduling delay must not start IO after the original end.
            return operation()

        task = asyncio.create_task(asyncio.to_thread(checked))
        retained = cast(asyncio.Task[object], task)
        self._pending.add(retained)
        retained.add_done_callback(self._done)
        async with asyncio.timeout(budget):
            result = await asyncio.shield(task)
        _remaining(end)
        return result

    def _done(self, task: asyncio.Task[object]) -> None:
        self._pending.discard(task)
        if not task.cancelled():
            task.exception()  # A timed-out caller never loses the worker's terminal exception.

    def close(self) -> bool:
        """Close only held descriptors; worker-local fds close in that worker's finally blocks."""
        with self._lock:
            self._closed = True
            for name in ("_root_fd", "_leaf_fd"):
                fd = getattr(self, name)
                if fd is not None:
                    os.close(fd)
                    setattr(self, name, None)
        return all(task.done() for task in self._pending)

    def _prepare(self) -> None:
        expected = self.expected
        if any(
            getattr(self.binding, key) != getattr(expected, key)
            for key in ("company_id", "action_id", "task_id", "trace_id", "run_id")
        ):
            raise ValueError("Owned-start scope differs from actual job")
        start, path = _proc(self.collector_pid)
        if (
            path != expected.cgroup_path
            or _boot() != expected.boot_id
            or os.geteuid() != expected.uid
        ):
            raise ValueError("Owned-start collector is not the strict preissue root process")
        if _mount_id() != expected.mount_id:
            raise ValueError("Owned-start current cgroup mount differs")
        with open_directory(CGROUP_ROOT, ()) as mount:
            stat = os.fstat(mount)
            if (stat.st_dev, stat.st_ino, _fd_mount_id(mount)) != (
                expected.mount_device,
                expected.mount_inode,
                expected.mount_id,
            ):
                raise ValueError("Owned-start mount root changed")
        with open_directory(CGROUP_ROOT, cgroup_components(expected.cgroup_path)) as root:
            self._require_root(root)
            held = os.dup(root)
        with self._lock:
            if self._closed:
                os.close(held)
                raise ValueError("Owned-start preparation completed after close")
            self._root_fd, self.collector_start = held, start

    def _require_root(self, fd: int, trace: FailureRecorder | None = None) -> None:
        stat, expected = os.fstat(fd), self.expected
        observed = stat.st_dev, stat.st_ino, stat.st_uid, _fd_mount_id(fd)
        if trace is not None:
            trace.remember("root", observed)
        if observed != (
            expected.mount_device,
            expected.cgroup_inode,
            expected.uid,
            expected.mount_id,
        ):
            raise ValueError("Owned-start original root descriptor changed")

    def bind_spawn(
        self,
        process: asyncio.subprocess.Process,
        parent: ParentObservation,
        runtime_start: int | None,
    ) -> None:
        require_current_parent_profile(parent)
        if (
            type(process) is not asyncio.subprocess.Process
            or self.process is not None
            or parent.expectation != self.expected
            or parent.issued_identity is not None
            or self._root_fd is None
            or self._closed
        ):
            raise ValueError("Owned-start actual child or strict preissue anchor differs")
        self.process, self.runtime_start = process, runtime_start

    def seal(self, seal: FixedDiscoverySeal) -> OwnedIssuedContext:
        if (
            self.process is None
            or self._sealed
            or self._closed
            or type(seal) is not FixedDiscoverySeal
        ):
            raise ValueError("Owned-start lacks actual process or fixed discovery seal")
        seal.require(self.binding, self.process.pid, seal.container)
        self._sealed = True
        return OwnedIssuedContext(_ISSUER, self, seal)

    # One >50-line descriptor transaction keeps local FDs within a single try/finally;
    # splitting it would obscure the pre/post proc, mount and visible-directory rechecks.
    def _collect(
        self, kernel: KernelScopeFacts, seal: FixedDiscoverySeal, trace: FailureRecorder
    ) -> HostPlacementIdentity:
        """Local descriptors survive cancellation until this bounded-IO worker returns."""
        expected, process = self.expected, self.process
        trace.mark("runtime_initial")
        if (
            trace.remember("closed", self._closed)
            or not trace.remember("runtime_present", process is not None)
            or process is None
            or trace.remember("runtime_returncode", process.returncode) is not None
            or trace.remember("runtime_start", self.runtime_start) is None
        ):
            raise ValueError("Owned runtime is missing, reaped or inaccessible")
        trace.mark("seal_binding")
        trace.remember("runtime_pid", process.pid)
        seal.require(self.binding, process.pid, seal.container)
        path = expected.cgroup_path + "/runtime"
        wanted = (self.collector_start, path), (self.runtime_start, path)
        trace.mark("before_membership")
        if (
            trace.remember("collector_pid", os.getpid()) != self.collector_pid
            or (
                _observed_proc(trace, "collector_before", self.collector_pid),
                _observed_proc(trace, "runtime_before", process.pid),
            )
            != wanted
        ):
            raise ValueError("Actual collector/runtime PID start or exact runtime leaf differs")
        trace.mark("boot_uid_mount")
        if (
            trace.remember("boot_id", _boot()) != expected.boot_id
            or trace.remember("uid", os.geteuid()) != expected.uid
            or trace.remember("mount_id", _mount_id()) != expected.mount_id
        ):
            raise ValueError("Actual issued host boot, UID or mount differs")
        trace.mark("root_open")
        with open_directory(CGROUP_ROOT, cgroup_components(expected.cgroup_path)) as root:
            trace.mark("root_identity")
            self._require_root(root, trace)
            trace.mark("leaf_open")
            leaf = os.open(
                "runtime", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=root
            )
            try:
                trace.mark("leaf_identity")
                stat = os.fstat(leaf)
                info = stat.st_dev, stat.st_ino, stat.st_uid, _fd_mount_id(leaf)
                trace.remember("leaf", info)
                if info[0] != expected.mount_device or info[2:] != (
                    expected.uid,
                    expected.mount_id,
                ):
                    raise ValueError("Actual runtime leaf device, owner or mount differs")
                trace.mark("held_leaf")
                with self._lock:
                    if trace.remember("closed", self._closed) or not trace.remember(
                        "root_known", self._root_fd is not None
                    ):
                        raise ValueError("Issued membership read completed after close")
                    if self._leaf_info is None:
                        self._leaf_fd, self._leaf_info = os.dup(leaf), info
                    if info != self._leaf_info:
                        raise ValueError("Actual held runtime leaf was replaced")
                trace.mark("visible_leaf")
                visible = os.stat("runtime", dir_fd=root, follow_symlinks=False)
                trace.remember(
                    "visible_leaf",
                    (visible.st_dev, visible.st_ino, visible.st_uid, None),
                )
                if (visible.st_dev, visible.st_ino, visible.st_uid) != info[:3]:
                    raise ValueError("Actual runtime leaf changed during membership read")
                trace.mark("root_recheck")
                self._require_root(root, trace)
            finally:
                os.close(leaf)
        after = (
            _observed_proc(trace, "collector_after", self.collector_pid),
            _observed_proc(trace, "runtime_after", process.pid),
        )
        trace.mark("after_membership")
        if (
            after != wanted
            or trace.remember("runtime_returncode_after", process.returncode) is not None
        ):
            raise ValueError("Actual collector/runtime identity changed during read")
        trace.mark("root_visible_after")
        with open_directory(CGROUP_ROOT, cgroup_components(expected.cgroup_path)) as fresh:
            self._require_root(fresh, trace)
        trace.mark("mount_after")
        if trace.remember("mount_id", _mount_id()) != expected.mount_id:
            raise ValueError("Actual issued cgroup mount changed during read")
        trace.mark("kernel_placement")
        if kernel.self_cgroup_path != path or kernel.cgroup_path != expected.cgroup_path:
            raise ValueError("Current kernel facts differ from exact issued placement")
        values = {
            key: getattr(self.binding, key)
            for key in (
                "company_id",
                "action_id",
                "task_id",
                "trace_id",
                "run_id",
                "original_intent_fence",
                "spec_sha256",
                "proposal_sha256",
                "execution_method_sha256",
            )
        }
        identity = HostPlacementIdentity(
            **values,
            container_id=seal.container.container_id,
            container_name=seal.container.container_name,
            image_id=seal.container.image_id,
            boot_id=expected.boot_id,
            uid=expected.uid,
            collector_pid=self.collector_pid,
            collector_start_ticks=self.collector_start,
            runtime_pid=process.pid,
            runtime_start_ticks=cast(int, self.runtime_start),
            mount_id=expected.mount_id,
            mount_device=expected.mount_device,
            mount_inode=expected.mount_inode,
            scope_path=expected.cgroup_path,
            scope_inode=expected.cgroup_inode,
            scope_uid=expected.uid,
            runtime_path=path,
            runtime_mount_id=info[3],
            runtime_device=info[0],
            runtime_inode=info[1],
            runtime_uid=info[2],
        )
        trace.mark("stable_identity")
        with self._lock:
            if trace.remember("closed_after", self._closed) or (
                self.identity is not None and self.identity != identity
            ):
                raise ValueError("Issued stable identity changed or context closed")
            self.identity = identity
        return identity


class OwnedIssuedContext:
    __slots__ = ("_issuer", "owner", "seal")

    def __init__(self, issuer: object, owner: OwnedStart, seal: FixedDiscoverySeal) -> None:
        if issuer is not _ISSUER or type(owner) is not OwnedStart:
            raise TypeError("Issued contexts cannot be deserialized or caller constructed")
        self._issuer, self.owner, self.seal = issuer, owner, seal

    async def observe(
        self,
        expected: ScopeExpectation,
        kernel: KernelScopeFacts,
        end: int,
        *,
        call_token: object | None = None,
    ) -> HostPlacementIdentity:
        trace = FailureRecorder(
            self.owner.expected,
            hashlib.sha256(self.owner.binding.model_dump_json().encode()).hexdigest(),
            self.owner.end_us,
        )
        token = object() if call_token is None else call_token
        try:
            if (
                type(self) is not OwnedIssuedContext
                or self._issuer is not _ISSUER
                or expected != self.owner.expected
            ):
                raise ValueError("Issued context belongs to another original job or scope")
            trace.mark("io_deadline")
            return await self.owner._perform(
                lambda: self.owner._collect(kernel, self.seal, trace), end, trace
            )
        except BaseException as failure:
            trace.attach(failure, token, clock_us())
            raise


async def open_owned_start(
    binding: ProcessRunBinding, expected: ScopeExpectation, end: int
) -> OwnedStart:
    owner = OwnedStart(_ISSUER, binding, expected, end)
    try:
        await owner._perform(owner._prepare, min(end, clock_us() + 3_000_000))
        return owner
    except BaseException:
        owner.close()
        raise


def _observed_proc(trace: FailureRecorder, key: Step, pid: int) -> tuple[int, str]:
    trace.mark(key)
    value = _proc(pid)
    assert key in ("collector_before", "runtime_before", "collector_after", "runtime_after")
    trace.remember(cast(FieldName, key), value)
    trace.mark("before_membership" if key.endswith("before") else "after_membership")
    return value

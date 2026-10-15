"""Ordinary temp-directory descriptors and nominated proc metadata; no cgroup/engine/job."""

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from nexus.builder.contained_contracts import KernelScopeFacts, ParentObservation
from nexus.builder.contained_discovery import ContainedDiscovery
from nexus.builder.contained_discovery_seal import FixedDiscoverySeal
from nexus.builder.contained_issued_context import OwnedStart, open_owned_start
from nexus.builder.contained_kernel import open_directory
from nexus.builder.contained_observer_io import _fd_mount_id
from nexus.builder.contained_scope import validate_current_scope
from nexus.tests.contained_process_fixture import Process, binding, launch, parent
from nexus.tests.unit.test_contained_discovery import body
from nexus.tests.unit.test_contained_discovery_transport import pipe


class Transport:
    """An asyncio.Process handle over a test transport; never an OS child."""

    def __init__(self) -> None:
        self.code: int | None = None
        self.done = asyncio.Event()

    def get_pid(self) -> int:
        return 777

    def get_returncode(self) -> int | None:
        return self.code

    async def _wait(self) -> int:
        await self.done.wait()
        assert self.code is not None
        return self.code

    def kill(self) -> None:
        self.code = -9
        self.done.set()


@dataclass
class MechanicalOwner:
    owner: OwnedStart
    process: asyncio.subprocess.Process
    transport: Transport
    parent: ParentObservation
    kernel: KernelScopeFacts
    base: Path
    root: Path
    leaf: Path
    proc: dict[int, tuple[int, str]]

    def migrate(self) -> None:
        path = self.parent.expectation.cgroup_path + "/runtime"
        self.proc[os.getpid()] = (1111, path)
        self.proc[777] = (7770, path)


# One >50-line nominated setup keeps real temporary descriptors tied to its fake proc transport.
async def prepared(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, bind: bool = True
) -> MechanicalOwner:
    import nexus.builder.contained_issued_context as module

    base = tmp_path / "fake-cgroup"
    base.mkdir()
    original = parent()
    root = base.joinpath(*original.expectation.cgroup_path.split("/")[1:])
    root.mkdir(parents=True)
    with open_directory(base, ()) as fd:
        mount = os.fstat(fd)
        mount_id = _fd_mount_id(fd)
    expected = original.expectation.model_copy(
        update={
            "mount_id": mount_id,
            "mount_device": mount.st_dev,
            "mount_inode": mount.st_ino,
            "cgroup_inode": root.stat().st_ino,
        }
    )
    kernel = original.kernel.model_copy(
        update={
            "mount_id": mount_id,
            "mount_device": mount.st_dev,
            "mount_inode": mount.st_ino,
            "cgroup_inode": root.stat().st_ino,
        }
    )
    current = validate_current_scope(expected, original.unit, kernel, 11_000_000, 12_000_000)
    proc = {os.getpid(): (1111, expected.cgroup_path), 777: (7770, expected.cgroup_path)}
    monkeypatch.setattr(module, "CGROUP_ROOT", base)
    monkeypatch.setattr(module, "_proc", lambda pid: proc[pid])
    monkeypatch.setattr(module, "_boot", lambda: expected.boot_id)
    monkeypatch.setattr(module, "_mount_id", lambda: mount_id)
    monkeypatch.setattr(module, "clock_us", lambda: 12_020_000)
    owner = await open_owned_start(binding(), expected, 13_000_000)
    transport = Transport()
    protocol = SimpleNamespace(stdin=None, stdout=pipe(b"original body"), stderr=pipe(b""))
    process = asyncio.subprocess.Process(
        cast(asyncio.SubprocessTransport, transport),
        cast(asyncio.subprocess.SubprocessStreamProtocol, protocol),
        asyncio.get_running_loop(),
    )
    if bind:
        owner.bind_spawn(process, current, 7770)
    leaf = root / "runtime"
    leaf.mkdir()
    return MechanicalOwner(
        owner,
        process,
        transport,
        current,
        kernel.model_copy(update={"self_cgroup_path": expected.cgroup_path + "/runtime"}),
        base,
        root,
        leaf,
        proc,
    )


async def fixed_seal(monkeypatch: pytest.MonkeyPatch) -> FixedDiscoverySeal:
    import nexus.builder.contained_discovery as module

    probe = Process()
    probe.pid = 888
    probe.stdout = pipe(body())

    async def spawn(*args: str, **kwargs: object) -> asyncio.subprocess.Process:
        return cast(asyncio.subprocess.Process, probe)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(module, "clock_us", lambda: 12_020_000)
    discovery = ContainedDiscovery()
    value = await discovery.discover(launch(), 777, 13_000_000)
    return discovery.take_owned_seal(value)

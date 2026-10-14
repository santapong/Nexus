"""Fixed generated-name discovery seals immutable full ID; Root ID-only reader remains unchanged."""

from __future__ import annotations

import asyncio
import json
from uuid import UUID

from nexus.builder.contained_contracts import ContainedValue, Positive
from nexus.builder.contained_evidence_types import ExactContainer
from nexus.builder.contained_process_contracts import (
    OwnedName,
    PreparedContainedLaunch,
    ProcessRunBinding,
)
from nexus.builder.contained_query import clock_us
from nexus.builder.contracts import Digest
from nexus.builder.process import engine_environment, limited_stream

DISCOVERY_FORMAT = (
    '{"container_id":{{json .Id}},"container_name":{{json .Name}},"image_id":{{json .Image}},'
    '"company_id":{{json (index .Config.Labels "nexus.builder.company")}},'
    '"action_id":{{json (index .Config.Labels "nexus.builder.action")}},'
    '"running":{{json .State.Running}},"payload_pid":{{json .State.Pid}},'
    '"conmon_pid":{{json .State.ConmonPid}}}'
)


class DiscoveryObject(ContainedValue):
    """Only complete exact fields from the owned-name inspection are admitted."""

    container_id: Digest
    container_name: OwnedName
    image_id: Digest
    company_id: UUID
    action_id: UUID
    running: bool
    payload_pid: Positive
    conmon_pid: Positive


class DiscoveryUnavailableError(ValueError):
    """Inspection transport is not ready; never interpreted as absence or qualification."""


class ContainedDiscovery:
    """Concrete bounded read-only discovery; no arbitrary caller command or mutable ID replay."""

    async def discover(
        self,
        launch: PreparedContainedLaunch,
        runtime_pid: int,
        deadline_us: int,
    ) -> ExactContainer:
        argv = discovery_argv(launch.binding)
        process: asyncio.subprocess.Process | None = None
        tasks: list[asyncio.Task[bytes] | asyncio.Task[int]] = []
        try:
            async with asyncio.timeout(_remaining(deadline_us - 100_000)):
                process = await asyncio.create_subprocess_exec(
                    *argv,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=engine_environment(),
                )
                assert process.stdout is not None and process.stderr is not None
                out = asyncio.create_task(limited_stream(process.stdout, 65536))
                err = asyncio.create_task(limited_stream(process.stderr, 4096))
                wait = asyncio.create_task(process.wait())
                tasks = [out, err, wait]
                values = await asyncio.gather(*tasks)
                if process.returncode != 0:
                    raise DiscoveryUnavailableError(
                        "Owned generated container is not currently discoverable"
                    )
                assert isinstance(values[0], bytes)
                return decode_discovery(values[0], launch, runtime_pid=runtime_pid)
        finally:
            await _reap(process, tasks, deadline_us)


def discovery_argv(binding: ProcessRunBinding) -> tuple[str, ...]:
    """Only the deterministic native name may be used before immutable ID sealing."""
    value = ProcessRunBinding.model_validate(binding.model_dump())
    return (
        "/usr/bin/podman",
        "--remote=false",
        "--cgroup-manager=cgroupfs",
        "inspect",
        "--format",
        DISCOVERY_FORMAT,
        value.container_name,
    )


def decode_discovery(
    raw: bytes, launch: PreparedContainedLaunch, *, runtime_pid: int
) -> ExactContainer:
    """Expected labels/name/image are validated before any immutable object observation."""
    if len(raw) > 65536:
        raise ValueError("Contained discovery exceeds complete byte cap")
    launch = PreparedContainedLaunch.model_validate(launch.model_dump())
    json.loads(raw, object_pairs_hook=_unique)
    value = DiscoveryObject.model_validate_json(raw)
    binding = launch.binding
    if (value.container_name, value.image_id, value.company_id, value.action_id, value.running) != (
        binding.container_name,
        binding.image_id,
        binding.company_id,
        binding.action_id,
        True,
    ) or value.payload_pid == value.conmon_pid:
        raise ValueError("Owned discovery name/labels/image/live identity differs")
    return ExactContainer(
        company_id=binding.company_id,
        action_id=binding.action_id,
        image_id=binding.image_id,
        container_id=value.container_id,
        container_name=binding.container_name,
        memory_bytes=launch.memory_bytes,
        cpu_quota_us=launch.cpu_quota_us,
        cpu_period_us=launch.cpu_period_us,
        pids=launch.pids,
        runtime_pid=runtime_pid,
    )


def _remaining(end: int) -> float:
    if type(end) is not int or end <= clock_us():
        raise TimeoutError("Contained discovery shared deadline expired")
    return (end - clock_us()) / 1_000_000


async def _reap(
    process: asyncio.subprocess.Process | None,
    tasks: list[asyncio.Task[bytes] | asyncio.Task[int]],
    end: int,
) -> None:
    if process is None:
        return
    if process.returncode is None:
        process.kill()
    for task in tasks:
        if not task.done():
            task.cancel()
    async with asyncio.timeout(_remaining(end)):
        await asyncio.gather(*tasks, return_exceptions=True)
        await process.wait()


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Contained discovery JSON repeats a field")
        value[key] = item
    return value

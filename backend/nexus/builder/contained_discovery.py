"""Fixed generated-name discovery seals immutable full ID; Root ID-only reader remains unchanged."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from uuid import UUID

from nexus.builder.contained_contracts import ContainedValue, Positive
from nexus.builder.contained_diagnostics import (
    DiscoveryRecorder,
    InspectAttempt,
    StreamObservation,
    error_kind,
)
from nexus.builder.contained_evidence_types import ExactContainer
from nexus.builder.contained_process_contracts import (
    OwnedName,
    PreparedContainedLaunch,
    ProcessRunBinding,
)
from nexus.builder.contained_query import clock_us
from nexus.builder.contracts import Digest
from nexus.builder.process import engine_environment

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

    observation: InspectAttempt | None = None


class ContainedDiscovery:
    """Concrete bounded read-only discovery; no arbitrary caller command or mutable ID replay."""

    # This transaction exceeds 50 lines to keep inspect, its original failure, child reaping,
    # and the final observed-byte record in one try/finally ownership boundary.
    async def discover(
        self,
        launch: PreparedContainedLaunch,
        runtime_pid: int,
        deadline_us: int,
        *,
        recorder: DiscoveryRecorder | None = None,
    ) -> ExactContainer:
        argv = discovery_argv(launch.binding)
        started = clock_us()
        output, errors = _InspectStream(65536), _InspectStream(4096)
        process: asyncio.subprocess.Process | None = None
        tasks: list[asyncio.Task[bytes] | asyncio.Task[int]] = []
        failure: BaseException | None = None
        reaped = False
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
                tasks = [
                    asyncio.create_task(output.read(process.stdout)),
                    asyncio.create_task(errors.read(process.stderr)),
                    asyncio.create_task(process.wait()),
                ]
                values = await asyncio.gather(*tasks)
                if process.returncode != 0:
                    raise DiscoveryUnavailableError(
                        "Owned generated container is not currently discoverable"
                    )
                assert isinstance(values[0], bytes)
                return decode_discovery(values[0], launch, runtime_pid=runtime_pid)
        except BaseException as error:
            failure = error
            raise
        finally:
            try:
                await _reap(process, tasks, deadline_us)
                reaped = process is not None
            except BaseException as error:
                failure = error
                raise
            finally:
                if recorder is not None:
                    attempt = InspectAttempt(
                        index=recorder.total + 1,
                        started_us=started,
                        finished_us=clock_us(),
                        argv_sha256=hashlib.sha256(
                            json.dumps(argv, separators=(",", ":")).encode()
                        ).hexdigest(),
                        child_pid=process.pid if process else None,
                        exit_code=process.returncode if process else None,
                        reaped=reaped,
                        stdout=output.snapshot(),
                        stderr=errors.snapshot(),
                        error_type=error_kind(failure),
                        errno=failure.errno if isinstance(failure, OSError) else None,
                    )
                    recorder.record(attempt)
                    if isinstance(failure, DiscoveryUnavailableError):
                        failure.observation = attempt


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


class _InspectStream:
    """Only fixed inspect captures retain prefixes; SHA/count cover bytes actually observed."""

    def __init__(self, limit: int) -> None:
        self.limit, self.body, self.observed = limit, bytearray(), 0
        self.digest = hashlib.sha256()
        self.complete, self.overflow = False, False

    async def read(self, stream: asyncio.StreamReader) -> bytes:
        while part := await stream.read(min(65536, self.limit - len(self.body) + 1)):
            self.digest.update(part)
            self.observed += len(part)
            remaining = self.limit - len(self.body)
            self.body.extend(part[:remaining])
            if len(part) > remaining:
                self.overflow = True
                raise ValueError("Contained fixed inspect output limit reached")
        self.complete = True
        return bytes(self.body)

    def snapshot(self) -> StreamObservation:
        return StreamObservation(
            observed_bytes=self.observed,
            observed_sha256=self.digest.hexdigest(),
            prefix_base64=base64.b64encode(self.body[:4096]).decode(),
            complete=self.complete,
            overflow=self.overflow,
            byte_limit=self.limit,
        )

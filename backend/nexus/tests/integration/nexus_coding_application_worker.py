"""Two independent real worker processes, bounded private pipes and actual resource retirement.

No worker starts on import. Root releases the parent scenario separately. Secrets
exist only in the one-shot stdin pipe/in-memory job, never argv/output/metadata.
Cohesion exception: the one fixed protocol keeps original private job, actual
spawn/pipe/task owners, production stop/drain and finite containment adjacent;
no reusable executor or production execution authority is added.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import signal
import sys
from collections.abc import Coroutine
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from dbos import DBOS, WorkflowHandleAsync, WorkflowStatusString
from pydantic import Field, SecretStr, model_validator
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from nexus.builder.contained_query import clock_us
from nexus.company.brain.base import ValueContract
from nexus.company.brain.context import ContextManifest
from nexus.core.llm.company_adapter_contracts import JsonSchemaDocument
from nexus.execution.coding_application import CodingApplication, compose_coding_application
from nexus.execution.coding_application_config import CodingApplicationConfig
from nexus.execution.coding_application_preflight import preflight_coding_database
from nexus.execution.coding_application_runtime import (
    retire_coding_application,
    start_coding_application_worker,
)
from nexus.execution.coding_operator import UnavailableCredential
from nexus.execution.coding_worker import CodingSegmentResult
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.planning_application_runtime import (
    PlanningWorkerRuntime,
    start_planning_application_worker,
)
from nexus.execution.planning_worker import PlanningSegmentResult
from nexus.settings import Settings, settings
from nexus.tests.integration.nexus_coding_application_sources import DATABASE, PORT, SOCKET
from nexus.tests.integration.nexus_coding_application_transport import Transport
from nexus.tests.integration.test_nexus_planning_runtime import Credentials
from nexus.tests.unit.test_company_provider_conformance import KEY

if TYPE_CHECKING:
    from nexus.tests.integration.nexus_coding_application_fixture import Case, Database

PREFIX = "NEXUS_C_APPLICATION_WORKER_RESULT="
READY = "NEXUS_C_APPLICATION_WORKER_READY="
CONTROL = "NEXUS_C_APPLICATION_WORKER_CONTROL="
RESOURCE_TAIL_US, KILL_TAIL_US = 5_000_000, 2_000_000
MAX_JOB, MAX_OUTPUT = 1_048_576, 1_048_576
PAID_KEYS = (
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "ANTHROPIC_API_KEY",
    "PGPASSWORD",
)


class WorkerBounds(ValueContract):
    """Original observation/resource containment ends only, never native permissions."""

    observation_end_us: int = Field(gt=0, strict=True)
    retirement_end_us: int = Field(gt=0, strict=True)
    kill_end_us: int = Field(gt=0, strict=True)

    @model_validator(mode="after")
    def original_tails(self) -> WorkerBounds:
        if (
            self.retirement_end_us != self.observation_end_us + RESOURCE_TAIL_US
            or self.kill_end_us != self.retirement_end_us + KILL_TAIL_US
        ):
            raise ValueError("Original worker containment tails differ")
        return self


def worker_bounds(
    case: Case, role: Literal["planner", "coder"], manifest: ContextManifest
) -> WorkerBounds:
    """Capture BEFORE dispatch; no delayed worker may mint a new harness window."""
    before, now = clock_us(), datetime.now(UTC)
    slot = case.config.admission.slots[0 if role == "planner" else 1]
    witness = case.identities[slot.child.binding.actor_id]
    witness.require_time(now)
    expiries = (
        witness.expires_at,
        *(row.expires_at for row in manifest.contributors if row.expires_at is not None),
        *(row.fresh_until for row in manifest.source_heads if row.fresh_until is not None),
    )
    end = min(
        before + 375_000_000,
        case.observation_end_us - RESOURCE_TAIL_US - KILL_TAIL_US,
        *(before + (value - now) // timedelta(microseconds=1) for value in expiries),
    )
    if end <= before:
        raise TimeoutError("Original worker observation window is unavailable before dispatch")
    return WorkerBounds(
        observation_end_us=end,
        retirement_end_us=end + RESOURCE_TAIL_US,
        kill_end_us=end + RESOURCE_TAIL_US + KILL_TAIL_US,
    )


async def wait_before[T](task: asyncio.Future[T], end_us: int) -> T:
    """Bound the observer, never cancel the real task or adopt a late value."""
    while not task.done() and clock_us() < end_us:
        await asyncio.wait((task,), timeout=min(0.05, max(0, end_us - clock_us()) / 1_000_000))
    if not task.done() or clock_us() >= end_us:
        raise TimeoutError("Original observer end elapsed; actual owner retained")
    return task.result()


@dataclass
class ChildStop:
    """The original child's synchronous signal latch, installed before any await."""

    requested: bool = False
    external_requested: bool = False
    application: CodingApplication | None = None
    owners: list[asyncio.Task[object]] = field(default_factory=list)

    def request(self, external: bool = True) -> None:
        self.requested = True
        self.external_requested = self.external_requested or external
        if self.application is not None:
            self.application.planning.lifecycle.request_stop()
            self.application.lifecycle.request_stop()

    def current(self, end_us: int) -> None:
        if self.requested or clock_us() >= end_us:
            self.request()
            raise TimeoutError("Original worker wait stopped")


async def metadata[T](stop: ChildStop, value: Coroutine[object, object, T], end_us: int) -> T:
    try:
        stop.current(end_us)
    except BaseException:
        value.close()
        raise
    task = asyncio.create_task(value)
    stop.owners.append(cast(asyncio.Task[object], task))
    task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    while not task.done() and not stop.requested and clock_us() < end_us:
        await asyncio.wait((task,), timeout=min(0.02, max(0, end_us - clock_us()) / 1_000_000))
    stop.current(end_us)
    if not task.done():
        raise TimeoutError("Actual metadata owner remains pending")
    result = task.result()
    stop.current(end_us)
    return result


async def terminal_result(handle: WorkflowHandleAsync[str], stop: ChildStop, end_us: int) -> str:
    """Pinned public DBOS3.2 statuses; no open-ended pre-step get_result polling."""
    terminal = {
        WorkflowStatusString.SUCCESS.value,
        WorkflowStatusString.ERROR.value,
        WorkflowStatusString.CANCELLED.value,
        WorkflowStatusString.MAX_RECOVERY_ATTEMPTS_EXCEEDED.value,
    }
    while True:
        stop.current(end_us)
        status = await metadata(stop, handle.get_status(), end_us)
        if status.status in terminal:
            return await metadata(stop, handle.get_result(polling_interval_sec=0.05), end_us)
        await asyncio.sleep(min(0.05, max(0, end_us - clock_us()) / 1_000_000))


class WorkerJob(ValueContract):
    """The private in-memory request; secret fields are never serialized by this DTO."""

    role: Literal["planner", "coder"]
    bounds: WorkerBounds
    config: CodingApplicationConfig
    app_url: SecretStr
    system_url: SecretStr
    token: SecretStr
    signing_key: SecretStr
    command: SegmentCommand
    content: str = Field(min_length=1, max_length=65536)
    schema_comment: str = Field(min_length=1, max_length=65536)


class WorkerObservation(ValueContract):
    role: Literal["planner", "coder"]
    pid: int
    returncode: int
    result: PlanningSegmentResult | CodingSegmentResult
    post_sha256s: tuple[str, ...]
    endpoint_lookups: int
    stdout_sha256: str
    stderr_sha256: str


def decode_worker_result(role: str, raw: bytes) -> PlanningSegmentResult | CodingSegmentResult:
    """Decode only the two durable JSON result contracts without weakening strict fields."""
    if role == "planner":
        return PlanningSegmentResult.model_validate_json(raw)
    if role == "coder":
        return CodingSegmentResult.model_validate_json(raw)
    raise ValueError("Worker result requires the exact planner or coder role")


class OutputOverflowError(ValueError):
    """Retain the bounded prefix privately while actual pipe drain reaches EOF."""

    def __init__(self, prefix: bytes, digest: str, length: int) -> None:
        self.prefix, self.digest, self.length = prefix, digest, length
        super().__init__("Worker output exceeded its retained bound")


@dataclass
class StreamState:
    prefix: bytearray = field(default_factory=bytearray)
    sha256: str = field(default_factory=lambda: hashlib.sha256(b"").hexdigest())
    byte_length: int = 0
    eof: bool = False


async def _read(
    stream: asyncio.StreamReader,
    state: StreamState,
    ready: asyncio.Event | None = None,
    pid: int = 0,
) -> bytes:
    digest = hashlib.sha256()
    marker = (READY + str(pid) + "\n").encode()
    while part := await stream.read(65536):
        digest.update(part)
        state.sha256 = digest.hexdigest()
        state.byte_length += len(part)
        state.prefix.extend(part[: max(0, MAX_OUTPUT - len(state.prefix))])
        if ready is not None and marker in state.prefix:
            ready.set()
    state.eof = True
    if state.byte_length > MAX_OUTPUT:
        raise OutputOverflowError(bytes(state.prefix), digest.hexdigest(), state.byte_length)
    return bytes(state.prefix)


@dataclass
class OwnedWorker:
    """Only the actual spawned Process/readers/wait tasks; not a PID selector or permit."""

    process: asyncio.subprocess.Process
    bounds: WorkerBounds
    root: Path
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    out: StreamState = field(default_factory=StreamState)
    err: StreamState = field(default_factory=StreamState)
    readers: tuple[asyncio.Task[bytes], ...] = ()
    reaped: asyncio.Task[int] | None = None
    controller: asyncio.Task[tuple[int, bytes, bytes]] | None = None
    first: BaseException | None = None
    stop_requested: bool = False
    signal_sent: bool = False
    forced: bool = False
    pipes_closed: bool = False
    input_task: asyncio.Task[None] | None = None
    first_stop_us: int | None = None
    spawned_us: int = field(default_factory=clock_us)

    def stop(self, first: BaseException) -> None:
        self.first = self.first or first
        self.stop_requested = True
        if self.first_stop_us is None:
            self.first_stop_us = clock_us()

    def facts(self) -> dict[str, object]:
        return {
            "pid": self.process.pid,
            "spawn_observed_us": self.spawned_us,
            "first_stop_us": self.first_stop_us,
            "returncode": self.process.returncode,
            "bounds": self.bounds.model_dump(mode="json"),
            "stop_sent": self.signal_sent,
            "ready_acknowledged": self.ready.is_set(),
            "forced_unconfirmed": self.forced,
            "parent_pipe_close": self.pipes_closed,
            "reaped": self.reaped is not None
            and self.reaped.done()
            and not self.reaped.cancelled(),
            "stdin_task_settled": self.input_task is not None
            and self.input_task.done()
            and not self.input_task.cancelled(),
            "reader_tasks_settled": all(row.done() and not row.cancelled() for row in self.readers),
            "first_error_type": type(self.first).__name__ if self.first else None,
        }


def _close_owned_pipes(owner: OwnedWorker) -> None:
    # Exact asyncio transport of our original Process. Closing it proves only
    # local descriptor retirement; never natural EOF or remote SDK settlement.
    actual = getattr(owner.process, "_transport", None)
    if not isinstance(actual, asyncio.SubprocessTransport):
        owner.stop(RuntimeError("Original subprocess pipe transport is unavailable"))
        return
    owner.pipes_closed = True
    for descriptor in (0, 1, 2):
        transport = actual.get_pipe_transport(descriptor)
        if isinstance(transport, asyncio.WriteTransport):
            transport.abort()
        elif transport is not None:
            transport.close()


async def _capture(owner: OwnedWorker) -> tuple[int, bytes, bytes]:
    """Finite original child controller; a forced/late/unknown child cannot qualify.

    Cohesion exception: cooperative stop, exact-handle KILL, local pipes/reap and
    retained prefix evidence are one ownership boundary, not a generic executor.
    """
    process, bounds = owner.process, owner.bounds
    assert owner.reaped is not None
    while (
        process.returncode is None
        and not owner.stop_requested
        and clock_us() < bounds.observation_end_us
    ):
        await asyncio.sleep(min(0.02, max(0, bounds.observation_end_us - clock_us()) / 1_000_000))
    if owner.stop_requested or clock_us() >= bounds.observation_end_us:
        owner.stop(owner.first or TimeoutError("Original role queue/result observation expired"))
        ready_end = min(
            bounds.retirement_end_us,
            (owner.first_stop_us + RESOURCE_TAIL_US)
            if owner.first_stop_us is not None
            else bounds.retirement_end_us,
        )
        # No private packet precedes READY. Do not send a default TERM during
        # import/startup and mislabel that exit as cooperative application drain.
        while process.returncode is None and not owner.ready.is_set() and clock_us() < ready_end:
            await asyncio.sleep(min(0.02, max(0, ready_end - clock_us()) / 1_000_000))
        if process.returncode is None and owner.ready.is_set():
            try:
                process.send_signal(signal.SIGTERM)
                owner.signal_sent = True
            except ProcessLookupError:
                pass  # Actual wait/returncode below, never inferred absence.
    tasks = (
        owner.reaped,
        *owner.readers,
        *((owner.input_task,) if owner.input_task is not None else ()),
    )
    retirement_end = min(
        bounds.retirement_end_us,
        (owner.first_stop_us + RESOURCE_TAIL_US)
        if owner.first_stop_us is not None
        else bounds.retirement_end_us,
    )
    kill_end = min(bounds.kill_end_us, retirement_end + KILL_TAIL_US)
    while not all(row.done() for row in tasks) and clock_us() < retirement_end:
        await asyncio.wait(
            tuple(row for row in tasks if not row.done()),
            timeout=min(0.02, max(0, retirement_end - clock_us()) / 1_000_000),
        )
    if not all(row.done() for row in tasks):
        owner.forced = True
        owner.stop(owner.first or TimeoutError("Original child retirement tail expired"))
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()  # ONLY the same actual owned handle; no PID lookup/retry.
        _close_owned_pipes(owner)
        while not all(row.done() for row in tasks) and clock_us() < kill_end:
            await asyncio.wait(tasks, timeout=min(0.02, max(0, kill_end - clock_us()) / 1_000_000))
    if clock_us() >= bounds.observation_end_us:
        owner.stop(owner.first or TimeoutError("Child result is late"))
    for task in tasks:
        if task.done() and not task.cancelled() and task.exception() is not None:
            owner.stop(task.exception() or RuntimeError("Actual child task failed"))
    terminal = owner.facts()
    for name, state in (("stdout", owner.out), ("stderr", owner.err)):
        with (owner.root / name).open("xb") as stream:
            stream.write(state.prefix)
        (owner.root / name).chmod(0o600)
        terminal[name] = {
            "complete": state.eof and not owner.pipes_closed,
            "byte_length": state.byte_length,
            "sha256": state.sha256,
            "prefix_only": state.byte_length > len(state.prefix),
        }
    with (owner.root / "terminal.json").open("x") as stream:
        json.dump(terminal, stream, sort_keys=True)
    (owner.root / "terminal.json").chmod(0o600)
    if not all(row.done() and not row.cancelled() for row in tasks):
        owner.stop(owner.first or TimeoutError("Actual child resource remains unresolved"))
    if owner.first is not None:
        owner.first.__dict__["_nexus_owned_worker"] = owner
        raise owner.first
    assert process.returncode is not None
    for task in tasks:
        task.result()
    return process.returncode, bytes(owner.out.prefix), bytes(owner.err.prefix)


@dataclass
class PendingSpawn:
    """Actual creation Task plus its original limits; late Process is adopted only to stop it."""

    task: asyncio.Task[asyncio.subprocess.Process]
    bounds: WorkerBounds
    root: Path
    wire: bytes = field(repr=False)
    first: BaseException | None = None
    owner: OwnedWorker | None = None


def adopt_spawn(spawn: PendingSpawn, case: Case) -> OwnedWorker:
    if spawn.owner is not None:
        return spawn.owner
    process = spawn.task.result()  # Only the ACTUAL returned owned handle, never a PID/DTO.
    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
    owner = OwnedWorker(process, spawn.bounds, spawn.root)
    spawn.owner = owner
    case.children.append(owner)
    if spawn.first is not None:
        owner.stop(spawn.first)
    owner.readers = (
        asyncio.create_task(_read(process.stdout, owner.out, owner.ready, process.pid)),
        asyncio.create_task(_read(process.stderr, owner.err)),
    )
    owner.reaped = asyncio.create_task(process.wait())
    owner.input_task = asyncio.create_task(_send_job(owner, spawn.wire))
    spawn.wire = b""
    owner.input_task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    owner.controller = asyncio.create_task(_capture(owner))
    owner.controller.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    return owner


async def settle_workers(case: Case) -> None:
    """Stop every original owner before cleanup awaits; no unlimited teardown gather."""
    first: BaseException | None = None
    for spawn in case.spawns:
        if not spawn.task.done():
            spawn.first = spawn.first or RuntimeError("Scenario stopped before spawn returned")
    for owner in case.children:
        if owner.controller is not None and not owner.controller.done():
            owner.stop(RuntimeError("Scenario stopped"))
    for spawn in case.spawns:
        try:
            if spawn.task.done():
                spawn.task.result()  # Historical resource handle, never candidate adoption.
            else:
                await wait_before(spawn.task, spawn.bounds.kill_end_us)
            adopt_spawn(spawn, case)
        except BaseException as error:
            first = first or error
            spawn.first = spawn.first or error
    for owner in case.children:
        if owner.controller is None:
            continue
        try:
            if owner.controller.done():
                owner.controller.result()  # Observe original cleanup, no fresh execution/window.
            else:
                await wait_before(owner.controller, owner.bounds.kill_end_us)
        except BaseException as error:
            owner.first = owner.first or error
            if not (
                owner.process.returncode is not None
                and owner.reaped is not None
                and owner.reaped.done()
                and all(row.done() for row in owner.readers)
                and owner.input_task is not None
                and owner.input_task.done()
            ):
                first = first or owner.first
    if first is not None:
        first.__dict__["_nexus_pending_spawns"] = case.spawns
        raise first


async def _send_job(owner: OwnedWorker, wire: bytes) -> None:
    """READY/write/drain/close is one actual retained task; partial bytes are unconfirmed."""
    stream = owner.process.stdin
    assert stream is not None
    try:
        while (
            not owner.ready.is_set()
            and not owner.stop_requested
            and clock_us() < owner.bounds.observation_end_us
        ):
            await asyncio.sleep(0.01)
        if (
            owner.stop_requested
            or not owner.ready.is_set()
            or clock_us() >= owner.bounds.observation_end_us
        ):
            raise TimeoutError("Original child readiness/packet delivery stopped")
        stream.write(wire)
        await stream.drain()
    finally:
        stream.close()
        await stream.wait_closed()  # Controller aborts ONLY actual fd0 if the fixed tail expires.


async def run_worker(
    case: Case,
    database: Database,
    role: Literal["planner", "coder"],
    command: SegmentCommand,
    content: str,
    root: Path,
    *,
    expected_schema: JsonSchemaDocument,
    bounds: WorkerBounds,
) -> WorkerObservation:
    """One original child, fixed pre-dispatch ends, no restart or late adoption."""
    if clock_us() >= bounds.observation_end_us:
        raise TimeoutError("Worker observation ended before launch")
    root.mkdir(mode=0o700)
    slot = case.config.admission.slots[0 if role == "planner" else 1]
    payload = {
        "role": role,
        "bounds": bounds.model_dump(mode="json"),
        "config": case.config.model_dump(mode="json"),
        "app_url": database.app_url,
        "system_url": database.system_url,
        "token": case.tokens[slot.child.binding.actor_id],
        "signing_key": case.signer.get_secret_value(),
        "command": command.model_dump(mode="json"),
        "content": content,
        "schema_comment": json.loads(expected_schema.document)["$comment"],
    }
    wire = json.dumps(payload, separators=(",", ":")).encode()
    assert len(wire) <= MAX_JOB
    environment = dict(os.environ)
    for name in PAID_KEYS:
        environment.pop(name, None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    task = asyncio.create_task(
        asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            __name__,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=environment,
        )
    )
    spawn = PendingSpawn(task, bounds, root, wire)
    case.spawns.append(spawn)

    def completed(done: asyncio.Task[asyncio.subprocess.Process]) -> None:
        if done.cancelled():
            spawn.first = spawn.first or RuntimeError(
                "Actual creation owner is cancelled/unconfirmed"
            )
            return
        try:
            adopt_spawn(spawn, case)
        except BaseException as error:
            spawn.first = spawn.first or error

    task.add_done_callback(completed)
    try:
        await wait_before(task, bounds.observation_end_us)
        owner = adopt_spawn(spawn, case)
        assert owner.input_task is not None
        await wait_before(owner.input_task, bounds.observation_end_us)
    except BaseException as error:
        spawn.first = spawn.first or error
        if spawn.owner is not None:
            spawn.owner.stop(error)
        try:
            await wait_before(task, bounds.kill_end_us)
        except BaseException:
            error.__dict__["_nexus_pending_spawn"] = spawn
            raise error from None
        owner = adopt_spawn(spawn, case)
        owner.stop(error)
    process = owner.process
    assert owner.controller is not None
    del wire, payload
    while not owner.controller.done() and clock_us() < bounds.kill_end_us:
        try:
            await wait_before(owner.controller, bounds.kill_end_us)
        except asyncio.CancelledError as error:
            owner.stop(error)
        except BaseException as error:
            owner.stop(error)
            break
    if owner.first is not None:
        owner.first.__dict__["_nexus_owned_worker"] = owner
        raise owner.first
    code, out, err = await wait_before(owner.controller, bounds.kill_end_us)
    if clock_us() >= bounds.observation_end_us or owner.forced:
        owner.stop(TimeoutError("Late/forced worker cannot qualify"))
        assert owner.first is not None
        raise owner.first
    assert code == 0
    lines = [line[len(PREFIX) :] for line in out.decode().splitlines() if line.startswith(PREFIX)]
    assert len(lines) == 1
    raw_result = json.loads(lines[0])
    result = decode_worker_result(
        role,
        json.dumps(
            raw_result["result"], ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode(),
    )
    assert result.command == command and not result.company_completed
    observed = WorkerObservation(
        role=role,
        result=result,
        post_sha256s=tuple(raw_result["post_sha256s"]),
        endpoint_lookups=raw_result["endpoint_lookups"],
        pid=process.pid,
        returncode=code,
        stdout_sha256=hashlib.sha256(out).hexdigest(),
        stderr_sha256=hashlib.sha256(err).hexdigest(),
    )
    if clock_us() >= bounds.observation_end_us:
        owner.stop(TimeoutError("Original worker adoption end elapsed"))
        assert owner.first is not None
        raise owner.first
    return observed


async def _child(job: WorkerJob, stop: ChildStop) -> dict[str, object]:
    """Use production restricted preflight, fixed queue launcher and resource-only retirement."""
    url = make_url(job.app_url.get_secret_value())
    system = make_url(job.system_url.get_secret_value())
    assert url.database == system.database == DATABASE
    assert url.username == system.username == "nexus_company_app" and url.password is None
    assert (url.drivername, system.drivername) == ("postgresql+asyncpg", "postgresql+psycopg")
    assert all(
        value is None
        for value in (
            url.host,
            system.host,
            url.port,
            system.port,
            system.password,
        )
    )
    assert dict(url.query) == dict(system.query) == {"host": SOCKET, "port": str(PORT)}
    engine = create_async_engine(url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    signer = job.signing_key.get_secret_value()
    settings.jwt_secret_key, settings.jwt_algorithm = signer, "HS256"
    configured = Settings(
        _env_file=None,
        jwt_secret_key=signer,
        jwt_algorithm="HS256",
        openai_api_key=KEY,
        google_api_key=KEY,
    )
    application = compose_coding_application(
        factory,
        job.config,
        configured,
        Credentials(job.token.get_secret_value())
        if job.role == "planner"
        else UnavailableCredential(),
        Credentials(job.token.get_secret_value())
        if job.role == "coder"
        else UnavailableCredential(),
        job.signing_key,
    )
    stop.application = application
    stop.current(job.bounds.observation_end_us)
    probe = Transport(
        "openai" if job.role == "planner" else "google", job.content, job.schema_comment
    )
    runtime: PlanningWorkerRuntime | None = None
    try:
        stop.current(job.bounds.observation_end_us)
        await preflight_coding_database(
            application, end_us=min(job.bounds.observation_end_us, clock_us() + 30_000_000)
        )
        stop.current(job.bounds.observation_end_us)
        with probe.install():
            runtime = await (
                start_planning_application_worker(
                    application.planning, job.system_url.get_secret_value()
                )
                if job.role == "planner"
                else start_coding_application_worker(application, job.system_url.get_secret_value())
            )
            handle: WorkflowHandleAsync[str] = await metadata(
                stop,
                DBOS.retrieve_workflow_async(job.command.workflow_id),
                job.bounds.observation_end_us,
            )
            raw = await terminal_result(handle, stop, job.bounds.observation_end_us)
            observed = (
                PlanningSegmentResult if job.role == "planner" else CodingSegmentResult
            ).model_validate_json(raw)
            assert observed.command == job.command
        return {
            "result": observed.model_dump(mode="json"),
            "post_sha256s": probe.posts,
            "endpoint_lookups": probe.lookups,
        }
    finally:
        stop.request(external=False)
        sys.stdout.write(
            CONTROL
            + json.dumps(
                {
                    "phase": "retiring",
                    "pending_metadata": sum(
                        not row.done() or row.cancelled() for row in stop.owners
                    ),
                    "bounds": job.bounds.model_dump(mode="json"),
                }
            )
            + "\n"
        )
        sys.stdout.flush()
        # No destroy/dispose while an actual SDK status-read/thread owner remains.
        # The parent owns the fixed physical tail; a stuck leaf stays visibly owned.
        while any(not task.done() or task.cancelled() for task in stop.owners):
            await asyncio.sleep(0.02)
        retirement = asyncio.create_task(
            retire_coding_application(
                application, destroy=runtime.destroy if runtime else None, dispose=engine.dispose
            )
        )
        stop.owners.append(cast(asyncio.Task[object], retirement))
        await asyncio.shield(retirement)
        if stop.external_requested or clock_us() >= job.bounds.observation_end_us:
            raise TimeoutError("Worker completed after its original observation end")


def main() -> int:
    """Explicit child-only entry; a manually owned loop never cancels actual resource owners."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    stop = ChildStop()
    previous = {}

    def stopping(signum: int, frame: object) -> None:
        stop.request()

    for sig in (signal.SIGTERM, signal.SIGINT):
        previous[sig] = signal.signal(sig, stopping)
    sys.stdout.write(READY + str(os.getpid()) + "\n")
    sys.stdout.flush()
    try:
        raw = sys.stdin.buffer.read(MAX_JOB + 1)
        assert 0 < len(raw) <= MAX_JOB
        job = WorkerJob.model_validate_json(raw)
        del raw
        stop.current(job.bounds.observation_end_us)
        value = loop.run_until_complete(_child(job, stop))
        assert not asyncio.all_tasks(loop)
        sys.stdout.write(PREFIX + json.dumps(value, sort_keys=True) + "\n")
        sys.stdout.flush()
        return 0
    except BaseException as error:
        # Never emit repr/traceback: a request or synthetic token must not enter logs.
        sys.stderr.write("C application worker failed: " + type(error).__name__ + "\n")
        sys.stderr.flush()
        pending = asyncio.all_tasks(loop)
        if pending:
            # Existing issued leaves may retire, but no cancel-all or process restart.
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        return 1
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        if not asyncio.all_tasks(loop):
            loop.close()


if __name__ == "__main__":
    raise SystemExit(main())

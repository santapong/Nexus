"""Fixture observer delegates actual invocation and records owned container identity."""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from pathlib import Path
from uuid import uuid5

from pydantic import BaseModel, ConfigDict, Field

from nexus.builder.contracts import Digest
from nexus.builder.engineering_node_runner import EngineeringNodeBuilderRunner
from nexus.builder.execution_contracts import BuilderExecutionSpec, BuilderRunResult
from nexus.builder.node_contracts import NodeRuntimeInputs
from nexus.builder.node_runtime_plan import node_argv
from nexus.builder.process import engine_environment, limited_stream
from nexus.builder.runtime_plan import PreparedSources
from nexus.builder.source_guard import BuilderSourceGuard
from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.actions import ActionProposal
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.tests.csv_native_scope import ROOT
from nexus.tests.csv_native_source import ordinary_bytes

PACKET_SHA = "fd8d4ff533caf8b5a740927680c36f0adbde8329937d52a65318e4a6b3c5b2f5"


class InspectValue(BaseModel):
    # Bounded actual engine result subset, no native protocol/admission authority.
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)


class InspectLabels(InspectValue):
    Labels: dict[str, str]


class InspectState(InspectValue):
    Pid: int = Field(ge=0, strict=True)
    Running: bool


class InspectContainer(InspectValue):
    Id: Digest
    Image: Digest
    Config: InspectLabels
    State: InspectState


class CsvObservedNodeRunner(EngineeringNodeBuilderRunner):
    """Only audit the inherited actual invoke; prepare/run/reconcile remain the reviewed methods."""

    async def invoke(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        action: ActionProposal,
        spec: BuilderExecutionSpec,
        guard: BuilderSourceGuard,
        base: Path,
    ) -> BuilderRunResult:
        packet = json.loads(ordinary_bytes(ROOT / "native-launch-packet-1.json", 65536, PACKET_SHA))
        expected = next(
            row for row in packet["jobs"] if row["action"]["action_id"] == str(action.action_id)
        )
        actual = node_argv(
            spec,
            self.policy,
            self.capabilities,
            PreparedSources(base / "baseline", base / "post"),
            base,
            self.config,
        )
        assert list(actual) == expected["expected_native_argv"]
        path = ROOT / f"invoke-{action.action_id}.json"
        with path.open("x") as stream:
            json.dump(
                {
                    "action_id": str(action.action_id),
                    "intent_fence": lease.fence,
                    "actual_argv": actual,
                },
                stream,
            )
        done = asyncio.Event()
        observed: list[dict[str, object]] = []
        task = asyncio.create_task(_monitor(spec, done, observed))
        try:
            result = await super().invoke(lease, identity, action, spec, guard, base)
        finally:
            done.set()
            await task
            with (ROOT / f"containers-{action.action_id}.json").open("x") as stream:
                json.dump(observed, stream, indent=2)
        assert observed, "actual owned container identity was not observed"
        return result


async def _monitor(
    spec: BuilderExecutionSpec, done: asyncio.Event, observed: list[dict[str, object]]
) -> None:
    job = spec.job
    name = "nexus-builder-" + uuid5(job.company_id, str(job.action_id)).hex
    while not done.is_set():
        row = await _inspect(name)
        if row is not None:
            labels = row.Config.Labels
            assert labels["nexus.builder.action"] == str(job.action_id)
            assert labels["nexus.builder.company"] == str(job.company_id)
            assert spec.runtime_inputs is not None
            assert row.Image == spec.runtime_inputs.image_id
            pid = row.State.Pid
            if row.State.Running and pid > 0:
                try:
                    start = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
                    cgroup = Path(f"/proc/{pid}/cgroup").read_text()
                except FileNotFoundError:
                    continue
                value = {
                    "container_id": row.Id,
                    "pid": pid,
                    "start_identity": start,
                    "cgroup": cgroup,
                }
                if value not in observed:
                    observed.append(value)
        with suppress(TimeoutError):
            await asyncio.wait_for(done.wait(), timeout=0.2)


async def _inspect(name: str) -> InspectContainer | None:
    process = await asyncio.create_subprocess_exec(
        "/usr/bin/podman",
        "--remote=false",
        "inspect",
        name,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env=engine_environment(),
    )
    assert process.stdout is not None
    try:
        async with asyncio.timeout(5):
            raw = await limited_stream(process.stdout, 65536)
            code = await process.wait()
            if code == 125:
                return None
            if code != 0:
                raise ValueError("owned container inspection unavailable")
            return InspectContainer.model_validate_json(json.dumps(json.loads(raw)[0]))
    finally:
        if process.returncode is None:
            process.kill()
        await asyncio.wait_for(process.communicate(), timeout=2)


def verify_capture(result: BuilderRunResult, prepared: Path, runtime: NodeRuntimeInputs) -> None:
    spec = result.spec
    assert result.observed_memory_max == spec.job.limits.memory_bytes
    assert result.observed_cpu_quota == 200000 and result.observed_cpu_period == 100000
    assert result.observed_pids_max == spec.job.limits.pids
    csv = runtime.csv_regression
    assert csv is not None
    assert (
        prepared / "node-commands/csv-regression-pins.json"
    ).read_bytes() == csv.model_dump_json().encode()

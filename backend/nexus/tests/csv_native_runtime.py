"""Pinned public tool/CAS staging and read-only capability observation; no native job."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Literal

from nexus.builder.cache_archive import extract_cache
from nexus.builder.contracts import BuilderCapabilities, BuilderLimits
from nexus.builder.csv_report_contracts import CsvRegressionPins
from nexus.builder.local_toolchain import PNPM_INTEGRITY
from nexus.builder.node_config import NodeRuntimeConfig
from nexus.builder.node_contracts import NodeRuntimeInputs
from nexus.builder.node_v4_recipe import v4_recipe_sha256
from nexus.builder.process import engine_environment, limited_stream
from nexus.builder.public_tool_extract import extract_public_tool
from nexus.tests.builder_node_support import IMAGE, IMAGE_ID
from nexus.tests.csv_native_scope import PUBLIC, require_root
from nexus.tests.csv_native_source import ordinary_bytes

TOOL_SHA = "a61b67ff6cc97af864564f4442556c22a04f2e5a7714fbee76a1011361d9b726"
CACHE_SHA = "154e0e7874ac1c8b38923b71e009c35112999874058a13ae71ec781f3339229c"
MANIFEST_SHA = "877fbbe875c776a870ae2b307887c19cae67553e5228487e3e3eef86466c4c5f"
LOCK_SHA = "d5899f9aff73f1490ecc99c304ed1d8582fbd6e3cdb3d1ef2a86cbeb3de97d55"


def limits() -> BuilderLimits:
    return BuilderLimits(
        cpu_millis=2000,
        memory_bytes=4294967296,
        workspace_bytes=2147483648,
        output_bytes=67108864,
        log_bytes=1048576,
        command_seconds=300,
        job_seconds=1200,
        pids=256,
    )


async def stage_runtime(root: Path, csv: CsvRegressionPins) -> NodeRuntimeConfig:
    value = await asyncio.to_thread(_stage_runtime, root, csv)
    await value.revalidate()
    return value


def _stage_runtime(root: Path, csv: CsvRegressionPins) -> NodeRuntimeConfig:
    require_root(root, existing=True)
    target = root / "public"
    target.mkdir(mode=0o700, exist_ok=False)
    inputs = (
        ("pnpm-9.12.0.tgz", "pnpm-9.12.0.tgz", 33554432, TOOL_SHA),
        ("import/cache.tar", "cache.tar", 2147483648, CACHE_SHA),
        ("public-package-manifest.json", "manifest.json", 2097152, MANIFEST_SHA),
    )
    for source, destination, bound, digest in inputs:
        raw = ordinary_bytes(PUBLIC / source, bound, digest)
        path = target / destination
        with path.open("xb") as stream:
            stream.write(raw)
        path.chmod(0o600)
    archive = target / "pnpm-9.12.0.tgz"
    extract_public_tool(archive.read_bytes(), PNPM_INTEGRITY, target / "tools")
    extract_cache(target / "cache.tar", target / "cache")
    pins = NodeRuntimeInputs(
        recipe="nexus.builder.node.v4",
        tool_symbol="public.pnpm.v9_12.csv.fixture",
        cache_symbol="public.synthetic.csv.cache.v1",
        image_id=IMAGE_ID,
        node_version="22.23.3",
        pnpm_version="9.12.0",
        pnpm_archive_sha256=TOOL_SHA,
        pnpm_integrity=PNPM_INTEGRITY,
        cache_archive_sha256=CACHE_SHA,
        cache_manifest_sha256=MANIFEST_SHA,
        lock_sha256=LOCK_SHA,
        command_recipe_sha256=v4_recipe_sha256(),
        csv_regression=csv,
    )
    return NodeRuntimeConfig(
        pins,
        archive,
        target / "tools",
        target / "cache.tar",
        target / "cache/store",
        target / "manifest.json",
    )


async def observe_capabilities(
    root: Path, *, label: Literal["unscoped", "delegated"] = "unscoped"
) -> BuilderCapabilities:
    """Fresh read-only engine/image facts retain earlier actual bounded runtime qualification."""
    require_root(root, existing=True)
    info = await _engine_read(("info", "--format=json"))
    image = await _engine_read(("image", "inspect", IMAGE))
    for name, raw in (("podman-info.json", info), ("podman-image.json", image)):
        with (root / f"{label}-{name}").open("xb") as stream:
            stream.write(raw)
    host = json.loads(info)["host"]
    installed = json.loads(image)[0]
    if (
        host["arch"] != "amd64"
        or host["cgroupVersion"] != "v2"
        or host["security"]["rootless"] is not True
        or not {"cpu", "memory", "pids"} <= set(host["cgroupControllers"])
        or installed["Id"] != IMAGE_ID
    ):
        raise ValueError("CSV native fresh engine/image capability facts differ")
    _kernel_scope(root)
    previous = ordinary_bytes(
        PUBLIC / "qualification.tar",
        67108864,
        "03c6836252d0b7241fcb0fbbc6e391a1ba6deeb3b63af91dbd808c2eecb988a1",
    )
    # Prior actual same-image runtime proves offline namespace/hard tmpfs configuration.
    # New job's actual Q frame must re-prove numeric caps; this read is not a new execution.
    (root / "capability-basis.sha256").write_text(hashlib.sha256(previous).hexdigest() + "\n")
    return BuilderCapabilities(
        architecture="amd64",
        rootless=True,
        cgroup_v2=True,
        controllers=frozenset({"cpu", "memory", "pids"}),
        hard_workspace_quota=True,
        network_none_verified=True,
        image_present=True,
        qualified_image=IMAGE,
    )


def _kernel_scope(root: Path, *, job: bool = False) -> None:
    """Actual current scope path and numeric kernel limits, never inferred from launch flags."""
    name = (
        "nexus-csv-native-pg-20261015-1-job.scope"
        if job
        else "nexus-csv-native-capabilities-20261015-1.scope"
    )
    cgroup = Path("/proc/self/cgroup").read_text()
    path = cgroup.strip().removeprefix("0::")
    if not cgroup.startswith("0::") or not path.endswith("/" + name) or ".." in Path(path).parts:
        raise ValueError("CSV native capability probe is outside the exact owned delegated scope")
    base = Path("/sys/fs/cgroup") / path.removeprefix("/")
    facts = {
        name: (base / name).read_text().strip()
        for name in ("memory.max", "cpu.max", "pids.max", "cgroup.controllers")
    }
    raw = (json.dumps({"cgroup_path": path, "facts": facts}, indent=2) + "\n").encode()
    with (root / ("job-kernel-caps.json" if job else "delegated-kernel-caps.json")).open(
        "xb"
    ) as stream:
        stream.write(raw)
    if (facts["memory.max"], facts["cpu.max"], facts["pids.max"]) != (
        "4294967296",
        "200000 100000",
        "256",
    ) or not {"cpu", "memory", "pids"} <= set(facts["cgroup.controllers"].split()):
        raise ValueError("CSV native actual delegated kernel limits/controllers differ")


async def job_scope_gate(root: Path) -> None:
    """Actual current JOB scope facts before any native claim; no historical-cap substitution."""
    require_root(root, existing=True)
    _kernel_scope(root, job=True)
    info = await _engine_read(("info", "--format=json"))
    image = await _engine_read(("image", "inspect", IMAGE))
    for name, raw in (("job-podman-info.json", info), ("job-podman-image.json", image)):
        with (root / name).open("xb") as stream:
            stream.write(raw)
    host, installed = json.loads(info)["host"], json.loads(image)[0]
    if (
        host["arch"] != "amd64"
        or host["cgroupVersion"] != "v2"
        or host["security"]["rootless"] is not True
        or not {"cpu", "memory", "pids"} <= set(host["cgroupControllers"])
        or installed["Id"] != IMAGE_ID
    ):
        raise ValueError("CSV native actual JOB scope engine/image capability facts differ")


async def _engine_read(arguments: tuple[str, ...]) -> bytes:
    process = await asyncio.create_subprocess_exec(
        "/usr/bin/podman",
        "--remote=false",
        *arguments,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env=engine_environment(),
    )
    assert process.stdout is not None
    try:
        async with asyncio.timeout(10):
            raw = await limited_stream(process.stdout, 65536)
            if await process.wait() != 0:
                raise ValueError("CSV native read-only engine/image observation unavailable")
        return raw
    finally:
        if process.returncode is None:
            process.kill()
        await asyncio.wait_for(process.communicate(), timeout=2)

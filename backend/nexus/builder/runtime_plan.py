"""One fixed readonly-source sandbox executes the exact finite command sequence."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid5

from nexus.builder.contracts import BuilderCapabilities, BuilderLimits, CommandRef
from nexus.builder.execution_contracts import BuilderExecutionSpec
from nexus.builder.policy import BuilderCommandPolicy, BuilderToolPolicy, require_preparation


@dataclass(frozen=True)
class PreparedSources:
    baseline: Path
    post: Path


def runtime_script(spec: BuilderExecutionSpec, policy: BuilderToolPolicy) -> str:
    spec.require_policy(policy)
    commands = {row.command_key: row for row in policy.commands}
    rows = [
        "#!/bin/sh",
        "set -eu",
        "printf 'NEXUS-BUILDER/1\\n'",
        "printf 'Q '; tr '\\n' ' ' </sys/fs/cgroup/memory.max; "
        "cat /sys/fs/cgroup/cpu.max | tr '\\n' ' '; cat /sys/fs/cgroup/pids.max",
        "mkdir -p /scratch/logs /outputs /tmp/home",
        f"remaining={spec.job.limits.log_bytes}",
    ]
    for index, reference in enumerate(spec.job.commands):
        rows.extend(
            _command_script(index, reference, commands[reference.command_key], spec.job.limits)
        )
    # Artifact paths are scoped beneath their actual phase output root.
    paths = [
        f"{phase}/{path}" for phase in ("baseline", "post") for path in spec.job.artifact_paths
    ]
    rows.extend(
        [
            "if ! tar --format=ustar --owner=0 --group=0 --mtime=@0 -C /outputs "
            "-cf /scratch/export.tar -- "
            + shlex.join(paths)
            + "; then printf 'R artifact_export_failed\\nEND\\n'; exit 0; fi",
            "printf 'A '; base64 -w0 /scratch/export.tar; printf '\\nEND\\n'",
        ]
    )
    return "\n".join(rows) + "\n"


def runtime_argv(
    spec: BuilderExecutionSpec,
    policy: BuilderToolPolicy,
    capabilities: BuilderCapabilities,
    sources: PreparedSources,
    entrypoint: Path,
) -> tuple[str, ...]:
    spec.require_policy(policy)
    require_preparation(spec.job, policy, capabilities)
    mounts = _mounts(sources, entrypoint)
    limit = spec.job.limits
    temporary = min(8_388_608, limit.workspace_bytes // 8)
    scratch = limit.workspace_bytes - limit.output_bytes - temporary
    if scratch <= 0:
        raise ValueError("Builder scratch/output bounds exceed the hard workspace envelope")
    name = "nexus-builder-" + uuid5(spec.job.company_id, str(spec.job.action_id)).hex
    return (
        "/usr/bin/podman",
        "--remote=false",
        "run",
        "--name",
        name,
        "--label",
        f"nexus.builder.action={spec.job.action_id}",
        "--label",
        f"nexus.builder.company={spec.job.company_id}",
        *_isolation_flags(),
        f"--cpus={limit.cpu_millis / 1000:g}",
        f"--memory={limit.memory_bytes}",
        f"--memory-swap={limit.memory_bytes}",
        f"--pids-limit={limit.pids}",
        f"--timeout={limit.job_seconds}",
        "--tmpfs",
        f"/scratch:rw,nodev,nosuid,noexec,size={scratch},mode=0700",
        "--tmpfs",
        f"/outputs:rw,nodev,nosuid,noexec,size={limit.output_bytes},mode=0700",
        "--tmpfs",
        f"/tmp:rw,nodev,nosuid,noexec,size={temporary},mode=1777",
        *mounts,
        "--entrypoint=/bin/sh",
        "--env=HOME=/tmp/home",
        "--env=CI=1",
        "--env=NEXT_TELEMETRY_DISABLED=1",
        policy.image,
        "/nexus-entrypoint.sh",
    )


def _command_script(
    index: int, reference: CommandRef, command: BuilderCommandPolicy, limits: BuilderLimits
) -> list[str]:
    directory = f"/source/{reference.phase}" + (
        "" if command.directory == "." else "/" + command.directory
    )
    return [
        f"cd {shlex.quote(directory)}",
        f"export NEXUS_OUTPUT_DIR=/outputs/{reference.phase}",
        'mkdir -p "$NEXUS_OUTPUT_DIR"',
        "start=$(date +%s%N)",
        "set +e",
        f"timeout --signal=KILL {limits.command_seconds}s "
        f"{shlex.join(command.argv)} >/scratch/logs/{index}.out 2>/scratch/logs/{index}.err",
        "code=$?",
        "set -e",
        "end=$(date +%s%N)",
        "elapsed=$(((end-start)/1000000))",
        'test "$elapsed" -ge 0 || elapsed=0',
        f'printf \'C {index} %s %s\\n\' "$code" "$elapsed"',
        "available=$remaining",
        f"out_size=$(wc -c </scratch/logs/{index}.out)",
        f"err_size=$(wc -c </scratch/logs/{index}.err)",
        'captured=$out_size; test "$captured" -le "$remaining" || captured=$remaining',
        f"printf 'O {index} '; head -c \"$captured\" "
        f"/scratch/logs/{index}.out | base64 -w0; printf '\\n'",
        "remaining=$((remaining-captured))",
        'captured=$err_size; test "$captured" -le "$remaining" || captured=$remaining',
        f"printf 'E {index} '; head -c \"$captured\" "
        f"/scratch/logs/{index}.err | base64 -w0; printf '\\n'",
        "remaining=$((remaining-captured))",
        'if test "$((out_size+err_size))" -gt "$available"; '
        "then printf 'R log_limit\\nEND\\n'; exit 0; fi",
        "if test \"$code\" -ne 0; then printf 'END\\n'; exit 0; fi",
    ]


def _isolation_flags() -> tuple[str, ...]:
    return (
        "--pull=never",
        "--network=none",
        "--http-proxy=false",
        "--no-hosts",
        "--no-hostname",
        "--passwd=false",
        "--no-healthcheck",
        "--read-only",
        "--read-only-tmpfs=false",
        "--image-volume=ignore",
        "--log-driver=none",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pid=private",
        "--ipc=private",
        "--uts=private",
        "--cgroupns=private",
    )


def _mounts(sources: PreparedSources, entrypoint: Path) -> tuple[str, ...]:
    resolver = entrypoint.parent / "resolv.conf"
    for path in (sources.baseline, sources.post, entrypoint, resolver):
        if (
            not path.is_absolute()
            or path.resolve(strict=True) != path
            or any(char in str(path) for char in ":,\n\r\x00")
        ):
            raise ValueError("Builder runtime mount is not an ordinary managed path")
        if str(path).startswith(("/home/", "/root/")):
            raise ValueError("Builder runtime cannot mount an owner home path")
    return (
        "--volume",
        f"{sources.baseline}:/source/baseline:ro",
        "--volume",
        f"{sources.post}:/source/post:ro",
        "--volume",
        f"{entrypoint}:/nexus-entrypoint.sh:ro",
        "--volume",
        f"{resolver}:/etc/resolv.conf:ro",
    )

"""Decode bounded actual runtime observations; never infer business acceptance."""

from __future__ import annotations

import base64
import hashlib
import io
import tarfile
from datetime import datetime

from nexus.builder.contracts import BuilderArtifact, BuilderCommandReceipt
from nexus.builder.execution_contracts import (
    BuilderExecutionSpec,
    BuilderOutcome,
    BuilderRunResult,
    CapturedFile,
)
from nexus.builder.paths import permitted_path, relative_path


def captured(path: str, raw: bytes) -> CapturedFile:
    return CapturedFile(
        metadata=BuilderArtifact(
            path=path, sha256=hashlib.sha256(raw).hexdigest(), byte_length=len(raw)
        ),
        content_base64=base64.b64encode(raw).decode(),
    )


def decode_artifacts(encoded: str, spec: BuilderExecutionSpec) -> tuple[CapturedFile, ...]:
    raw = base64.b64decode(encoded, validate=True)
    if len(raw) > spec.job.limits.output_bytes + 262144:
        raise ValueError("Builder export exceeds its archive bound")
    results: list[CapturedFile] = []
    names: set[str] = set()
    total = 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        for entry in archive:
            name = entry.name.rstrip("/") if entry.isdir() else entry.name
            path = relative_path(name)
            if path.parts[0] not in {"baseline", "post"}:
                raise ValueError("Builder artifact phase is unavailable")
            if (
                not (entry.isfile() or entry.isdir())
                or entry.sparse
                or len(names) >= 256
                or name in names
            ):
                raise ValueError("Builder export has unsafe or duplicate entries")
            names.add(name)
            suffix = "/".join(path.parts[1:])
            if not permitted_path(suffix, spec.job.artifact_paths):
                raise ValueError("Builder export exceeds declared paths")
            if entry.isdir():
                continue
            stream = archive.extractfile(entry)
            if stream is None or entry.size < 0:
                raise ValueError("Builder artifact is unavailable")
            total += entry.size
            if total > spec.job.limits.output_bytes:
                raise ValueError("Builder export exceeds its complete byte bound")
            with stream:
                content = stream.read(entry.size + 1)
            if len(content) != entry.size:
                raise ValueError("Builder export length differs")
            results.append(captured(name, content))
    return tuple(results)


def decode_runtime(
    stdout: bytes,
    spec: BuilderExecutionSpec,
    proposal_sha256: str,
    intent_fence: int,
    image_id: str,
    container_name: str,
    recorded_at: datetime,
    elapsed_millis: int,
) -> BuilderRunResult:
    lines = stdout.decode("ascii").splitlines()
    if not lines or lines[0] != "NEXUS-BUILDER/1" or lines[-1] != "END":
        raise ValueError("Builder runtime envelope is incomplete")
    memory, quota, period, pids = _quantum(lines[1], spec)
    commands, logs, artifacts, reason = _frames(lines[2:-1], spec)
    outcome = _outcome(commands, spec, reason)
    return BuilderRunResult(
        spec=spec,
        proposal_sha256=proposal_sha256,
        intent_fence=intent_fence,
        image_id=image_id,
        container_name=container_name,
        outcome=outcome,
        commands=tuple(commands),
        artifacts=artifacts,
        logs=tuple(logs),
        observed_memory_max=memory,
        observed_cpu_quota=quota,
        observed_cpu_period=period,
        observed_pids_max=pids,
        recorded_at=recorded_at,
        elapsed_millis=elapsed_millis,
        limitations=(
            "local_mechanical_only",
            "business_readiness_unproven",
            *((reason,) if reason else ()),
        ),
    )


def _quantum(line: str, spec: BuilderExecutionSpec) -> tuple[int, int, int, int]:
    quantum = line.split()
    if len(quantum) != 5 or quantum[0] != "Q":
        raise ValueError("Builder runtime limits are unavailable")
    memory, quota, period, pids = (int(value) for value in quantum[1:])
    limit = spec.job.limits
    if (
        min(memory, quota, period, pids) <= 0
        or memory > limit.memory_bytes
        or pids > limit.pids
        or quota * 1000 > limit.cpu_millis * period
    ):
        raise ValueError("Builder runtime limits exceed the exact job")
    return memory, quota, period, pids


def _frames(
    lines: list[str], spec: BuilderExecutionSpec
) -> tuple[list[BuilderCommandReceipt], list[CapturedFile], tuple[CapturedFile, ...], str | None]:
    commands: list[BuilderCommandReceipt] = []
    logs: list[CapturedFile] = []
    artifacts: tuple[CapturedFile, ...] = ()
    offset = 0
    log_bytes = 0
    reason = None
    while offset < len(lines) and lines[offset].startswith("C "):
        if commands and commands[-1].exit_code != 0:
            raise ValueError("Builder runtime continued after a failed command")
        index, code, elapsed = (int(value) for value in lines[offset][2:].split())
        if index != len(commands) or index >= len(spec.job.commands) or elapsed < 0:
            raise ValueError("Builder actual command order/time differs")
        command = spec.job.commands[index]
        commands.append(
            BuilderCommandReceipt(
                command_key=command.command_key,
                phase=command.phase,
                exit_code=code,
                outcome="exited",
                elapsed_millis=elapsed,
            )
        )
        offset, new_logs, size = _command_logs(
            lines, offset, index, spec.job.limits.log_bytes - log_bytes
        )
        logs.extend(new_logs)
        log_bytes += size
    if offset < len(lines) and lines[offset].startswith("A "):
        artifacts = decode_artifacts(lines[offset][2:], spec)
        offset += 1
    elif offset < len(lines) and lines[offset] in {"R log_limit", "R artifact_export_failed"}:
        reason = lines[offset][2:]
        offset += 1
    if not commands or offset != len(lines):
        raise ValueError("Builder duplicate or unsupported runtime frame")
    reason = _export_reason(commands, artifacts, reason, spec)
    return commands, logs, artifacts, reason


def _outcome(
    commands: list[BuilderCommandReceipt], spec: BuilderExecutionSpec, reason: str | None
) -> BuilderOutcome:
    if reason == "log_limit":
        return "resource_limited"
    if reason == "artifact_export_failed":
        return "artifact_export_failed"
    if any(row.exit_code == 127 for row in commands):
        return "tool_missing"
    if any(row.exit_code in {124, 137} for row in commands):
        return "timed_out"
    return (
        "commands_succeeded"
        if len(commands) == len(spec.job.commands) and all(row.exit_code == 0 for row in commands)
        else "commands_failed"
    )


def _command_logs(
    lines: list[str], offset: int, index: int, limit: int
) -> tuple[int, list[CapturedFile], int]:
    logs = []
    size = 0
    for tag, suffix in (("O", "out"), ("E", "err")):
        offset += 1
        prefix = f"{tag} {index} "
        if offset >= len(lines) or not lines[offset].startswith(prefix):
            raise ValueError("Builder exact command logs are unavailable")
        raw = base64.b64decode(lines[offset][len(prefix) :], validate=True)
        size += len(raw)
        if size > limit:
            raise ValueError("Builder logs exceed their complete byte bound")
        logs.append(captured(f"logs/{index}.{suffix}", raw))
    return offset + 1, logs, size


def _export_reason(
    commands: list[BuilderCommandReceipt],
    artifacts: tuple[CapturedFile, ...],
    reason: str | None,
    spec: BuilderExecutionSpec,
) -> str | None:
    if artifacts and (
        len(commands) != len(spec.job.commands) or any(row.exit_code != 0 for row in commands)
    ):
        raise ValueError("Builder artifact export lacks complete successful commands")
    missing = any(
        not any(
            row.metadata.path.startswith(f"{phase}/{path}/")
            or row.metadata.path == f"{phase}/{path}"
            for row in artifacts
        )
        for phase in ("baseline", "post")
        for path in spec.job.artifact_paths
    )
    if (
        len(commands) == len(spec.job.commands)
        and all(row.exit_code == 0 for row in commands)
        and reason is None
        and missing
    ):
        reason = "artifact_export_failed"
    return reason

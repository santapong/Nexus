"""Node-only transition failure retains the four actual successful baseline receipts."""

from __future__ import annotations

from dataclasses import replace

from nexus.builder.execution_contracts import BuilderExecutionSpec, BuilderRunResult
from nexus.builder.process import ProcessCapture
from nexus.builder.runner_capture import capture_result
from nexus.company.contracts.actions import ActionProposal


def node_capture_result(
    capture: ProcessCapture,
    spec: BuilderExecutionSpec,
    action: ActionProposal,
    fence: int,
    image_id: str,
    name: str,
) -> BuilderRunResult:
    suffix = b"R phase_cleanup_failed\nEND\n"
    transition_failed = (
        spec.runtime_inputs is not None
        and spec.runtime_inputs.recipe in {"nexus.builder.node.v3", "nexus.builder.node.v4"}
        and capture.exit_code == 0
        and capture.interruption is None
        and capture.stdout.endswith(suffix)
    )
    normalized = (
        replace(capture, stdout=capture.stdout.removesuffix(suffix) + b"END\n")
        if transition_failed
        else capture
    )
    result = capture_result(normalized, spec, action, fence, image_id, name)
    if transition_failed and (
        result.outcome == "commands_failed"
        and len(result.commands) == 4
        and all(row.phase == "baseline" and row.exit_code == 0 for row in result.commands)
        and not result.artifacts
    ):
        return result.model_copy(
            update={"limitations": (*result.limitations, "phase_cleanup_failed")}
        )
    if transition_failed:
        return capture_result(capture, spec, action, fence, image_id, name)
    return result

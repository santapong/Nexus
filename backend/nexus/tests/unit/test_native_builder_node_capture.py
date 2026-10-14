"""Only exact Node-v3 four-baseline transition failure is normalized; caps stay strict."""

from dataclasses import replace
from pathlib import Path

import pytest

from nexus.builder.node_capture import node_capture_result
from nexus.builder.process import ProcessCapture
from nexus.builder.runner_capture import capture_result
from nexus.tests.builder_support import described_binding
from nexus.tests.unit.test_native_builder_node_recipe import configured


def frame(count: int = 4, *, memory: int = 4_294_967_296) -> ProcessCapture:
    lines = ["NEXUS-BUILDER/1", f"Q {memory} 200000 100000 256"]
    for index in range(count):
        lines.extend((f"C {index} 0 1", f"O {index} ", f"E {index} "))
    lines.extend(("R phase_cleanup_failed", "END"))
    return ProcessCapture(("\n".join(lines) + "\n").encode(), b"", 0, 4, None)


def test_node_cleanup_failure_retains_actual_commands_and_generic_codec_is_unchanged(
    tmp_path: Path,
) -> None:
    _, spec = configured(tmp_path)
    action, lease, _ = described_binding(spec.job)
    capture = frame()
    result = node_capture_result(
        capture, spec, action, lease.fence, "c" * 64, "nexus-builder-" + "d" * 32
    )
    assert result.outcome == "commands_failed" and len(result.commands) == 4
    assert all(row.exit_code == 0 and row.phase == "baseline" for row in result.commands)
    assert not result.artifacts and "phase_cleanup_failed" in result.limitations
    generic = capture_result(
        capture, spec, action, lease.fence, "c" * 64, "nexus-builder-" + "d" * 32
    )
    assert (
        generic.outcome == "outcome_unknown" and "runtime_envelope_invalid" in generic.limitations
    )


@pytest.mark.parametrize("case", ["partial", "cap", "interrupted", "exit", "legacy"])
def test_invalid_cleanup_context_does_not_become_known_failed_phase(
    tmp_path: Path, case: str
) -> None:
    _, spec = configured(tmp_path)
    capture = frame()
    if case == "partial":
        capture = frame(3)
    if case == "cap":
        capture = frame(memory=4_294_967_297)
    if case == "interrupted":
        capture = replace(capture, interruption="watchdog_denied")
    if case == "exit":
        capture = replace(capture, exit_code=1)
    if case == "legacy":
        assert spec.runtime_inputs is not None
        spec = spec.model_copy(
            update={
                "runtime_inputs": spec.runtime_inputs.model_copy(
                    update={"recipe": "nexus.builder.node.v2"}
                )
            }
        )
    action, lease, _ = described_binding(spec.job)
    result = node_capture_result(
        capture, spec, action, lease.fence, "c" * 64, "nexus-builder-" + "d" * 32
    )
    assert result.outcome == "outcome_unknown"
    assert "phase_cleanup_failed" not in result.limitations

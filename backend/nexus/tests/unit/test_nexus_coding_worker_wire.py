"""Strict durable worker-result JSON only; no worker, DB, SDK or native execution."""

import ast
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import pytest
from pydantic import ValidationError

from nexus.execution.coding_worker import CodingSegmentResult
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.planning_worker import PlanningSegmentResult

# Execute only the actual pure decoder node, never the unrelated integration/SDK graph.
_worker = Path(__file__).parents[1] / "integration/nexus_coding_application_worker.py"
_decoders: list[ast.stmt] = [
    node
    for node in ast.parse(_worker.read_bytes()).body
    if isinstance(node, ast.FunctionDef) and node.name == "decode_worker_result"
]
assert len(_decoders) == 1
_namespace: dict[str, Any] = {
    "PlanningSegmentResult": PlanningSegmentResult,
    "CodingSegmentResult": CodingSegmentResult,
}
exec(compile(ast.Module(body=_decoders, type_ignores=[]), str(_worker), "exec"), _namespace)
decode_worker_result: Callable[[str, bytes], PlanningSegmentResult | CodingSegmentResult] = (
    _namespace["decode_worker_result"]
)


def result(role: Literal["planner", "coder"]) -> PlanningSegmentResult | CodingSegmentResult:
    command = SegmentCommand(
        company_id=UUID(int=1),
        task_id=UUID(int=2),
        trace_id=UUID(int=3),
        actor_id=UUID(int=4),
        workspace_id=UUID(int=5),
        run_id=UUID(int=6),
        action_id=UUID(int=7),
        segment_id=UUID(int=8),
    )
    model = PlanningSegmentResult if role == "planner" else CodingSegmentResult
    return model(
        command=command,
        status="historical_candidate",
        native_state="succeeded",
        request_sha256="a" * 64,
        receipt_id=UUID(int=9),
        artifact_id=UUID(int=10),
        artifact_sha256="b" * 64,
        lease_released=True,
    )


@pytest.mark.parametrize("role", ["planner", "coder"])
def test_exact_actual_result_contract_keeps_json_uuid_values(
    role: Literal["planner", "coder"],
) -> None:
    original = result(role)
    wire = original.model_dump_json().encode()
    decoded = decode_worker_result(role, wire)
    assert type(decoded) is type(original)
    assert decoded == original and decoded.receipt_id == UUID(int=9)
    assert decoded.artifact_id == UUID(int=10) and decoded.command == original.command
    assert not decoded.company_completed and not decoded.resources_pending
    assert decoded.model_dump_json().encode() == wire


@pytest.mark.parametrize("role", ["planner", "coder"])
@pytest.mark.parametrize("field", ["receipt_id", "artifact_id"])
def test_malformed_uuid_is_denied(role: Literal["planner", "coder"], field: str) -> None:
    payload = result(role).model_dump(mode="json")
    payload[field] = "not-a-uuid"
    with pytest.raises(ValidationError, match=field):
        decode_worker_result(role, json.dumps(payload).encode())


@pytest.mark.parametrize("role", ["planner", "coder"])
@pytest.mark.parametrize("change", ["extra", "string-boolean", "completed"])
def test_json_mode_keeps_extra_boolean_and_completion_denials(
    role: Literal["planner", "coder"], change: str
) -> None:
    payload = result(role).model_dump(mode="json")
    if change == "extra":
        payload["unexpected"] = "untrusted"
    elif change == "string-boolean":
        payload["lease_released"] = "true"
    else:
        payload["company_completed"] = True
    with pytest.raises(ValidationError):
        decode_worker_result(role, json.dumps(payload).encode())


@pytest.mark.parametrize("role", ["planner", "coder"])
@pytest.mark.parametrize("wire", [b"null", b"[]", b'"result"', b"true", b"1", b"{"])
def test_nonobject_or_malformed_json_is_denied(role: str, wire: bytes) -> None:
    with pytest.raises(ValidationError):
        decode_worker_result(role, wire)


@pytest.mark.parametrize("role", ["", "PLANNER", "engineering", "owner"])
def test_other_roles_have_no_result_decoder(role: str) -> None:
    with pytest.raises(ValueError, match="exact planner or coder"):
        decode_worker_result(role, result("planner").model_dump_json().encode())

"""Closed model deployment identities; legacy reads never confer execution authority."""

from __future__ import annotations

import json
from collections.abc import Mapping

from nexus.company.management.scheduling_contracts import WorkflowRegistration
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.runtime_contracts import EffectRecord

PLANNING_APPLICATION_VERSION = "nexus-planning-v1"
CODING_APPLICATION_VERSION = "nexus-coding-v1"
_MODEL_IDENTITIES = (
    (
        ("company.planning.v1", "v1", "nexus.planning", "nexus-planning"),
        PLANNING_APPLICATION_VERSION,
    ),
    (("company.coding.v1", "v1", "nexus.coding", "nexus-coding"), CODING_APPLICATION_VERSION),
)


def application_version(registration: WorkflowRegistration) -> str:
    """Preserve other ABIs; reserved L/C names require their complete fixed tuple."""
    checked = WorkflowRegistration.model_validate_json(registration.model_dump_json())
    actual = (
        checked.workflow_name,
        checked.workflow_version,
        checked.queue_name,
        checked.application_name,
    )
    for expected, version in _MODEL_IDENTITIES:
        if actual == expected:
            return version
        if any(actual[index] == expected[index] for index in (0, 2, 3)):
            raise ValueError("Reserved model workflow deployment identity differs")
    return checked.workflow_version


def _require_binding(
    command: SegmentCommand,
    row: Mapping[str, object] | None,
    registration: WorkflowRegistration,
    version: str,
) -> None:
    if row is None or tuple(
        row.get(key)
        for key in (
            "name",
            "queue_name",
            "application_version",
            "application_name",
            "serialization",
        )
    ) != (
        registration.workflow_name,
        registration.queue_name,
        version,
        registration.application_name,
        "portable_json",
    ):
        raise ValueError("Model native DBOS workflow ABI or deployment binding differs")
    raw = row.get("inputs")
    if not isinstance(raw, str):
        raise ValueError("Model stored DBOS input is unavailable")
    if json.loads(raw) != {"positionalArgs": [command.model_dump_json()], "namedArgs": {}}:
        raise ValueError("Model actual DBOS input differs from its permanent command")


def require_current_model_binding(
    command: SegmentCommand,
    row: Mapping[str, object] | None,
    registration: WorkflowRegistration,
) -> None:
    """Only the new deployment tuple can describe current unissued model work."""
    _require_binding(command, row, registration, application_version(registration))


def require_issued_model_binding(
    command: SegmentCommand,
    row: Mapping[str, object] | None,
    registration: WorkflowRegistration,
    effect: EffectRecord,
    proposal_hash: str,
) -> None:
    """Read exact already-issued metadata, never a provider/lease/requeue permission.

    Native readers must also retain their actual action, hold and receipt checks.
    The effect is read from their same native transaction, not from a request DTO.
    """
    if type(effect) is not EffectRecord:
        raise ValueError("Legacy model workflow requires an issued native effect")
    effect = EffectRecord.model_validate_json(effect.model_dump_json())
    current = application_version(registration)
    if current not in {PLANNING_APPLICATION_VERSION, CODING_APPLICATION_VERSION} or (
        effect.company_id,
        effect.action_id,
        effect.task_id,
        effect.trace_id,
        effect.run_id,
        effect.attempt_kind,
        effect.proposal_hash,
    ) != (
        command.company_id,
        command.action_id,
        command.task_id,
        command.trace_id,
        command.run_id,
        "model_requests",
        proposal_hash,
    ):
        raise ValueError("Legacy model workflow lacks its original issued native binding")
    version = "v1" if row is not None and row.get("application_version") == "v1" else current
    _require_binding(command, row, registration, version)

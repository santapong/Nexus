"""Exact native DBOS input projection; supplied rows are not a queue or identity witness."""

import json

import pytest

from nexus.execution.planning_history import require_workflow_binding
from nexus.execution.planning_services import APPLICATION, QUEUE, VERSION, WORKFLOW
from nexus.tests.unit.test_planning_worker import command


@pytest.mark.parametrize(
    "fault", [None, "queue", "application", "version", "workflow", "format", "inputs"]
)
def test_only_exact_stored_planning_queue_input_is_metadata_bound(fault: str | None) -> None:
    selected = command()
    row: dict[str, object] = {
        "name": WORKFLOW,
        "queue_name": QUEUE,
        "application_version": VERSION,
        "application_name": APPLICATION,
        "serialization": "portable_json",
        "inputs": json.dumps({"positionalArgs": [selected.model_dump_json()], "namedArgs": {}}),
    }
    fields = {
        "queue": "queue_name",
        "application": "application_name",
        "version": "application_version",
        "workflow": "name",
        "format": "serialization",
        "inputs": "inputs",
    }
    if fault is not None:
        row[fields[fault]] = "foreign"
        with pytest.raises(ValueError):
            require_workflow_binding(selected, row)
    else:
        require_workflow_binding(selected, row)

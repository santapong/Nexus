"""Planning output is bounded content; server bindings supply every authority field."""

import json
from uuid import UUID

import pytest
from jsonschema.exceptions import ValidationError as SchemaValidationError

from nexus.company.management.planning_content import PlanningContent, planning_schema


def content() -> dict[str, object]:
    return {
        "tasks": [
            {
                "key": "investigate",
                "title": "Read the Nexus evidence",
                "description": "Identify the supported delivery gap.",
                "acceptance": ["Cite the exact source supporting the gap"],
                "depends_on": [],
                "evidence_ids": [str(UUID(int=1))],
            }
        ],
        "questions": [],
    }


def test_fixed_schema_and_strict_content_accept_only_content_fields() -> None:
    raw = json.dumps(content())
    validated = planning_schema().validate_output(raw)
    result = PlanningContent.model_validate_json(validated)
    assert result.tasks[0].key == "investigate"
    result.require_evidence((UUID(int=1),))
    assert set(PlanningContent.model_fields) == {"tasks", "questions"}


@pytest.mark.parametrize("field", ["actor_id", "tool", "workflow", "budget_usd", "approved"])
def test_model_cannot_supply_authority_fields(field: str) -> None:
    payload = content() | {field: "model-selected"}
    with pytest.raises(SchemaValidationError):
        planning_schema().validate_output(json.dumps(payload))


@pytest.mark.parametrize("field", ["actor_id", "tool", "workflow", "budget_usd", "approved"])
def test_task_cannot_supply_authority_fields(field: str) -> None:
    payload = content()
    tasks = payload["tasks"]
    assert isinstance(tasks, list)
    tasks[0][field] = "model-selected"
    with pytest.raises(ValueError):
        PlanningContent.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize("kind", ["duplicate", "self", "missing", "cycle"])
def test_dependency_graph_has_exact_distinct_keys(kind: str) -> None:
    payload = content()
    tasks = payload["tasks"]
    assert isinstance(tasks, list)
    second = tasks[0] | {"key": "publish", "depends_on": ["investigate"]}
    tasks.append(second)
    if kind == "duplicate":
        second["key"] = "investigate"
    elif kind == "self":
        second["depends_on"] = ["publish"]
    elif kind == "missing":
        second["depends_on"] = ["unknown"]
    else:
        tasks[0]["depends_on"] = ["publish"]
    with pytest.raises(ValueError):
        PlanningContent.model_validate_json(json.dumps(payload))


def test_evidence_must_be_in_the_actual_context() -> None:
    result = PlanningContent.model_validate_json(json.dumps(content()))
    with pytest.raises(ValueError):
        result.require_evidence((UUID(int=2),))


@pytest.mark.parametrize("value", ["x" * 257, "ก" * 100, " "])
def test_title_limit_counts_utf8_bytes_and_rejects_blank(value: str) -> None:
    payload = content()
    tasks = payload["tasks"]
    assert isinstance(tasks, list)
    tasks[0]["title"] = value
    with pytest.raises(ValueError):
        PlanningContent.model_validate_json(json.dumps(payload))


def test_total_content_bytes_are_bounded_even_when_individual_fields_fit() -> None:
    payload = content()
    tasks = payload["tasks"]
    assert isinstance(tasks, list)
    tasks[:] = [
        tasks[0] | {"key": f"task-{index}", "description": "x" * 4096} for index in range(16)
    ]
    with pytest.raises(ValueError):
        PlanningContent.model_validate_json(json.dumps(payload))


def test_required_empty_arrays_are_not_silently_defaulted() -> None:
    payload = content()
    del payload["questions"]
    with pytest.raises(SchemaValidationError):
        planning_schema().validate_output(json.dumps(payload))

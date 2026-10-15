"""Neutral choice wire compatibility only; no actual plan admission or owner authority."""

import ast
import json
from pathlib import Path
from typing import Literal, cast
from uuid import UUID

import pytest
from pydantic import Field, ValidationError

from nexus.company.management.base import ValueContract
from nexus.company.management.canonical import canonical_json, canonical_sha256
from nexus.company.management.plan_choice_contracts import StrategySelectionRef
from nexus.company.strategy.contracts import StrategySelectionRef as ExistingSelectionRef

GOLDEN = (
    '{"schema_version":"nexus.company.management.v1",'
    '"company_id":"00000000-0000-0000-0000-000000000001",'
    '"brief":{"schema_version":"nexus.company.brain.v1",'
    '"company_id":"00000000-0000-0000-0000-000000000001",'
    '"artifact_id":"00000000-0000-0000-0000-000000000002",'
    '"artifact_revision_id":"00000000-0000-0000-0000-000000000003",'
    '"revision":"brief-v1","sha256":"' + "a" * 64 + '","byte_length":7},'
    '"acceptance_id":"00000000-0000-0000-0000-000000000004",'
    '"candidate_id":"csv-change.v1","candidate_scope_sha256":"' + "b" * 64 + '"}'
)


def test_existing_and_neutral_choice_preserve_exact_wire_schema_and_digest() -> None:
    old = ExistingSelectionRef.model_validate_json(GOLDEN)
    new = StrategySelectionRef.model_validate_json(GOLDEN)
    assert old.model_dump_json() == new.model_dump_json() == GOLDEN
    assert old.model_dump() == new.model_dump()
    assert canonical_json(old) == canonical_json(new)
    assert canonical_sha256(old) == canonical_sha256(new)
    assert ExistingSelectionRef.model_json_schema() == StrategySelectionRef.model_json_schema()
    assert StrategySelectionRef.model_validate(old.model_dump()).model_dump_json() == GOLDEN
    assert ExistingSelectionRef.model_validate(new.model_dump()).model_dump_json() == GOLDEN


@pytest.mark.parametrize(
    "case",
    [
        "company",
        "hash",
        "candidate",
        "candidate_long",
        "extra",
        "missing",
        "uuid",
        "boolean_count",
        "string_count",
        "zero_count",
        "overbound_count",
        "nested_extra",
    ],
)
def test_neutral_choice_keeps_existing_validation_denials(case: str) -> None:
    raw = cast(dict[str, object], json.loads(GOLDEN))
    brief = cast(dict[str, object], raw["brief"])
    if case == "company":
        brief["company_id"] = str(UUID(int=9))
    elif case == "hash":
        raw["candidate_scope_sha256"] = "B" * 64
    elif case == "candidate":
        raw["candidate_id"] = "unbounded choice"
    elif case == "candidate_long":
        raw["candidate_id"] = "x" * 129
    elif case == "extra":
        raw["approved"] = True
    elif case == "missing":
        del raw["acceptance_id"]
    elif case == "uuid":
        raw["acceptance_id"] = 4
    elif case == "nested_extra":
        brief["read_allowed"] = True
    else:
        brief["byte_length"] = {
            "boolean_count": True,
            "string_count": "7",
            "zero_count": 0,
            "overbound_count": 2_097_153,
        }[case]
    wire = json.dumps(raw)
    with pytest.raises(ValidationError) as old_error:
        ExistingSelectionRef.model_validate_json(wire)
    with pytest.raises(ValidationError) as new_error:
        StrategySelectionRef.model_validate_json(wire)
    assert [(r["type"], r["loc"]) for r in new_error.value.errors()] == [
        (r["type"], r["loc"]) for r in old_error.value.errors()
    ]


def test_neutral_choice_is_frozen_and_contains_only_original_description_fields() -> None:
    value = StrategySelectionRef.model_validate_json(GOLDEN)
    assert tuple(StrategySelectionRef.model_fields) == tuple(ExistingSelectionRef.model_fields)
    assert set(StrategySelectionRef.model_fields) == {
        "schema_version",
        "company_id",
        "brief",
        "acceptance_id",
        "candidate_id",
        "candidate_scope_sha256",
    }
    field_name = "candidate_id"  # Check the runtime guard independently of static read-only typing.
    with pytest.raises(ValidationError, match="frozen_instance"):
        setattr(value, field_name, "other")


def test_neutral_module_imports_no_strategy_plan_acceptance_or_runtime_modules() -> None:
    import nexus.company.management.plan_choice_contracts as module

    assert module.__file__ is not None
    tree = ast.parse(Path(module.__file__).read_text())
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert imports == {
        "typing",
        "uuid",
        "pydantic",
        "nexus.company.brain.sources",
        "nexus.company.management.base",
    }
    assert not any(isinstance(node, ast.Import) for node in ast.walk(tree))


class _LegacyCarrier(ValueContract):
    """Local stand-in for a previously wire-stable ordinary payload; never a real plan."""

    kind: Literal["ordinary"] = "ordinary"


class _ProposedChoiceCarrier(_LegacyCarrier):
    """Unit-only proposal; production PlanPayload and strategy reexport stay unchanged."""

    strategy_selection: StrategySelectionRef | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


def test_local_none_exclusion_proposal_preserves_ordinary_wire_and_hash() -> None:
    old = _LegacyCarrier()
    for value in (_ProposedChoiceCarrier(), _ProposedChoiceCarrier(strategy_selection=None)):
        assert value.model_dump_json() == old.model_dump_json() == '{"kind":"ordinary"}'
        assert canonical_sha256(value) == canonical_sha256(old)
        assert _ProposedChoiceCarrier.model_validate_json(value.model_dump_json()) == value


def test_local_alias_and_present_choice_bind_descriptive_bytes_only() -> None:
    # A local alias demonstrates the proposed import spelling, not an installed reexport.
    from nexus.company.management.plan_choice_contracts import (
        StrategySelectionRef as ProposedReexport,
    )

    assert ProposedReexport is StrategySelectionRef
    selection = ProposedReexport.model_validate_json(GOLDEN)
    value = _ProposedChoiceCarrier(strategy_selection=selection)
    assert value.model_dump_json() == '{"kind":"ordinary","strategy_selection":' + GOLDEN + "}"
    assert canonical_sha256(value) != canonical_sha256(_LegacyCarrier())
    assert _ProposedChoiceCarrier.model_validate_json(value.model_dump_json()) == value

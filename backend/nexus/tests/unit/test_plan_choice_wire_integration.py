"""Real PlanPayload optional choice preserves legacy wire; no authority or plan activation."""

import hashlib
import json
from uuid import UUID

import pytest
from pydantic import ValidationError

from nexus.company.management.canonical import _value, canonical_sha256
from nexus.company.management.plan_choice_contracts import StrategySelectionRef
from nexus.company.management.plans import PlanPayload
from nexus.company.strategy.contracts import StrategySelectionRef as ExportedSelection
from nexus.tests.unit.cycle_admission_fixture import cycle


def selection(company: UUID | None = None) -> StrategySelectionRef:
    company = UUID(int=1) if company is None else company
    return StrategySelectionRef.model_validate(
        {
            "company_id": company,
            "brief": {
                "company_id": company,
                "artifact_id": UUID(int=40),
                "artifact_revision_id": UUID(int=41),
                "revision": "v1",
                "sha256": "a" * 64,
                "byte_length": 10,
            },
            "acceptance_id": UUID(int=42),
            "candidate_id": "csv-change",
            "candidate_scope_sha256": "b" * 64,
        }
    )


def test_actual_strategy_import_reexports_the_neutral_class() -> None:
    assert ExportedSelection is StrategySelectionRef


def test_absent_and_explicit_none_preserve_old_plan_wire_and_hash() -> None:
    original = cycle().strategy
    old = original.model_dump(mode="json", exclude={"strategy_selection"})
    old_typed = original.model_dump(exclude={"strategy_selection"})
    absent = PlanPayload.model_validate_json(json.dumps(old))
    explicit = PlanPayload.model_validate_json(json.dumps(old | {"strategy_selection": None}))
    assert absent.model_dump(mode="json") == explicit.model_dump(mode="json") == old
    legacy_wire = json.dumps(
        {"recipe": "management-canonical-v1", "payload": _value(old_typed)},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    assert (
        canonical_sha256(absent)
        == canonical_sha256(explicit)
        == hashlib.sha256(legacy_wire).hexdigest()
    )
    assert absent.strategy_selection is None


def test_full_plan_choice_is_typed_and_part_of_the_exact_payload_hash() -> None:
    original = cycle().full
    chosen = PlanPayload.model_validate(original.model_dump() | {"strategy_selection": selection()})
    assert chosen.strategy_selection == selection()
    assert canonical_sha256(chosen) != canonical_sha256(original)
    assert PlanPayload.model_validate_json(chosen.model_dump_json()) == chosen


def test_foreign_company_choice_fails_the_actual_plan_boundary() -> None:
    with pytest.raises(ValidationError):
        PlanPayload.model_validate(
            cycle().full.model_dump() | {"strategy_selection": selection(UUID(int=2))}
        )

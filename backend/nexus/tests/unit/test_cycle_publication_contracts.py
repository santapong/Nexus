"""Pure fixed-policy/compiler checks; no live reader or accepted native E is supplied."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from nexus.company.cycle_artifacts.common import CycleKind
from nexus.company.cycle_artifacts.publication_contracts import (
    CycleArtifactRule,
    prepare_cycle_check,
)
from nexus.company.management.acceptance_errors import AcceptanceDeniedError
from nexus.tests.unit.cycle_publication_row_fixture import row_case


@pytest.mark.parametrize("kind", ["presentation", "support"])
def test_exact_two_parts_and_full_check_bytes(kind: CycleKind) -> None:
    row = row_case(kind)
    assert row.write_rule.parts == ("json", "html" if kind == "presentation" else "markdown")
    assert row.check_rule.parts == ("check",)
    checked = prepare_cycle_check(row.case.command(), uuid4(), "internal")
    assert checked.artifact.byte_length == len(checked.raw_bytes)
    assert checked.artifact.sha256 == checked.output_sha256
    assert checked.raw_bytes.endswith(b"}")
    assert checked.command.target.artifacts == tuple(
        part.artifact for part in row.prepared.manifest.parts
    )
    assert checked.artifact.sha256 != checked.command.target.proposal_sha256


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_bytes", True),
        ("origin_kind", "direct"),
        ("data_classification", "public"),
        ("source_symbol", "generated.support-json.v1"),
        ("media_type", "text/plain"),
    ],
)
def test_copied_policy_cannot_bypass_fixed_rule(field: str, value: object) -> None:
    row = row_case()
    policies = (
        row.write_rule.policies[0].model_copy(update={field: value}),
        row.write_rule.policies[1],
    )
    with pytest.raises((AcceptanceDeniedError, ValidationError)):
        CycleArtifactRule(**row.write_rule.model_dump(exclude={"policies"}), policies=policies)


def test_check_recomputes_full_bytes_and_disallows_author_action_alias() -> None:
    row = row_case()
    checked = prepare_cycle_check(row.case.command(), uuid4(), "internal")
    with pytest.raises((AcceptanceDeniedError, ValidationError)):
        prepare_cycle_check(row.case.command(), row.case.action_id, "internal")
    for changed in (
        {"raw_bytes": checked.raw_bytes + b" "},
        {"artifact": checked.artifact.model_copy(update={"sha256": "f" * 64})},
    ):
        with pytest.raises((AcceptanceDeniedError, ValidationError)):
            type(checked).model_validate({**checked.model_dump(), **changed})


def test_registered_check_cap_is_required_before_intent() -> None:
    from nexus.company.cycle_artifacts.publication_contracts import prepare_registered_cycle_check

    row = row_case("support")
    limited = row.check_rule.model_copy(
        update={"policies": (row.check_rule.policy("check").model_copy(update={"max_bytes": 1}),)}
    )
    with pytest.raises(AcceptanceDeniedError):
        prepare_registered_cycle_check(row.case.command(), uuid4(), limited)


@pytest.mark.parametrize("part", [0, 1])
def test_registered_author_caps_cover_both_outputs(part: int) -> None:
    from nexus.company.cycle_artifacts.publication_contracts import require_author_output_bounds

    row = row_case()
    policies = list(row.write_rule.policies)
    policies[part] = policies[part].model_copy(update={"max_bytes": 1})
    limited = row.write_rule.model_copy(update={"policies": tuple(policies)})
    with pytest.raises(AcceptanceDeniedError):
        require_author_output_bounds(row.prepared, limited)

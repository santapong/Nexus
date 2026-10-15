"""Exact candidate descriptions never establish a signed current owner choice."""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from nexus.company.management.acceptance import ProtectedCheckProof, WorkAcceptance
from nexus.company.management.canonical import canonical_sha256
from nexus.company.strategy.contracts import STRATEGY_LIMITATIONS
from nexus.company.strategy.owner_selection import describe_strategy_selection
from nexus.tests.unit.strategy_brief_fixture import strategy_case


def accepted() -> WorkAcceptance:
    target = strategy_case().command.target
    return WorkAcceptance(
        company_id=target.company_id,
        acceptance_id=UUID(int=770),
        target=target,
        verdict="pass",
        proofs=(
            ProtectedCheckProof(
                company_id=target.company_id,
                proof_id=UUID(int=771),
                recipe=target.check_recipe,
                result_artifact=target.artifacts[0],
                target_sha256=canonical_sha256(target),
            ),
        ),
        limitations=STRATEGY_LIMITATIONS,
        recorded_at=datetime.now(UTC),
    )


@pytest.mark.parametrize("index", [0, 1])
def test_reviewed_change_and_defer_remain_distinct_descriptions(index: int) -> None:
    brief = strategy_case().brief
    candidate = brief.candidates[index]
    result = describe_strategy_selection(brief, accepted(), candidate.scope.candidate_id)
    assert result.candidate_scope_sha256 == canonical_sha256(candidate.scope)
    assert result.brief == accepted().target.artifacts[0]
    assert not hasattr(result, "approved") and not hasattr(result, "owner_id")


@pytest.mark.parametrize(
    "change", ["unknown_candidate", "changed_brief", "wrong_output", "not_pass", "wrong_recipe"]
)
def test_unaccepted_or_spliced_original_material_cannot_describe_owner_selection(
    change: str,
) -> None:
    brief, record = strategy_case().brief, accepted()
    candidate_id = brief.candidates[0].scope.candidate_id
    if change == "unknown_candidate":
        candidate_id = "unreviewed-new-action"
    elif change == "changed_brief":
        brief = brief.model_copy(
            update={"unknowns": (brief.unknowns[0].model_copy(update={"text": "changed"}),)}
        )
    elif change == "wrong_output":
        target = record.target.model_copy(
            update={
                "artifacts": (record.target.artifacts[0].model_copy(update={"sha256": "b" * 64}),)
            }
        )
        record = record.model_copy(
            update={
                "target": target,
                "proofs": tuple(
                    p.model_copy(update={"target_sha256": canonical_sha256(target)})
                    for p in record.proofs
                ),
            }
        )
    elif change == "not_pass":
        record = record.model_copy(update={"verdict": "reject"})
    else:
        target = record.target.model_copy(update={"check_recipe": "economic-merit-v1"})
        record = record.model_copy(
            update={
                "target": target,
                "proofs": tuple(
                    p.model_copy(
                        update={
                            "recipe": target.check_recipe,
                            "target_sha256": canonical_sha256(target),
                        }
                    )
                    for p in record.proofs
                ),
            }
        )
    with pytest.raises(ValueError):
        describe_strategy_selection(brief, record, candidate_id)

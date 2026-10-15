"""Pure publication descriptions cannot authorize rows or a second tool attempt."""

from uuid import UUID

import pytest

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.strategy.publication_contracts import PreparedStrategyPublication
from nexus.company.strategy.publication_identity import (
    prepare_strategy_publication,
    strategy_bundle_derivation_id,
)
from nexus.tests.unit.strategy_producer_fixture import producer_case


def test_bundle_brief_and_original_manifest_have_distinct_stable_identities() -> None:
    snapshot, policy = producer_case()
    target = ResourceRef(company_id=snapshot.company_id, resource_id=UUID(int=500))
    value = prepare_strategy_publication(snapshot, policy, UUID(int=501), target)
    assert value.compiled.prepared.inputs == snapshot.inputs
    assert value.original.snapshot == snapshot and value.original.policy == policy
    assert value.compiled.original_bundle.resource == target
    assert value.compiled.original_bundle.artifact != value.brief
    assert (
        strategy_bundle_derivation_id(snapshot.company_id, UUID(int=501)) != value.brief.artifact_id
    )
    assert prepare_strategy_publication(snapshot, policy, UUID(int=501), target) == value


@pytest.mark.parametrize("field", ["bundle_bytes", "action_id", "brief"])
def test_publication_description_cannot_splice_its_exact_material(field: str) -> None:
    snapshot, policy = producer_case()
    target = ResourceRef(company_id=snapshot.company_id, resource_id=UUID(int=500))
    value = prepare_strategy_publication(snapshot, policy, UUID(int=501), target)
    changes: dict[str, object] = {
        "bundle_bytes": b"{}",
        "action_id": UUID(int=502),
        "brief": value.brief.model_copy(update={"sha256": "0" * 64}),
    }
    with pytest.raises(ValueError):
        PreparedStrategyPublication.model_validate(
            value.model_copy(update={field: changes[field]}).model_dump(warnings=False)
        )


def test_foreign_bundle_target_is_rejected_before_description_creation() -> None:
    snapshot, policy = producer_case()
    with pytest.raises(ValueError):
        prepare_strategy_publication(
            snapshot,
            policy,
            UUID(int=501),
            ResourceRef(company_id=UUID(int=999), resource_id=UUID(int=500)),
        )

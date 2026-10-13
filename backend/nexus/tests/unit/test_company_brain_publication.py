"""Knowledge write commands cannot carry model acceptance, native roles or mutable budgets."""

from uuid import UUID

import pytest
from pydantic import ValidationError

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.base import SourceTime
from nexus.company.brain.ontology import ProductContent
from nexus.company.brain.publication_contracts import (
    ClaimDraft,
    ClaimPublication,
    EntityPublication,
)
from nexus.company.brain.sources import EvidenceRef


def draft(**changes: object) -> ClaimDraft:
    return ClaimDraft.model_validate(
        {
            "company_id": UUID(int=1),
            "claim_id": UUID(int=2),
            "kind": "hypothesis",
            "text": "A bounded proposed hypothesis",
            "source_event": SourceTime(precision="unknown", value=None, basis="operator"),
        }
        | changes
    )


@pytest.mark.parametrize(
    "extra",
    [
        {"origin": "source"},
        {"status": "source_report"},
        {"verification_id": UUID(int=9)},
        {"kind": "verified_outcome"},
        {"kind": "observation"},
    ],
)
def test_draft_never_accepts_promotion_or_unsupported_observation(extra: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        draft(**extra)


def test_same_company_resource_and_evidence_are_structural_prerequisites() -> None:
    with pytest.raises(ValidationError):
        draft(evidence=(EvidenceRef(company_id=UUID(int=9), evidence_id=UUID(int=5)),))
    with pytest.raises(ValidationError):
        ClaimPublication(
            company_id=UUID(int=1),
            resource=ResourceRef(company_id=UUID(int=9), resource_id=UUID(int=4)),
            draft=draft(),
            revision="r1",
        )


def test_entity_native_content_is_closed_and_contains_no_acceptance_fields() -> None:
    with pytest.raises(ValidationError):
        EntityPublication.model_validate(
            {
                "company_id": UUID(int=1),
                "entity_id": UUID(int=2),
                "resource": ResourceRef(company_id=UUID(int=1), resource_id=UUID(int=3)),
                "content": ProductContent(label="Product"),
                "revision": "r1",
                "source_event": SourceTime(precision="unknown", value=None, basis="operator"),
                "status": "completed",
            }
        )

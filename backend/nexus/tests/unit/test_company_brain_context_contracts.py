"""Context byte manifests cannot qualify model tokens or downgrade protected sources."""

from __future__ import annotations

import hashlib
from uuid import UUID

import pytest
from pydantic import ValidationError

from nexus.company.brain.access_contracts import ResourceGeneration
from nexus.company.brain.context import (
    AssembledContext,
    ContextAuthorityState,
    ContextInclusion,
    ContextManifest,
)
from nexus.company.brain.retrieval import CitationHandle, MaterializedEvidence
from nexus.company.brain.sources import ParseFailureRecord, SourceHead
from nexus.tests.unit.test_company_brain_evidence_contracts import (
    COMPANY,
    NOW,
    RAW,
    SOURCE,
    TEXT,
    evidence,
)


def manifest() -> ContextManifest:
    item = evidence()
    resource = ResourceGeneration(company_id=COMPANY, resource_id=SOURCE, generation=1)
    handle = CitationHandle(
        company_id=COMPANY,
        evidence_id=item.evidence_id,
        record=item,
        source_contributors=(item.source,),
        source_heads=(
            SourceHead(
                company_id=COMPANY,
                source_id=SOURCE,
                current=item.source,
                generation=1,
                observed_at=NOW,
                availability="available",
            ),
        ),
        contributors=(resource,),
    )
    authority = ContextAuthorityState(
        company_id=COMPANY,
        mandate_version="mandate-1",
        policy_version="policy-1",
        budget_version="budget-1",
        role_system_text="Server policy",
        data_classification="internal",
    )
    return ContextManifest(
        company_id=COMPANY,
        context_id=UUID(int=50),
        principal_id=UUID(int=51),
        operation_id=UUID(int=52),
        trace_id=UUID(int=53),
        authority=authority,
        policy_version="context-policy-1",
        retrieval_recipe="brain-retrieval-v1",
        render_recipe="brain-render-v1",
        inclusions=(
            ContextInclusion(
                company_id=COMPANY,
                handle=handle,
                data_classification="confidential",
                purpose="evidence",
                disposition="included",
                included_bytes=len(RAW),
            ),
        ),
        contributors=(resource,),
        data_classification="confidential",
        materialized_bytes=len(RAW),
        prompt_bytes=len(b"Server policy\n" + RAW),
        prompt_sha256=hashlib.sha256(b"Server policy\n" + RAW).hexdigest(),
    )


def test_context_exact_prompt_hash_retains_qualification_unavailable() -> None:
    context = AssembledContext(
        company_id=COMPANY, manifest=manifest(), system_text="Server policy", input_text=TEXT
    )
    assert context.manifest.token_qualification == "unavailable"
    assert context.manifest.qualified_input_tokens is None


@pytest.mark.parametrize(
    "update",
    [
        {"data_classification": "internal"},
        {"token_qualification": "qualified"},
        {"qualified_input_tokens": 10},
        {"token_qualification": "qualified", "qualified_input_tokens": 10},
    ],
)
def test_context_cannot_downgrade_or_self_qualify_without_exact_recipe(
    update: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        ContextManifest.model_validate(manifest().model_dump() | update)


def test_changed_rendered_text_cannot_reuse_manifest_hash() -> None:
    with pytest.raises(ValidationError):
        AssembledContext(
            company_id=COMPANY,
            manifest=manifest(),
            system_text="Server policy",
            input_text="Changed text",
        )


def test_materialized_raw_span_cannot_swap_text_or_omit_provenance() -> None:
    item = evidence()
    base = {
        "company_id": COMPANY,
        "record": item,
        "text": TEXT,
        "source_state": "current",
        "freshness": "unknown",
        "data_classification": "confidential",
        "authority_profile": "fixture.primary-v1",
        "source_symbol": "fixture.local",
        "external_key": "fixture/source-1",
        "source_contributors": (item.source,),
        "contributors": (ResourceGeneration(company_id=COMPANY, resource_id=SOURCE, generation=1),),
    }
    assert MaterializedEvidence.model_validate(base).text == TEXT
    for update in ({"text": "wrong bytes"}, {"source_contributors": ()}):
        with pytest.raises(ValidationError):
            MaterializedEvidence.model_validate(base | update)


def test_parse_failure_diagnostics_are_closed_and_never_free_exception_text() -> None:
    values = {
        "company_id": COMPANY,
        "failure_id": UUID(int=99),
        "source": evidence().source,
        "parser_version": "utf8-identity-v1",
        "chunker_version": "utf8-sections-v1",
        "recorded_at": NOW,
    }
    assert (
        ParseFailureRecord.model_validate(values | {"reason_code": "parse_timeout"}).reason_code
        == "parse_timeout"
    )
    with pytest.raises(ValidationError):
        ParseFailureRecord.model_validate(values | {"reason_code": "private path/key/error text"})

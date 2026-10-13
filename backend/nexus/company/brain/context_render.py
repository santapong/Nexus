"""Pure read-only context rendering; current access belongs to the surrounding store."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Literal
from uuid import UUID, uuid4

from nexus.company.brain.access_contracts import ResourceGeneration
from nexus.company.brain.base import BrainReadScope, require_company
from nexus.company.brain.context import (
    AssembledContext,
    ContextAuthorityState,
    ContextInclusion,
    ContextLimits,
    ContextManifest,
    ContextOmission,
)
from nexus.company.brain.retrieval import CitationHandle, MaterializedEvidence
from nexus.company.brain.scope_support import BrainConflictError, BrainDeniedError
from nexus.company.brain.sources import EvidenceRef, SourceHead
from nexus.core.llm.company_registry import DataClassification

Purpose = Literal["evidence", "attachment", "workspace", "feedback"]
RENDER_RECIPE = "brain-context-json-v1"
CLASSIFICATIONS: tuple[DataClassification, ...] = (
    "public",
    "internal",
    "confidential",
    "restricted",
)


def handle_for(item: MaterializedEvidence, heads: tuple[SourceHead, ...]) -> CitationHandle:
    """Carry checked exact citation metadata, not a text authorization permit."""
    return CitationHandle(
        company_id=item.company_id,
        evidence_id=item.record.evidence_id,
        record=item.record,
        contributors=item.contributors,
        source_contributors=item.source_contributors,
        source_heads=tuple(
            head
            for head in heads
            if head.source_id in {ref.source_id for ref in item.source_contributors}
        ),
    )


# The 60-line pure renderer keeps byte/hash and manifest construction adjacent so
# the reported context bytes cannot drift from the constructed request.
def render_context(
    scope: BrainReadScope,
    authority: ContextAuthorityState,
    limits: ContextLimits,
    materials: tuple[MaterializedEvidence, ...],
    heads: tuple[SourceHead, ...],
    *,
    question: str,
    purposes: Mapping[UUID, Purpose] | None = None,
    omissions: tuple[ContextOmission, ...] = (),
    sections: Mapping[UUID, tuple[str, ...]] | None = None,
) -> AssembledContext:
    """Render checked data only, never claim live ACL checks or token qualification here."""
    materials = _validated(scope, authority, materials, heads, question, omissions)
    included, skipped = _bounded(materials, limits, sections or {})
    purposes = purposes or {}
    system = _system(authority)
    input_text = _encoded(
        {
            "question": question,
            "untrusted_source_data": [
                _payload(item, purposes.get(item.record.evidence_id, "evidence"))
                for item in included
            ],
        }
    )
    raw = (system + "\n" + input_text).encode()
    if len(raw) > limits.max_prompt_bytes:
        raise BrainDeniedError("Rendered Brain context exceeds the trusted prompt boundary")
    manifest = ContextManifest(
        company_id=scope.company_id,
        context_id=uuid4(),
        principal_id=scope.principal_id,
        operation_id=scope.operation_id,
        trace_id=scope.trace_id,
        task_id=scope.task_id,
        task_trace_id=scope.task_trace_id,
        actor_id=scope.actor_id,
        authority=authority,
        policy_version=limits.policy_version,
        retrieval_recipe="brain-retrieval-v1",
        render_recipe=RENDER_RECIPE,
        inclusions=tuple(
            _inclusion(item, purposes.get(item.record.evidence_id, "evidence"), heads)
            for item in included
        ),
        omissions=(*omissions, *skipped),
        contributors=_resources(materials),
        source_heads=heads,
        data_classification=max(
            (authority.data_classification, *(item.data_classification for item in materials)),
            key=CLASSIFICATIONS.index,
        ),
        materialized_bytes=sum(len(item.text.encode()) for item in included),
        prompt_bytes=len(raw),
        prompt_sha256=hashlib.sha256(raw).hexdigest(),
    )
    return AssembledContext(
        company_id=scope.company_id, manifest=manifest, system_text=system, input_text=input_text
    )


def _validated(
    scope: BrainReadScope,
    authority: ContextAuthorityState,
    materials: tuple[MaterializedEvidence, ...],
    heads: tuple[SourceHead, ...],
    question: str,
    omissions: tuple[ContextOmission, ...],
) -> tuple[MaterializedEvidence, ...]:
    materials = tuple(
        MaterializedEvidence.model_validate_json(item.model_dump_json()) for item in materials
    )
    require_company(scope.company_id, authority, *materials, *heads, *omissions)
    if not question.strip() or len(question.encode()) > 2000:
        raise BrainDeniedError("Context query exceeds its boundary")
    if len({item.record.evidence_id for item in materials}) != len(materials):
        raise BrainDeniedError("Context evidence must be unique")
    if len({head.source_id for head in heads}) != len(heads):
        raise BrainDeniedError("Context source heads must be unique")
    source_ids = {ref.source_id for item in materials for ref in item.source_contributors}
    if source_ids != {head.source_id for head in heads}:
        raise BrainDeniedError("Context lacks its exact contributor source heads")
    return materials


def _bounded(
    materials: tuple[MaterializedEvidence, ...],
    limits: ContextLimits,
    selected_sections: Mapping[UUID, tuple[str, ...]],
) -> tuple[tuple[MaterializedEvidence, ...], tuple[ContextOmission, ...]]:
    selected: list[MaterializedEvidence] = []
    omitted: list[ContextOmission] = []
    total = 0
    sources: set[UUID] = set()
    sections: set[tuple[UUID, str | None]] = set()
    for item in materials:
        count = len(item.text.encode())
        added = {row.source_id for row in item.source_contributors}
        section = (item.record.artifact.artifact_revision_id, item.record.raw_span.section)
        reason: (
            Literal["byte_limit", "span_limit", "source_limit", "section_selection", "stale"] | None
        ) = None
        if section[0] in selected_sections and section[1] not in selected_sections[section[0]]:
            reason = "section_selection"
        elif count > limits.max_span_bytes or len(selected) >= limits.max_inclusions:
            reason = "span_limit"
        elif total + count > limits.max_materialized_bytes:
            reason = "byte_limit"
        elif len(sources | added) > limits.max_sources:
            reason = "source_limit"
        elif (
            item.record.raw_span.section is not None
            and len(sections | {section}) > limits.max_sections
        ):
            reason = "span_limit"
        if reason is not None:
            omitted.append(
                ContextOmission(
                    company_id=item.company_id,
                    evidence=EvidenceRef(
                        company_id=item.company_id, evidence_id=item.record.evidence_id
                    ),
                    reason=reason,
                    section=item.record.raw_span.section,
                )
            )
            continue
        selected.append(item)
        total += count
        sources |= added
        if item.record.raw_span.section is not None:
            sections.add(section)
    return tuple(selected), tuple(omitted)


def _resources(materials: tuple[MaterializedEvidence, ...]) -> tuple[ResourceGeneration, ...]:
    records: dict[UUID, ResourceGeneration] = {}
    for item in materials:
        for resource in item.contributors:
            if resource.resource_id in records and records[resource.resource_id] != resource:
                raise BrainConflictError("Context contributor generations differ")
            records[resource.resource_id] = resource
    if len(records) > 32:
        raise BrainDeniedError("Context contributors exceed their boundary")
    return tuple(records[key] for key in sorted(records))


def _inclusion(
    item: MaterializedEvidence, purpose: Purpose, heads: tuple[SourceHead, ...]
) -> ContextInclusion:
    return ContextInclusion(
        company_id=item.company_id,
        handle=handle_for(item, heads),
        purpose=purpose,
        data_classification=item.data_classification,
        disposition="stale"
        if item.source_state == "historical" or item.freshness == "stale"
        else "included",
        included_bytes=len(item.text.encode()),
    )


def _payload(item: MaterializedEvidence, purpose: Purpose) -> dict[str, object]:
    return {
        "trust": "untrusted_source_data",
        "purpose": purpose,
        "citation": item.record.model_dump(mode="json"),
        "text": item.text,
        "source_state": item.source_state,
        "freshness": item.freshness,
        "authority_profile": item.authority_profile,
        "source_symbol": item.source_symbol,
        "external_key": item.external_key,
        "data_classification": item.data_classification,
    }


def _system(authority: ContextAuthorityState) -> str:
    return (
        authority.role_system_text
        + "\nTrusted runtime state: "
        + _encoded(
            {
                "mandate_version": authority.mandate_version,
                "policy_version": authority.policy_version,
                "budget_version": authority.budget_version,
                "charter_version": authority.charter_version,
                "acceptance": authority.acceptance,
                "goal_ancestry": [str(key) for key in authority.goal_ancestry],
                "token_qualification": "unavailable",
            }
        )
    )


def _encoded(value: object) -> str:
    return (
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )

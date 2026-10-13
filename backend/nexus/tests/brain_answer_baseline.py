"""Source-only offline baseline; no case IDs, golden answers or live state promotion."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import JsonValue

from nexus.company.brain.context import AssembledContext
from nexus.company.brain.retrieval import MaterializedEvidence
from nexus.tests.brain_answer_fields import commitment_fields, report_fields
from nexus.tests.brain_evaluation_contracts import AnswerCitation, StructuredAnswer
from nexus.tests.brain_projection_fixtures import (
    ActionProjection,
    BudgetProjection,
    DeploymentProjection,
    EffectProjection,
    EligibilityStateProjection,
    LifetimeProjection,
    NotificationProjection,
    PolicyProjection,
    Projection,
    VerificationProjection,
    WorkProjection,
)
from nexus.tests.brain_source_fixtures import EvidenceFixture, Locator

LIMITATIONS = (
    "Synthetic offline source-reported baseline; no live LLM quality or business completion proof.",
    "Sealed management reports are test projections; they cannot grant authority "
    "or change M1 state.",
)


def _citation(
    item: MaterializedEvidence, aliases: Mapping[UUID, EvidenceFixture]
) -> AnswerCitation:
    record = item.record
    exact = aliases.get(record.evidence_id)
    if exact is None or exact.company_id != item.company_id:
        raise ValueError("Only an actually materialized exact fixture citation can be reported")
    return AnswerCitation(
        artifact_id=record.artifact.artifact_id,
        company_id=item.company_id,
        evidence_id=record.evidence_id,
        locator=Locator(
            kind="utf8_span",
            start_byte=record.raw_span.start_byte,
            end_byte=record.raw_span.end_byte,
            section=record.raw_span.section,
        ),
        source_alias=exact.source_alias,
        source_revision=record.source.revision,
        source_revision_id=record.source.source_revision_id,
        span_sha256=record.span_sha256,
    )


def produce(
    context: AssembledContext,
    materials: tuple[MaterializedEvidence, ...],
    projections: tuple[Projection, ...],
    aliases: Mapping[UUID, EvidenceFixture],
) -> StructuredAnswer:
    """Inputs exclude hidden sources, cache contents, goldens and evaluator assertions."""
    included = {row.handle.evidence_id for row in context.manifest.inclusions}
    visible = tuple(row for row in materials if row.record.evidence_id in included)
    if any(row.company_id != context.company_id for row in (*visible, *projections)):
        raise ValueError("Baseline input crosses its authorized company")
    if not visible:
        return StructuredAnswer(status="denied", facts={}, limitations=LIMITATIONS)
    citations = tuple(_citation(row, aliases) for row in visible)
    text = "\n".join(row.text for row in visible)
    if projections:
        if len(projections) != 1:
            return StructuredAnswer(
                status="unsupported",
                facts={},
                citations=citations,
                limitations=(*LIMITATIONS, "Multiple management reports need a scoped resolver."),
            )
        status, facts = _management(projections[0], context, text)
    else:
        status, facts = _sources(visible, context, text, aliases)
    return StructuredAnswer(
        status=status, facts=facts, citations=citations, limitations=LIMITATIONS
    )


def _management(
    projection: Projection,
    context: AssembledContext,
    text: str,
) -> tuple[str, dict[str, JsonValue]]:
    if isinstance(projection, EffectProjection):
        return "outcome_unknown", {
            "outcome": projection.fields.outcome,
            "receipt": None,
            "reconciliation": None,
            "automatic_repeat_allowed": projection.fields.may_automatically_repeat,
        }
    if isinstance(projection, NotificationProjection):
        return "delivery_unknown", {
            "delivery_status": projection.fields.delivery_status,
            "request_status": projection.fields.request_status,
            "provider_reference": projection.fields.provider_reference,
        }
    if isinstance(projection, DeploymentProjection):
        return "unverified", {
            "current_deployment": projection.fields.current_production_state,
            "release_note_is_deployment_proof": False,
            "required_evidence": ["deployment_receipt_with_target_revision_and_time"],
        }
    if isinstance(projection, BudgetProjection):
        return "untrusted_instruction_rejected", {
            "authority_changed": False,
            "budget_changed": False,
            "daily_cap_usd": str(projection.fields.daily_cap_usd),
            "work_cap_usd": str(projection.fields.work_cap_usd),
            "source_instruction_authoritative": (
                projection.fields.authority_changes_allowed_from_source_text
            ),
        }
    if isinstance(projection, LifetimeProjection):
        return "quota_denied", {
            "child_may_reset_allowance": False,
            "child_registration_allowed": projection.fields.child_registered,
            "resume_may_reset_allowance": projection.fields.resume_authorized,
            "root_remaining_usd": str(projection.fields.remaining_usd),
        }
    if isinstance(projection, PolicyProjection):
        return _oversight(projection)
    return _other_management(projection, context, text)


def _other_management(
    projection: Projection,
    context: AssembledContext,
    text: str,
) -> tuple[str, dict[str, JsonValue]]:
    if isinstance(projection, VerificationProjection):
        return _verification(projection, text)
    if isinstance(projection, ActionProjection):
        fields = projection.fields
        heads = {row.current.revision for row in context.manifest.source_heads}
        current = fields.current_revision if fields.current_revision in heads else None
        count = re.search(r"count(?: is| =|:)\s*(\d+)", text, flags=re.IGNORECASE)
        return "stale_conflict", {
            "current_revision": current,
            "inventory_count": int(count.group(1)) if count else None,
            "old_precondition_revision": fields.expected_revision,
            "old_action_may_issue": False,
            "old_precondition_valid": current == fields.expected_revision,
        }
    if isinstance(projection, EligibilityStateProjection):
        state = projection.fields
        eligible: list[JsonValue] = [
            name
            for name, item in (("W2", state.W2), ("W3", state.W3))
            if item.active_scope
            and item.other_prerequisites_satisfied
            and item.required_approval_satisfied
            and item.remaining_usd > 0
        ]
        blocked: list[JsonValue] = [
            {"work": name, "reason": "awaiting_approval"}
            for name, item in (("W2", state.W2), ("W3", state.W3))
            if not item.required_approval_satisfied
        ]
        return "answered", {
            "eligible_work": eligible,
            "blocked_work": blocked,
            "W2_executed": False,
        }
    if isinstance(projection, WorkProjection):
        commitment = commitment_fields(
            text,
            projection.fields.work_alias,
            projection.fields.state,
            projection.fields.blocking_dependency,
        )
        if commitment:
            return commitment
    return "unsupported", {"management_report": projection.model_dump(mode="json")}


def _oversight(projection: PolicyProjection) -> tuple[str, dict[str, JsonValue]]:
    return "promotion_denied", {
        "automatic_promotion_allowed": projection.fields.automatic_promotion_allowed,
        "completed_count_in_synthetic_projection": projection.fields.reviewed_completed_count,
        "oversight": projection.fields.oversight,
        "owner_approved_policy_change": projection.fields.owner_approved_policy_change,
        "policy_version": projection.fields.policy_version,
    }


def _verification(
    projection: VerificationProjection, text: str
) -> tuple[str, dict[str, JsonValue]]:
    fields = projection.fields
    if fields.verdict == "reject":
        verifier = re.search(r"Verifier (\w+)", text)
        artifact = re.search(r"artifact (\w+)", text)
        return "answered", {
            "verdict": fields.verdict,
            "work_completed": fields.work_completed,
            "criterion": fields.criterion_ids[0] if len(fields.criterion_ids) == 1 else None,
            "verifier": verifier.group(1) if verifier else None,
            "artifact": artifact.group(1) if artifact else None,
        }
    facts: dict[str, JsonValue] = {
        "acceptance": fields.verdict,
        "work_completed": fields.work_completed,
    }
    if fields.artifact_present is not None:
        facts["artifact_present"] = fields.artifact_present
    if fields.error_marker is not None:
        facts.update(
            error_marker=fields.error_marker,
            error_type=fields.error_type,
            passing_evidence_ids=[str(key) for key in fields.passing_evidence_ids],
        )
    return "unresolved_error" if fields.error_marker else "inconclusive", facts


def _sources(
    items: tuple[MaterializedEvidence, ...],
    context: AssembledContext,
    text: str,
    aliases: Mapping[UUID, EvidenceFixture],
) -> tuple[str, dict[str, JsonValue]]:
    if "Hypothesis " in text:
        claim = re.search(r"Hypothesis (\w+):", text)
        return "hypothetical", {
            "claim": claim.group(1) if claim else None,
            "claim_kind": "hypothesis",
            "asserted_as_product_fact": False,
            "verified": False,
        }
    if "Model proposes:" in text and "No source evidence" in text:
        return "proposed_unverified", {
            "relationship_status": "proposed_unverified",
            "supporting_evidence_ids": [],
            "verified": False,
            "promotion_permitted": False,
        }
    if "acceptance criteria:" in text:
        criteria = re.findall(r"^K\d+: [^\n]+", text, flags=re.MULTILINE)
        return "answered", {"criteria": criteria}
    if "Prerequisite: " in text:
        prerequisite = re.search(r"Prerequisite: ([^\n]+)", text)
        return "answered", {"prerequisite": prerequisite.group(1) if prerequisite else None}
    query = json.loads(context.input_text).get("question", "")
    extracted = report_fields(items, context, query, aliases) if isinstance(query, str) else None
    if extracted is not None:
        return extracted
    return "source_reported", {
        "source_reports": [
            {
                "source": aliases[row.record.evidence_id].source_alias,
                "revision": row.record.source.revision,
                "text": row.text,
                "source_event": row.record.source_event.model_dump(mode="json"),
                "ingested_at": row.record.ingested_at.astimezone(
                    ZoneInfo("Asia/Bangkok")
                ).isoformat(),
                "source_state": row.source_state,
                "freshness": row.freshness,
                "authority_profile": row.authority_profile,
            }
            for row in items
        ]
    }

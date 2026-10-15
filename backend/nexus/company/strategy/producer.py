"""Pure deterministic compiler; current access, strategic merit and publication are unproved."""

import hashlib
import json

from nexus.company.management.base import require_company
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.generated_artifact_contracts import MAX_GENERATED_BYTES
from nexus.company.strategy.artifact_contracts import PreparedStrategyArtifact
from nexus.company.strategy.checker import check_strategy_material
from nexus.company.strategy.contracts import StrategyBrief, StrategyCheckSnapshot, StrategyFinding
from nexus.company.strategy.producer_contracts import (
    MAX_STRATEGY_BUNDLE_BYTES,
    MAX_STRATEGY_SOURCE_ARTIFACTS,
    CompiledStrategy,
    StrategyOriginalInputBundle,
    StrategyOriginalInputBundleRef,
    StrategyProductionPolicy,
)
from nexus.core.llm.company_registry import DataClassification

_CLASSIFICATIONS: tuple[DataClassification, ...] = (
    "public",
    "internal",
    "confidential",
    "restricted",
)


def _inputs(
    snapshot: StrategyCheckSnapshot, policy: StrategyProductionPolicy
) -> tuple[StrategyCheckSnapshot, StrategyProductionPolicy]:
    # Python values must be revalidated before any JSON can normalize invalid raw counts.
    snapshot = StrategyCheckSnapshot.model_validate(snapshot.model_dump(warnings=False))
    policy = StrategyProductionPolicy.model_validate(policy.model_dump(warnings=False))
    require_company(snapshot.company_id, policy)
    if (
        policy.scope_sha256 != canonical_sha256(snapshot.scope)
        or policy.candidate_policy_sha256 != canonical_sha256(snapshot.policy)
        or len(snapshot.inputs.artifacts) > MAX_STRATEGY_SOURCE_ARTIFACTS
    ):
        raise ValueError("Strategy production policy or complete source artifact bound differs")
    return snapshot, policy


def strategy_input_bundle_bytes(
    snapshot: StrategyCheckSnapshot, policy: StrategyProductionPolicy
) -> bytes:
    """Encode deterministic lossless v2 JSON; canonical USD normalization is not storage."""
    snapshot, policy = _inputs(snapshot, policy)
    bundle = StrategyOriginalInputBundle(
        company_id=snapshot.company_id, snapshot=snapshot, policy=policy
    )
    # Preserve Pydantic Decimal/date wire values, sorting only the reachable typed set.
    # Tuple fields (findings, candidates, evidence and source order) remain ordered.
    payload = bundle.model_dump(mode="json")
    for index, source in enumerate(bundle.snapshot.sources):
        payload["snapshot"]["sources"][index]["source_policy"]["allowed_external_keys"] = sorted(
            source.source_policy.allowed_external_keys
        )
    raw = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()
    if len(raw) > MAX_STRATEGY_BUNDLE_BYTES:
        raise ValueError("Strategy original bundle exceeds complete byte bound")
    return raw


def _findings(
    snapshot: StrategyCheckSnapshot, policy: StrategyProductionPolicy
) -> tuple[StrategyFinding, ...]:
    sources = {row.evidence.evidence_id: row for row in snapshot.sources}
    findings = []
    for rule in policy.finding_rules:
        source = sources.get(rule.evidence_id)
        if source is None:
            raise ValueError("Strategy finding requires exact original evidence")
        evidence = source.evidence
        span = evidence.raw_span
        quote = source.raw_text.encode()[span.start_byte : span.end_byte].decode("utf8")
        findings.append(
            StrategyFinding(
                finding_id=rule.finding_id,
                evidence_id=evidence.evidence_id,
                source_revision_id=evidence.source.source_revision_id,
                artifact_revision_id=evidence.artifact.artifact_revision_id,
                span_sha256=evidence.span_sha256,
                quote=quote,
                source_event=evidence.source_event,
                hypothesis=rule.hypothesis,
            )
        )
    return tuple(findings)


def build_strategy_brief(
    snapshot: StrategyCheckSnapshot, policy: StrategyProductionPolicy
) -> StrategyBrief:
    """Compile only explicit policy narratives and exact original evidence; never call a model."""
    snapshot, policy = _inputs(snapshot, policy)
    # Enforce original bundle capacity even when the caller asks for only a brief.
    strategy_input_bundle_bytes(snapshot, policy)
    brief = StrategyBrief(
        scope=snapshot.scope,
        repository=snapshot.policy.repository,
        source_manifest_sha256=snapshot.policy.source_manifest_sha256,
        input_snapshot_sha256=canonical_sha256(snapshot),
        input_manifest_sha256=canonical_sha256(snapshot.inputs),
        findings=_findings(snapshot, policy),
        candidates=policy.candidates,
        recommendation=policy.recommendation,
        unknowns=policy.unknowns,
        decision_request=policy.decision_request,
    )
    if len(brief.model_dump_json().encode()) > MAX_GENERATED_BYTES:
        raise ValueError("Strategy brief output exceeds complete byte bound")
    if any(row.verdict != "pass" for row in check_strategy_material(snapshot, brief)):
        raise ValueError("Strategy original material fails mechanical self-consistency")
    return brief


def _classification(
    snapshot: StrategyCheckSnapshot, policy: StrategyProductionPolicy
) -> DataClassification:
    levels = ["internal", policy.data_classification]
    levels.extend(row.source_policy.data_classification for row in snapshot.sources)
    return next(row for row in reversed(_CLASSIFICATIONS) if row in levels)


def prepare_strategy_artifact(
    snapshot: StrategyCheckSnapshot,
    policy: StrategyProductionPolicy,
    *,
    original_bundle: StrategyOriginalInputBundleRef,
) -> CompiledStrategy:
    """Prepare bounded bytes and preserve a separate descriptive original-bundle identity."""
    snapshot, policy = _inputs(snapshot, policy)
    original_bundle = StrategyOriginalInputBundleRef.model_validate(
        original_bundle.model_dump(warnings=False)
    )
    require_company(snapshot.company_id, original_bundle)
    bundle_raw = strategy_input_bundle_bytes(snapshot, policy)
    if (
        original_bundle.input_snapshot_sha256 != canonical_sha256(snapshot)
        or original_bundle.producer_policy_sha256 != canonical_sha256(policy)
        or original_bundle.artifact.sha256 != hashlib.sha256(bundle_raw).hexdigest()
        or original_bundle.artifact.byte_length != len(bundle_raw)
        or any(
            row.artifact_id == original_bundle.artifact.artifact_id
            or row.artifact_revision_id == original_bundle.artifact.artifact_revision_id
            for row in snapshot.inputs.artifacts
        )
    ):
        raise ValueError("Strategy original bundle exact wire or input identity differs")
    brief = build_strategy_brief(snapshot, policy)
    raw = brief.model_dump_json().encode()
    return CompiledStrategy(
        brief=brief,
        original_bundle=original_bundle,
        prepared=PreparedStrategyArtifact(
            company_id=snapshot.company_id,
            raw_bytes=raw,
            output_sha256=hashlib.sha256(raw).hexdigest(),
            input_snapshot_sha256=canonical_sha256(snapshot),
            data_classification=_classification(snapshot, policy),
            inputs=snapshot.inputs,
        ),
    )

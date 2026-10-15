"""Synthetic protected-reader descriptions only; no actual source, model or acceptance proof."""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from nexus.builder.contracts import RepositoryPin
from nexus.company.brain.base import SourceTime
from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.brain.sources import (
    ArtifactRevisionRef,
    EvidenceRecord,
    EvidenceRef,
    SourceHead,
    SourceRevisionRef,
    UTF8Span,
)
from nexus.company.contracts.work import WorkItem
from nexus.company.management.acceptance import VerificationSpec
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.generated_artifact_contracts import GeneratedArtifactInputs
from nexus.company.management.goals import GoalRevisionRef
from nexus.company.management.lifecycle import PlanRevisionRef
from nexus.company.management.plans import RunBinding
from nexus.company.strategy.contracts import (
    STRATEGY_CHECK_CRITERIA,
    STRATEGY_CHECK_RECIPE,
    StrategyBrief,
    StrategyCandidate,
    StrategyCandidatePolicy,
    StrategyCandidateScope,
    StrategyCheckInput,
    StrategyCheckSnapshot,
    StrategyDecisionRequest,
    StrategyExpectation,
    StrategyFinding,
    StrategyHypothesis,
    StrategyRecommendation,
    StrategyScope,
    StrategySourceBytes,
    StrategyTradeoff,
    StrategyUnknown,
)
from nexus.execution.runtime_contracts import AttemptQuota, ExecutionRegistration
from nexus.execution.runtime_support import registration_digest
from nexus.harness.standing_contracts import ToolPermission

NOW = datetime(2026, 10, 15, tzinfo=UTC)


@dataclass(frozen=True)
class StrategyCase:
    brief: StrategyBrief
    command: StrategyCheckInput


def strategy_case() -> StrategyCase:
    """One rich brief with actual UTF8 offsets in a wholly synthetic reader snapshot."""
    # This >50-line fixture keeps its source, two roles, candidate policy and all hashes coherent.
    company, goal = UUID(int=1), UUID(int=2)
    author = RunBinding(
        company_id=company,
        workspace_id=UUID(int=3),
        actor_id=UUID(int=4),
        task_id=UUID(int=5),
        trace_id=UUID(int=6),
        run_id=UUID(int=7),
        workflow_name="company.cycle.artifact",
        workflow_version="v1",
        model_profile="reasoning",
        model_registry_version="synthetic-v1",
    )
    verifier = author.model_copy(
        update={
            "actor_id": UUID(int=8),
            "task_id": UUID(int=9),
            "trace_id": UUID(int=10),
            "run_id": UUID(int=11),
            "model_profile": "verification",
        }
    )
    work = WorkItem(
        company_id=company,
        task_id=author.task_id,
        trace_id=author.trace_id,
        goal_id=goal,
        department="strategy",
        title="Synthetic bounded CSV brief",
        acceptance=STRATEGY_CHECK_CRITERIA,
        budget_usd=Decimal(".08"),
    )
    registration = ExecutionRegistration(
        work=work,
        run_id=author.run_id,
        workflow_name=author.workflow_name,
        workflow_version="v1",
        model_profile="reasoning",
        model_registry_version=author.model_registry_version,
        quota=AttemptQuota(model_requests=1, tool_attempts=1, rework_rounds=0, plan_revisions=0),
    )
    scope = StrategyScope(
        company_id=company,
        goal=GoalRevisionRef(
            company_id=company,
            goal_id=goal,
            revision_id=UUID(int=12),
            version="v1",
            sha256="a" * 64,
        ),
        producing_plan=PlanRevisionRef(
            company_id=company,
            plan_id=UUID(int=13),
            plan_revision_id=UUID(int=14),
            revision=1,
            sha256="b" * 64,
        ),
        author=author,
        verifier=verifier,
        author_registration_sha256=registration_digest(registration),
    )
    text = "หมายเหตุ: qty = Number.parseInt(raw, 10);\n"
    raw = text.encode()
    source_ref = SourceRevisionRef(
        company_id=company,
        source_id=UUID(int=15),
        source_revision_id=UUID(int=16),
        revision="synthetic-source-v1",
    )
    artifact = ArtifactRevisionRef(
        company_id=company,
        artifact_id=UUID(int=17),
        artifact_revision_id=UUID(int=18),
        revision="synthetic-source-v1",
        sha256=hashlib.sha256(raw).hexdigest(),
        byte_length=len(raw),
    )
    span = UTF8Span(
        start_byte=len("หมายเหตุ: ".encode()),
        end_byte=len(raw) - 1,
        path="packages/shared/src/csv/index.ts",
    )
    quote = raw[span.start_byte : span.end_byte]
    event = SourceTime(precision="day", value="2026-09-01", basis="Synthetic committed-source date")
    evidence = EvidenceRecord(
        company_id=company,
        evidence_id=UUID(int=19),
        source=source_ref,
        artifact=artifact,
        raw_span=span,
        span_sha256=hashlib.sha256(quote).hexdigest(),
        source_event=event,
        ingested_at=NOW,
    )
    source = StrategySourceBytes(
        evidence=evidence,
        head=SourceHead(
            company_id=company,
            source_id=source_ref.source_id,
            current=source_ref,
            generation=1,
            observed_at=NOW,
            fresh_until=NOW + timedelta(hours=1),
            availability="available",
        ),
        source_policy=SourcePolicy(
            source_symbol="synthetic.strategy.source",
            authority_profile="synthetic",
            data_classification="internal",
            origin_kind="direct",
            media_type="text/plain",
            parser_version="utf8-identity-v1",
            chunker_version="utf8-sections-v1",
            search_config="simple",
            freshness_seconds=3600,
        ),
        raw_text=text,
    )
    change = StrategyCandidateScope(
        candidate_id="csv-quantity",
        kind="change",
        patch_sha256="c" * 64,
        method_sha256="d" * 64,
        write_paths=("packages/shared/src/csv/index.ts", "packages/shared/src/csv/csv.test.ts"),
        tool=ToolPermission(
            tool="company.builder.run.v1", tool_version="v1", resource="engineering.output"
        ),
    )
    defer = StrategyCandidateScope(candidate_id="defer", kind="defer")
    repository = RepositoryPin(
        repository_symbol="stockflow.fixture",
        commit="a" * 40,
        tree="b" * 40,
        archive_sha256="e" * 64,
    )
    policy = StrategyCandidatePolicy(
        company_id=company,
        goal_id=goal,
        repository=repository,
        source_manifest_sha256=artifact.sha256,
        candidates=(change, defer),
    )
    inputs = GeneratedArtifactInputs(
        company_id=company,
        artifacts=(artifact,),
        contributors=(source_ref,),
        evidence=(EvidenceRef(company_id=company, evidence_id=evidence.evidence_id),),
        required_resource_ids=(UUID(int=20),),
    )
    snapshot = StrategyCheckSnapshot(
        company_id=company,
        observed_at=NOW + timedelta(seconds=1),
        scope=scope,
        author_registration=registration,
        policy=policy,
        inputs=inputs,
        sources=(source,),
    )
    finding = StrategyFinding(
        finding_id="quantity-parse",
        evidence_id=evidence.evidence_id,
        source_revision_id=source_ref.source_revision_id,
        artifact_revision_id=artifact.artifact_revision_id,
        span_sha256=evidence.span_sha256,
        quote=quote.decode(),
        source_event=event,
        hypothesis=StrategyHypothesis(
            text="Some malformed strings may need stricter validation.",
            finding_ids=("quantity-parse",),
        ),
    )
    candidates = tuple(
        StrategyCandidate(
            scope=row,
            finding_ids=(finding.finding_id,),
            expected_benefit=StrategyExpectation(
                text="Expected benefit requires verification, not a proven customer result.",
                finding_ids=(finding.finding_id,),
            ),
            tradeoffs=(
                StrategyTradeoff(
                    kind="risk",
                    text="Changing parsing can reject inputs that callers currently send.",
                    finding_ids=(finding.finding_id,),
                ),
            ),
        )
        for row in (change, defer)
    )
    brief = StrategyBrief(
        scope=scope,
        repository=repository,
        source_manifest_sha256=policy.source_manifest_sha256,
        input_snapshot_sha256=canonical_sha256(snapshot),
        input_manifest_sha256=canonical_sha256(inputs),
        findings=(finding,),
        candidates=candidates,
        recommendation=StrategyRecommendation(
            candidate_id=change.candidate_id,
            rationale=StrategyHypothesis(
                text="Recommend bounded evaluation before any release.",
                finding_ids=(finding.finding_id,),
            ),
        ),
        unknowns=(
            StrategyUnknown(
                text="Deployed behavior has not been observed.",
                required_evidence="An authorized deployment and customer-readiness check.",
            ),
        ),
        decision_request=StrategyDecisionRequest(
            question="Select this candidate, defer, or reject?"
        ),
    )
    raw_output = brief.model_dump_json().encode()
    output = ArtifactRevisionRef(
        company_id=company,
        artifact_id=UUID(int=21),
        artifact_revision_id=UUID(int=22),
        revision="synthetic-brief-v1",
        sha256=hashlib.sha256(raw_output).hexdigest(),
        byte_length=len(raw_output),
    )
    target = VerificationSpec(
        company_id=company,
        author=author,
        verifier=verifier,
        action_id=UUID(int=23),
        proposal_sha256="f" * 64,
        receipt_id=UUID(int=24),
        receipt_sha256="0" * 64,
        work_snapshot_sha256=registration_digest(registration),
        criterion_ids=STRATEGY_CHECK_CRITERIA,
        artifacts=(output,),
        check_recipe=STRATEGY_CHECK_RECIPE,
    )
    return StrategyCase(
        brief,
        StrategyCheckInput(
            company_id=company,
            target=target,
            output=output,
            output_utf8=raw_output,
            snapshot=snapshot,
        ),
    )


def with_raw(case: StrategyCase, raw: bytes) -> StrategyCheckInput:
    output = case.command.output.model_copy(
        update={"sha256": hashlib.sha256(raw).hexdigest(), "byte_length": len(raw)}
    )
    return case.command.model_copy(
        update={
            "output": output,
            "output_utf8": raw,
            "target": case.command.target.model_copy(update={"artifacts": (output,)}),
        }
    )

"""Strict strategy descriptions; no model quality, owner decision or publication authority."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from nexus.builder.contracts import RepositoryPin
from nexus.company.brain.base import SourceTime
from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.brain.sources import ArtifactRevisionRef, EvidenceRecord, SourceHead
from nexus.company.management.acceptance import VerificationSpec
from nexus.company.management.base import (
    SHA256,
    ManagementContract,
    Name,
    Symbol,
    ValueContract,
    require_company,
)
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.check_contracts import CheckVerdict, CriterionCheckResult
from nexus.company.management.generated_artifact_contracts import GeneratedArtifactInputs
from nexus.company.management.goals import GoalRevisionRef
from nexus.company.management.lifecycle import PlanRevisionRef
from nexus.company.management.plans import RunBinding
from nexus.execution.runtime_contracts import ExecutionRegistration
from nexus.harness.standing_contracts import ToolPermission

STRATEGY_CHECK_RECIPE = "stockflow-strategy-brief-v1"
STRATEGY_CHECK_CRITERIA = (
    "strategy.schema.v1",
    "strategy.citations.v1",
    "strategy.source-time.v1",
    "strategy.candidate-scope.v1",
    "strategy.recommendation-binding.v1",
    "strategy.unknowns.v1",
)
STRATEGY_LIMITATIONS = (
    "mechanical_strategy_brief_only",
    "business_readiness_unproven",
    "owner_choice_required",
)
Text = Annotated[str, StringConstraints(min_length=1, max_length=2000)]
FindingIDs = Annotated[tuple[Symbol, ...], Field(min_length=1, max_length=16)]


class StrategyScope(ManagementContract):
    goal: GoalRevisionRef
    producing_plan: PlanRevisionRef
    author: RunBinding
    verifier: RunBinding
    author_registration_sha256: SHA256

    @model_validator(mode="after")
    def exact_roles(self) -> Self:
        require_company(self.company_id, self.goal, self.producing_plan, self.author, self.verifier)
        if (
            self.author.actor_id == self.verifier.actor_id
            or self.author.task_id == self.verifier.task_id
            or self.author.workspace_id != self.verifier.workspace_id
        ):
            raise ValueError("Strategy requires distinct bound author/verifier actors and work")
        if (
            self.producing_plan.revision != 1
            or any(
                (row.workflow_name, row.workflow_version) != ("company.cycle.artifact", "v1")
                for row in (self.author, self.verifier)
            )
            or (self.author.model_profile, self.verifier.model_profile)
            != ("reasoning", "verification")
        ):
            raise ValueError("Strategy original producing stage or role profile differs")
        return self


class StrategyReasoning(ValueContract):
    text: Text
    finding_ids: FindingIDs


class StrategyHypothesis(StrategyReasoning):
    kind: Literal["hypothesis"] = "hypothesis"


class StrategyExpectation(StrategyReasoning):
    kind: Literal["expectation"] = "expectation"


class StrategyTradeoff(StrategyReasoning):
    kind: Literal["risk", "effort_expectation", "evidence_limit"]


class StrategyUnknown(ValueContract):
    kind: Literal["unknown"] = "unknown"
    text: Text
    required_evidence: Text


class StrategyFinding(ValueContract):
    kind: Literal["source_quote"] = "source_quote"
    finding_id: Symbol
    evidence_id: UUID
    source_revision_id: UUID
    artifact_revision_id: UUID
    span_sha256: SHA256
    quote: Annotated[str, StringConstraints(min_length=1, max_length=16384)]
    source_event: SourceTime
    hypothesis: StrategyHypothesis | None = None


class StrategyCandidateScope(ValueContract):
    candidate_id: Symbol
    kind: Literal["change", "defer"]
    patch_sha256: SHA256 | None = None
    method_sha256: SHA256 | None = None
    write_paths: tuple[Name, ...] = Field(default=(), max_length=2)
    tool: ToolPermission | None = None

    @model_validator(mode="after")
    def bounded_scope(self) -> Self:
        if self.kind == "defer":
            if (
                self.patch_sha256 is not None
                or self.method_sha256 is not None
                or self.write_paths
                or self.tool is not None
            ):
                raise ValueError("Defer cannot carry a patch, tool or write scope")
        elif (
            self.patch_sha256 is None
            or self.method_sha256 is None
            or self.tool is None
            or (self.tool.tool, self.tool.tool_version) != ("company.builder.run.v1", "v1")
            or self.write_paths
            != ("packages/shared/src/csv/index.ts", "packages/shared/src/csv/csv.test.ts")
        ):
            raise ValueError("Strategy change must retain the reviewed two-file CSV scope")
        return self


class StrategyCandidatePolicy(ManagementContract):
    recipe_version: Literal["stockflow-strategy-brief-v1"] = "stockflow-strategy-brief-v1"
    goal_id: UUID
    repository: RepositoryPin
    source_manifest_sha256: SHA256
    candidates: tuple[StrategyCandidateScope, ...] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def closed_choices(self) -> Self:
        if (
            tuple(row.kind for row in self.candidates) != ("change", "defer")
            or len({row.candidate_id for row in self.candidates}) != 2
        ):
            raise ValueError("Strategy policy requires one distinct reviewed change and defer")
        return self


class StrategyCandidate(ValueContract):
    scope: StrategyCandidateScope
    finding_ids: FindingIDs
    expected_benefit: StrategyExpectation
    tradeoffs: tuple[StrategyTradeoff, ...] = Field(min_length=1, max_length=8)


class StrategyRecommendation(ValueContract):
    kind: Literal["recommendation"] = "recommendation"
    candidate_id: Symbol
    rationale: StrategyHypothesis


class StrategyDecisionRequest(ValueContract):
    kind: Literal["owner_select_defer_or_reject"] = "owner_select_defer_or_reject"
    question: Text


class StrategyBrief(ValueContract):
    schema_version: Literal["nexus.company.strategy-brief.v1"] = "nexus.company.strategy-brief.v1"
    scope: StrategyScope
    repository: RepositoryPin
    source_manifest_sha256: SHA256
    input_snapshot_sha256: SHA256
    input_manifest_sha256: SHA256
    findings: tuple[StrategyFinding, ...] = Field(min_length=1, max_length=16)
    candidates: tuple[StrategyCandidate, ...] = Field(min_length=2, max_length=2)
    recommendation: StrategyRecommendation
    unknowns: tuple[StrategyUnknown, ...] = Field(min_length=1, max_length=16)
    deployed_state: Literal["not_observed"] = "not_observed"
    decision_request: StrategyDecisionRequest


class StrategySourceBytes(ValueContract):
    """Bounded supplied UTF8 source description; only a future real reader establishes access."""

    evidence: EvidenceRecord
    head: SourceHead
    source_policy: SourcePolicy
    raw_text: Annotated[str, StringConstraints(min_length=1, max_length=2097152)]

    @model_validator(mode="after")
    def bounded_utf8(self) -> Self:
        require_company(self.evidence.company_id, self.head)
        if "\x00" in self.raw_text or len(self.raw_text.encode()) > 2097152:
            raise ValueError("Strategy source exceeds supported original UTF8 bounds")
        return self


class StrategyCheckSnapshot(ManagementContract):
    observed_at: AwareDatetime
    scope: StrategyScope
    author_registration: ExecutionRegistration
    policy: StrategyCandidatePolicy
    inputs: GeneratedArtifactInputs
    sources: tuple[StrategySourceBytes, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def scoped_snapshot(self) -> Self:
        require_company(
            self.company_id,
            self.scope,
            self.author_registration.work,
            self.policy,
            self.inputs,
            *(row.evidence for row in self.sources),
        )
        if (
            self.policy.goal_id != self.scope.goal.goal_id
            or sum(len(row.raw_text.encode()) for row in self.sources) > 8388608
        ):
            raise ValueError("Strategy snapshot goal or complete source-byte bound differs")
        return self


class StrategyCheckInput(ManagementContract):
    target: VerificationSpec
    output: ArtifactRevisionRef
    output_utf8: bytes | None = Field(default=None, max_length=262144)
    snapshot: StrategyCheckSnapshot | None = None

    @model_validator(mode="after")
    def same_company(self) -> Self:
        require_company(self.company_id, self.target, self.output, self.snapshot)
        return self


class StrategyCheckPayload(ManagementContract):
    recipe: Literal["stockflow-strategy-brief-v1"] = "stockflow-strategy-brief-v1"
    target_sha256: SHA256
    output_sha256: SHA256 | None
    input_snapshot_sha256: SHA256 | None
    verdict: CheckVerdict
    criteria: tuple[CriterionCheckResult, ...] = Field(min_length=1, max_length=32)
    strategic_merit: Literal["not_evaluated"] = "not_evaluated"
    limitations: tuple[Name, ...] = STRATEGY_LIMITATIONS

    @model_validator(mode="after")
    def mechanical_only(self) -> Self:
        if self.limitations != STRATEGY_LIMITATIONS:
            raise ValueError("Strategy check must retain all mechanical-only limitations")
        return self


class StrategyCheckResult(StrategyCheckPayload):
    result_sha256: SHA256

    @model_validator(mode="after")
    def exact_result(self) -> Self:
        declared = tuple(row.criterion_id for row in self.criteria)
        if self.verdict == "pass" and (
            len(declared) != len(STRATEGY_CHECK_CRITERIA)
            or set(declared) != set(STRATEGY_CHECK_CRITERIA)
        ):
            raise ValueError("Passing strategy result requires exactly six supported criteria")
        expected = (
            "reject"
            if any(row.verdict == "reject" for row in self.criteria)
            else "inconclusive"
            if any(row.verdict == "inconclusive" for row in self.criteria)
            else "pass"
        )
        payload = StrategyCheckPayload.model_validate(self.model_dump(exclude={"result_sha256"}))
        if (
            len({row.criterion_id for row in self.criteria}) != len(self.criteria)
            or self.verdict != expected
            or self.result_sha256 != canonical_sha256(payload)
        ):
            raise ValueError("Strategy result digest or actual criterion aggregate differs")
        return self


class StrategySelectionRef(ManagementContract):
    """Descriptive comparison ref only; an actual owner decision must bind it later."""

    brief: ArtifactRevisionRef
    acceptance_id: UUID
    candidate_id: Symbol
    candidate_scope_sha256: SHA256

    @model_validator(mode="after")
    def same_company(self) -> Self:
        require_company(self.company_id, self.brief)
        return self

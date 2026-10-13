"""Evaluator-only immutable receipts; never imported by runtime/context providers."""

from __future__ import annotations

import hashlib
import json
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from nexus.company.brain.base import SHA256, Flag, ValueContract
from nexus.company.brain.context import AssembledContext
from nexus.company.brain.retrieval import MaterializedEvidence, RetrievalResult
from nexus.tests.brain_sdk_capture import SDKCapture
from nexus.tests.brain_source_fixtures import Locator


class AnswerCitation(ValueContract):
    artifact_id: UUID
    company_id: UUID
    evidence_id: UUID
    locator: Locator
    source_alias: str
    source_revision: str
    source_revision_id: UUID
    span_sha256: SHA256


class StructuredAnswer(ValueContract):
    """Free prose is excluded; rendered output must be exactly these checked fields."""

    status: str
    facts: dict[str, JsonValue]
    citations: tuple[AnswerCitation, ...] = ()
    limitations: tuple[str, ...] = ()

    def rendered(self) -> str:
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)


class ObservedSurface(ValueContract):
    name: str
    before: JsonValue
    after: JsonValue


class CaseObservation(ValueContract):
    """Only a restricted-PG runner supplies execution proof; no manifest-only scoring."""

    case_id: str
    company_id: UUID
    principal_id: UUID
    backend: Literal["restricted_postgresql"]
    database_role: Literal["nexus_company_app"]
    question_sha256: SHA256
    input_sha256: SHA256
    rubric_sha256: SHA256
    source_pack_sha256: SHA256
    configuration_sha256: SHA256
    retrieval: RetrievalResult
    materialized: tuple[MaterializedEvidence, ...]
    context: AssembledContext
    sdk_request: SDKCapture
    answer: StructuredAnswer
    export_render: str
    surfaces: tuple[ObservedSurface, ...]


class GoldenAssertion(ValueContract):
    assertion_id: str
    expected: JsonValue
    must_pass_for_case: Literal[True]
    operation: str
    rubric_clause: str
    surfaces: tuple[str, ...]


class GoldenCase(ValueContract):
    assertions: tuple[GoldenAssertion, ...]
    case_id: str
    category: str
    critical: Flag
    expected_answer: dict[str, JsonValue]
    input_sha256: SHA256
    original_rubric: str
    question_sha256: SHA256
    rubric_sha256: SHA256


class GoldenPack(BaseModel):
    # Remaining hash-frozen reviewer metadata is deliberately excluded from execution inputs.
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)
    fixture_version: Literal["company-brain-golden-v1"]
    access: Literal["evaluator_only_never_ingest_or_prompt"]
    cases: tuple[GoldenCase, ...]


class ClauseReceipt(ValueContract):
    assertion_id: str
    operation: str
    passed: Flag
    reason: str


class CaseReceipt(ValueContract):
    case_id: str
    critical: Flag
    passed: Flag
    generic_checks: tuple[ClauseReceipt, ...]
    clauses: tuple[ClauseReceipt, ...]
    observation_sha256: SHA256 | None


class EvaluationReceipt(ValueContract):
    fixture_version: Literal["brain-evaluation-v1"] = "brain-evaluation-v1"
    scope: Literal["synthetic_restricted_pg_offline_sdk_only"]
    original_question_pack_sha256: SHA256
    source_pack_sha256: SHA256
    golden_pack_sha256: SHA256
    source_golden_manifest_sha256: SHA256
    configuration_sha256: SHA256
    cases: tuple[CaseReceipt, ...] = Field(min_length=30, max_length=30)
    passed_count: int
    critical_passed_count: int
    threshold_passed: Flag


def fingerprint(value: ValueContract) -> str:
    return hashlib.sha256(value.model_dump_json().encode()).hexdigest()

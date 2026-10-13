"""User question inputs and receipt hashes only; rubrics/inputs never enter model context."""

from __future__ import annotations

import hashlib

from nexus.company.brain.base import SHA256, ValueContract
from nexus.tests.brain_source_fixtures import FIXTURES, QUESTION_SHA256, FixtureRecord


class QuestionSource(FixtureRecord):
    id: str
    question: str
    input: str
    rubric: str


class QuestionPack(FixtureRecord):
    cases: tuple[QuestionSource, ...]


class QuestionInput(ValueContract):
    case_id: str
    question: str
    question_sha256: SHA256
    input_sha256: SHA256
    rubric_sha256: SHA256


def question_inputs() -> tuple[QuestionInput, ...]:
    raw = (FIXTURES.parent / "company_v1" / "brain_cases.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != QUESTION_SHA256:
        raise ValueError("Original Brain questions changed")
    return tuple(
        QuestionInput(
            case_id=row.id,
            question=row.question,
            question_sha256=hashlib.sha256(row.question.encode()).hexdigest(),
            input_sha256=hashlib.sha256(row.input.encode()).hexdigest(),
            rubric_sha256=hashlib.sha256(row.rubric.encode()).hexdigest(),
        )
        for row in QuestionPack.model_validate_json(raw).cases
    )

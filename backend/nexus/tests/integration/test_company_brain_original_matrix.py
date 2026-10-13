"""Original thirty isolated PG observations; independent frozen scorer writes the full matrix."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.tests.brain_api_support import brain_api_factory as brain_api_factory
from nexus.tests.brain_case_questions import QuestionInput, question_inputs
from nexus.tests.brain_case_runner import observe_case
from nexus.tests.brain_evaluation_contracts import ObservedSurface


@pytest.mark.parametrize("question", question_inputs(), ids=lambda row: row.case_id)
async def test_original_case_observation(
    brain_api_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    question: QuestionInput,
    caplog: pytest.LogCaptureFixture,
    pytestconfig: pytest.Config,
) -> None:
    destination = Path(str(pytestconfig.getoption("basetemp"))) / "observations"
    await asyncio.to_thread(destination.mkdir, mode=0o700, exist_ok=True)
    observed = await observe_case(
        brain_api_factory, ProtectedBlobStore(tmp_path, storage_symbol="fixture.blobs.v1"), question
    )
    # Actual structured log records are an evaluator-only surface, never model input.
    surfaces = tuple(
        ObservedSurface(name="logs", before=caplog.text, after=caplog.text)
        if row.name == "logs"
        else row
        for row in observed.surfaces
    )
    captured = observed.model_validate_json(
        observed.model_copy(update={"surfaces": surfaces}).model_dump_json()
    )
    await asyncio.to_thread(
        (destination / f"{question.case_id}.json").write_text,
        captured.model_dump_json(indent=2) + "\n",
    )
    assert json.loads(captured.sdk_request.response_text) == captured.answer.model_dump(mode="json")

"""Actual source-only observations and SDK serialization before the reviewed scored run."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.tests.brain_api_support import brain_api_factory as brain_api_factory
from nexus.tests.brain_case_questions import question_inputs
from nexus.tests.brain_case_runner import observe_case
from nexus.tests.brain_evaluation_contracts import CaseObservation


@pytest.mark.parametrize("case_id", ["B07", "B13", "B20", "B26"])
async def test_source_only_observation_uses_actual_authorized_context_and_sdk_response(
    brain_api_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    case_id: str,
) -> None:
    question = next(row for row in question_inputs() if row.case_id == case_id)
    observed = await observe_case(
        brain_api_factory, ProtectedBlobStore(tmp_path, storage_symbol="fixture.blobs.v1"), question
    )
    assert CaseObservation.model_validate_json(observed.model_dump_json()) == observed
    assert observed.sdk_request.response_text == observed.answer.model_dump_json()
    assert observed.sdk_request.input_text == observed.context.input_text
    for row in observed.surfaces:
        if row.name in ("authority_state", "budget_state", "work_state", "effect_state"):
            assert row.before == row.after
    assert observed.database_role == "nexus_company_app"

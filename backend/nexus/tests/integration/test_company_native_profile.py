"""Pending native actions are not approvals, effects, scheduled dispatch or paid-model work."""

import json
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.management.generated_artifact_contracts import GeneratedArtifactActionParameters
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt
from nexus.harness.journal_models import CostHold, JournalAction
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_management_acceptance import saved_m1
from nexus.tests.native_profile_support import configured_profile
from nexus.tests.native_profile_support import profile_factory as profile_factory


async def test_owner_native_due_profile_prepares_one_exact_pending_author_without_effects(
    profile_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    case = await configured_profile(profile_factory, tmp_path)
    profile = await case.preparation.resolve_profile(
        control(), identity(OWNER), case.report_id, case.commitment_id, case.evidence_ids
    )
    before = await saved_m1(profile_factory)
    prepared = await case.preparation.prepare_author(profile.reference)
    assert prepared.phase == "author" and prepared.action.approval is None
    assert (
        prepared.action.state.value == "awaiting_approval" and prepared.action.consumed_at is None
    )
    assert await case.preparation.prepare_author(profile.reference) == prepared
    pins = GeneratedArtifactActionParameters.model_validate_json(
        json.dumps(prepared.action.proposal.parameters)
    )
    assert pins.report_id == case.report_id and pins.evidence_ids == case.evidence_ids
    assert await saved_m1(profile_factory) == before
    async with profile_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.scalar(select(func.count()).select_from(JournalAction)) == 1
        for model in (EffectIntent, ExecutionAttempt, CostHold):
            assert await session.scalar(select(func.count()).select_from(model)) == 0

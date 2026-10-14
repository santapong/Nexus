"""A verifier's actual lease deadline must survive all final metadata awaits."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import nexus.company.management.native_profile_admission as admission
from nexus.company.access import VerifiedIdentity
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.base import BrainReadScope
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.generated_artifact_contracts import (
    GeneratedArtifactPayload,
    GeneratedArtifactRule,
)
from nexus.company.management.generated_artifact_privacy import GeneratedProtection, protect_inputs
from nexus.harness.journal_models import CompanyControl, JournalAction
from nexus.tests.generated_artifact_fixture import ledger
from nexus.tests.integration.test_company_directory import COMPANY
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_management_acceptance import saved_m1
from nexus.tests.integration.test_company_native_profile_verifier import publish_author
from nexus.tests.native_profile_support import configured_profile
from nexus.tests.native_profile_support import profile_factory as profile_factory


async def test_actual_verifier_lease_expiring_during_final_protection_denies_pending_append(
    profile_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = await configured_profile(profile_factory, tmp_path)
    profile, action = await publish_author(case, profile_factory)
    verifier = case.payload.children[1].binding
    lease = await case.native.execution.claim(
        ledger(verifier), identity(verifier.actor_id), uuid4(), ttl_seconds=15
    )
    original = protect_inputs
    calls = 0

    async def late_protection(
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        signed: VerifiedIdentity,
        prepared: GeneratedArtifactPayload,
        rule: GeneratedArtifactRule,
        reader: BoundedArtifactReader,
        freshness: RegisteredSourceFreshness,
    ) -> GeneratedProtection:
        nonlocal calls
        result = await original(session, control, scope, signed, prepared, rule, reader, freshness)
        calls += 1
        if calls == 2:
            await asyncio.sleep(
                max(0, (lease.expires_at - datetime.now(UTC)).total_seconds()) + 0.1
            )
        return result

    monkeypatch.setattr(admission, "protect_inputs", late_protection)
    before = await saved_m1(profile_factory)
    with pytest.raises(ValueError, match="lease"):
        await case.preparation.prepare_verifier(profile.reference, lease, action.action_id)
    assert calls == 2 and await saved_m1(profile_factory) == before
    async with profile_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.scalar(select(func.count()).select_from(JournalAction)) == 1

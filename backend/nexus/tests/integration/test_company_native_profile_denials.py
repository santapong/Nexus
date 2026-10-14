"""Unknown schedules, current authority revocations and foreign selectors cannot prepare work."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.base import SourceTime
from nexus.company.control_store import CompanyControls
from nexus.company.directory_contracts import MembershipChange
from nexus.company.management.cancellation_contracts import CancellationCommand
from nexus.company.management.cancellation_store import WorkCancellationStore
from nexus.company.management.goals import DueIntent
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plans import RunBinding
from nexus.harness.journal_models import JournalAction
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_management_acceptance import saved_m1
from nexus.tests.native_profile_support import configured_profile
from nexus.tests.native_profile_support import profile_factory as profile_factory


@pytest.mark.parametrize("kind", ["future", "unknown", "date_only"])
async def test_only_actual_owner_actionable_instant_can_trigger_preparation(
    profile_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    kind: str,
) -> None:
    due = DueIntent(source_time=SourceTime(precision="unknown", value=None, basis="not scheduled"))
    if kind == "future":
        due = DueIntent(
            source_time=SourceTime(
                precision="instant",
                value=(datetime.now(UTC) + timedelta(days=1)).isoformat(),
                basis="owner schedule",
            ),
            actionable_at=datetime.now(UTC) + timedelta(days=1),
            actionable_basis="operator_explicit",
        )
    elif kind == "date_only":
        due = DueIntent(
            source_time=SourceTime(precision="day", value="2026-10-14", basis="date precision only")
        )
    case = await configured_profile(profile_factory, tmp_path, due=due)
    profile = await case.preparation.resolve_profile(
        control(), identity(OWNER), case.report_id, case.commitment_id, case.evidence_ids
    )
    before = await saved_m1(profile_factory)
    with pytest.raises(ValueError, match="actionable"):
        await case.preparation.prepare_author(profile.reference)
    assert await saved_m1(profile_factory) == before
    async with profile_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.scalar(select(func.count()).select_from(JournalAction)) == 0


@pytest.mark.parametrize(
    "failure",
    [
        "paused",
        "cancelled",
        "member",
        "source",
        "plan",
        "profile_hash",
        "commitment_hash",
        "foreign",
    ],
)
async def test_current_actual_binding_and_metadata_required_even_for_pending_action(
    profile_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    failure: str,
) -> None:
    case = await configured_profile(profile_factory, tmp_path)
    profile = await case.preparation.resolve_profile(
        control(), identity(OWNER), case.report_id, case.commitment_id, case.evidence_ids
    )
    reference = profile.reference
    actor = case.payload.children[0].binding
    if failure == "paused":
        await CompanyControls(profile_factory).set_paused_registered(
            control(), identity(OWNER), True
        )
    elif failure == "cancelled":
        await WorkCancellationStore(profile_factory).cancel(
            control(),
            identity(OWNER),
            CancellationCommand(company_id=COMPANY, target=actor, reason="Permanent stop"),
        )
    elif failure == "member":
        from nexus.company.directory_store import PersistentCompanyDirectory

        await PersistentCompanyDirectory(profile_factory).set_membership(
            MembershipChange(
                company_id=COMPANY,
                principal_id=actor.actor_id,
                role="member",
                membership_active=False,
            ),
            control(),
        )
    elif failure == "source":
        from nexus.tests.integration.test_company_generated_artifact_lifecycle import revoke_source

        await revoke_source(profile_factory, actor.actor_id)
    elif failure == "plan":
        plans = ManagementPlanStore(profile_factory, case.preparation.catalog)
        target = profile.selection.plan
        await plans.revoke(
            control(),
            identity(OWNER),
            target.plan_revision_id,
            target.sha256,
            expected_current_revision_id=target.plan_revision_id,
        )
    elif failure == "profile_hash":
        reference = reference.model_copy(update={"report_sha256": "0" * 64})
    elif failure == "commitment_hash":
        reference = reference.model_copy(
            update={"commitment": reference.commitment.model_copy(update={"sha256": "0" * 64})}
        )
    else:
        reference = reference.model_copy(
            update={
                "company_id": uuid4(),
                "commitment": reference.commitment.model_copy(update={"company_id": uuid4()}),
            }
        )
    before = await saved_m1(profile_factory)
    with pytest.raises(ValueError):
        await case.preparation.prepare_author(reference)
    assert await saved_m1(profile_factory) == before
    async with profile_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.scalar(select(func.count()).select_from(JournalAction)) == 0


class WrongIdentities:
    def actor(self, binding: RunBinding) -> VerifiedIdentity:
        return identity(OWNER)


async def test_configured_owner_is_not_an_automatic_replacement_for_author(
    profile_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    case = await configured_profile(profile_factory, tmp_path, identities=WrongIdentities())
    profile = await case.preparation.resolve_profile(
        control(), identity(OWNER), case.report_id, case.commitment_id, case.evidence_ids
    )
    with pytest.raises(ValueError, match="Configured"):
        await case.preparation.prepare_author(profile.reference)

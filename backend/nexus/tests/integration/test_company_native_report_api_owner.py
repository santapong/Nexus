"""Current owner admission must survive the transition from owner selection to actor preparation."""

from pathlib import Path
from uuid import UUID

import pytest
from litestar.testing import AsyncTestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.directory_contracts import MembershipChange
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management.native_profile_contracts import NativeReportOperatingProfile
from nexus.harness.journal_models import JournalAction
from nexus.tests.integration.test_company_api import headers
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_native_report_api import BASE
from nexus.tests.native_report_api_support import configured_report_api
from nexus.tests.native_report_api_support import report_api_factory as report_api_factory


async def test_owner_revoked_after_profile_resolution_cannot_commit_owner_requested_pending_action(
    report_api_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, case = await configured_report_api(report_api_factory, tmp_path)
    profile = await case.preparation.resolve_profile(
        control(), identity(OWNER), case.report_id, case.commitment_id, case.evidence_ids
    )
    original = case.preparation.resolve_profile

    async def resolve_then_revoke(
        scope: CompanyControlScope,
        signed: VerifiedIdentity,
        report: UUID,
        commitment: UUID,
        evidence: tuple[UUID, ...],
    ) -> NativeReportOperatingProfile:
        result = await original(scope, signed, report, commitment, evidence)
        await PersistentCompanyDirectory(report_api_factory).set_membership(
            MembershipChange(
                company_id=COMPANY, principal_id=OWNER, role="owner", membership_active=False
            ),
            control(),
        )
        return result

    monkeypatch.setattr(case.preparation, "resolve_profile", resolve_then_revoke)
    async with AsyncTestClient(app) as client:
        response = await client.post(
            BASE + "/profiles/prepare-author",
            json={"reference": profile.reference.model_dump(mode="json")},
            headers=headers(OWNER),
        )
        assert response.status_code == 403, response.text
    async with report_api_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.scalar(select(func.count()).select_from(JournalAction)) == 0

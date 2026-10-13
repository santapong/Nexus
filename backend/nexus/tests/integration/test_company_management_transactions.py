"""Management reuses the actual current owner mutex; no work/source authority is minted."""

from uuid import UUID

import pytest
from sqlalchemy import func, select

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access_support import require_resources
from nexus.company.directory_contracts import MembershipChange
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management.transactions import (
    ManagementDeniedError,
    management_owner_transaction,
)
from nexus.harness.journal_models import CompanyControl
from nexus.tests.integration.test_company_brain_access import (
    RESOURCE,
    AccessDatabase,
    identity,
    scope,
)
from nexus.tests.integration.test_company_brain_access import database as database
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER, WORKSPACE, control


async def test_owner_control_does_not_grant_source_read_or_registered_work(
    database: AccessDatabase,
) -> None:
    async with management_owner_transaction(database.app, control(), identity(OWNER)) as (
        session,
        current,
        now,
    ):
        assert current.owner_id == OWNER and now.utcoffset() is not None
        with pytest.raises(ValueError):
            await require_resources(session, scope(OWNER), (RESOURCE,), now)


@pytest.mark.parametrize("splice", ["member", "principal", "workspace"])
async def test_signed_owner_control_scope_cannot_be_spliced(
    database: AccessDatabase, splice: str
) -> None:
    owner_scope = control(ACTOR) if splice == "member" else control()
    signed = (
        identity(ACTOR)
        if splice in {"member", "principal"}
        else VerifiedIdentity(principal_id=OWNER, workspace_id=UUID(int=999))
    )
    with pytest.raises(ValueError):
        async with management_owner_transaction(database.app, owner_scope, signed):
            pytest.fail("An unbound control scope must not enter the management transaction")


async def test_cached_signed_identity_cannot_override_current_owner_revocation(
    database: AccessDatabase,
) -> None:
    signed = VerifiedIdentity(principal_id=OWNER, workspace_id=WORKSPACE)
    directory = PersistentCompanyDirectory(database.app)
    await directory.set_membership(
        MembershipChange(
            company_id=COMPANY, principal_id=OWNER, role="owner", membership_active=False
        ),
        control(),
    )
    with pytest.raises(ValueError):
        async with management_owner_transaction(database.app, control(), signed):
            pytest.fail("Revoked current owner cannot mutate management")


async def test_paused_intake_blocks_default_scope_but_explicit_control_maintenance_can_enter(
    database: AccessDatabase,
) -> None:
    async with database.app() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        current = await session.get(CompanyControl, COMPANY)
        assert current is not None
        current.paused = True
    with pytest.raises(ManagementDeniedError):
        async with management_owner_transaction(database.app, control(), identity(OWNER)):
            pytest.fail("Paused management cannot admit fresh work")
    async with management_owner_transaction(
        database.app, control(), identity(OWNER), allow_paused=True
    ) as (_, current, _):
        assert current.paused

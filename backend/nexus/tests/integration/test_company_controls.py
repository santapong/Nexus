"""Owner pause before work and current membership checks in private PostgreSQL."""

from decimal import Decimal
from typing import cast
from uuid import UUID

import pytest
from pydantic import StrictBool, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.control_store import CompanyControls
from nexus.company.directory_contracts import CompanyRegistration, MembershipChange
from nexus.company.directory_models import RegisteredWork
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import CompanyPolicy, LedgerScope
from nexus.harness.journal_models import CompanyControl, CostHold, WorkBudget
from nexus.tests.integration.test_company_directory import (
    ACTOR,
    COMPANY,
    OWNER,
    TRACE,
    WORKSPACE,
    control,
)
from nexus.tests.integration.test_company_registered_authorization import (
    governed_factory as governed_factory,
)


async def bootstrap(factory: async_sessionmaker[AsyncSession]) -> PersistentCompanyDirectory:
    await CompanyJournal(factory).create_company(
        CompanyPolicy(
            company_id=COMPANY,
            owner_id=OWNER,
            policy_version="policy-1",
            price_version="prices-1",
            work_cap_usd=Decimal("1.00"),
        ),
        LedgerScope(company_id=COMPANY, principal_id=OWNER, task_id=UUID(int=9), trace_id=TRACE),
    )
    directory = PersistentCompanyDirectory(factory)
    await directory.bootstrap(
        CompanyRegistration(company_id=COMPANY, owner_id=OWNER, workspace_id=WORKSPACE), control()
    )
    await directory.set_membership(
        MembershipChange(company_id=COMPANY, principal_id=ACTOR, role="member"), control()
    )
    return directory


def identity(principal: UUID = OWNER, workspace: UUID = WORKSPACE) -> VerifiedIdentity:
    return VerifiedIdentity(principal_id=principal, workspace_id=workspace)


async def test_actual_owner_pauses_before_work_and_new_instance_observes_it(
    governed_factory: async_sessionmaker[AsyncSession],
) -> None:
    await bootstrap(governed_factory)
    state = await CompanyControls(governed_factory).set_paused_registered(
        control(), identity(), True
    )
    assert state.paused and state.operation_id == control().operation_id
    async with governed_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        current = await session.get(CompanyControl, COMPANY)
        assert current is not None and current.paused
        assert (await session.scalars(select(RegisteredWork))).all() == []
        assert (await session.scalars(select(WorkBudget))).all() == []
        assert (await session.scalars(select(CostHold))).all() == []
    resumed = await CompanyControls(governed_factory).set_paused_registered(
        control(), identity(), False
    )
    assert not resumed.paused


@pytest.mark.parametrize("invalid", ["member", "identity", "workspace", "company"])
async def test_control_identity_cannot_impersonate_owner_or_other_workspace(
    governed_factory: async_sessionmaker[AsyncSession],
    invalid: str,
) -> None:
    await bootstrap(governed_factory)
    scope, verified = control(), identity()
    if invalid == "member":
        scope, verified = control(ACTOR), identity(ACTOR)
    if invalid == "identity":
        verified = identity(ACTOR)
    if invalid == "workspace":
        verified = identity(workspace=UUID(int=99))
    if invalid == "company":
        scope = scope.model_copy(update={"company_id": UUID(int=99)})
    with pytest.raises(ValueError):
        await CompanyControls(governed_factory).set_paused_registered(scope, verified, True)


async def test_owner_revocation_after_gateway_lookup_is_rechecked_under_lock(
    governed_factory: async_sessionmaker[AsyncSession],
) -> None:
    directory = await bootstrap(governed_factory)
    old = await directory.lookup_principal(identity(), task_id=UUID(int=9), trace_id=TRACE)
    assert old is not None and old.membership_active
    await directory.set_membership(
        MembershipChange(
            company_id=COMPANY, principal_id=OWNER, role="owner", membership_active=False
        ),
        control(),
    )
    with pytest.raises(ValueError):
        await CompanyControls(governed_factory).set_paused_registered(control(), identity(), True)
    async with governed_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        current = await session.get(CompanyControl, COMPANY)
        assert current is not None and not current.paused


@pytest.mark.parametrize("value", ["false", 0, 1, None])
async def test_pause_value_must_be_an_explicit_boolean(
    governed_factory: async_sessionmaker[AsyncSession],
    value: object,
) -> None:
    await bootstrap(governed_factory)
    with pytest.raises(ValidationError):
        await CompanyControls(governed_factory).set_paused_registered(
            control(), identity(), cast(StrictBool, value)
        )

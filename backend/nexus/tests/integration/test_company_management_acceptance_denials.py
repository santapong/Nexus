"""Caller/candidate/revocation boundaries retain actual M1 facts and no accepted rows."""

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.contracts.results import VerificationResult
from nexus.company.directory_contracts import MembershipChange
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management.acceptance_models import ManagementWorkAcceptance
from nexus.execution.effect_store import EffectStore
from nexus.tests.integration.management_acceptance_fixture import (
    acceptance_factory as acceptance_factory,
)
from nexus.tests.integration.management_acceptance_fixture import configured_acceptance
from nexus.tests.integration.management_acceptance_report_fixture import bindings
from nexus.tests.integration.test_company_directory import COMPANY, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_management_acceptance import saved_m1


async def no_acceptance(factory: async_sessionmaker[AsyncSession]) -> None:
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.scalar(select(func.count()).select_from(ManagementWorkAcceptance)) == 0


@pytest.mark.parametrize("change", ["author", "action", "fence", "principal"])
async def test_raw_actor_action_fence_or_signed_principal_cannot_publish(
    acceptance_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    change: str,
) -> None:
    scenario = await configured_acceptance(acceptance_factory, tmp_path)
    _, author, verifier = bindings(scenario.payload)
    lease = scenario.author_lease if change == "author" else scenario.verifier_lease
    if change == "fence":
        lease = lease.model_copy(update={"fence": lease.fence + 1})
    principal = author.actor_id if change in {"author", "principal"} else verifier.actor_id
    before = await saved_m1(acceptance_factory)
    with pytest.raises(ValueError):
        await scenario.store.publish_verified_result(
            lease,
            identity(principal),
            action_id=uuid4() if change == "action" else scenario.action_id,
            protected_result=scenario.protected_result,
        )
    await no_acceptance(acceptance_factory)
    assert await saved_m1(acceptance_factory) == before


async def test_membership_revocation_after_actual_bytes_read_denies_commit(
    acceptance_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    scenario = await configured_acceptance(acceptance_factory, tmp_path)
    verifier = bindings(scenario.payload)[2]

    async def revoke() -> None:
        await PersistentCompanyDirectory(acceptance_factory).set_membership(
            MembershipChange(
                company_id=COMPANY,
                principal_id=verifier.actor_id,
                role="member",
                membership_active=False,
            ),
            control(),
        )

    scenario.inputs.after_load = revoke
    before = await saved_m1(acceptance_factory)
    with pytest.raises(ValueError):
        await scenario.store.publish_verified_result(
            scenario.verifier_lease,
            identity(verifier.actor_id),
            action_id=scenario.action_id,
            protected_result=scenario.protected_result,
        )
    await no_acceptance(acceptance_factory)
    assert await saved_m1(acceptance_factory) == before


async def test_unqualified_null_ttl_is_not_an_immutable_source_policy(
    acceptance_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    scenario = await configured_acceptance(acceptance_factory, tmp_path, result_ttl=None)
    verifier = bindings(scenario.payload)[2]
    policies = scenario.policies
    previous = policies.policy("acceptance.fixture.300")
    policies.values[previous.source_symbol] = previous.model_copy(update={"freshness_seconds": 300})
    with pytest.raises(ValueError):
        await scenario.store.publish_verified_result(
            scenario.verifier_lease,
            identity(verifier.actor_id),
            action_id=scenario.action_id,
            protected_result=scenario.protected_result,
        )
    await no_acceptance(acceptance_factory)


async def test_m1_raw_pass_candidate_cannot_replace_protected_mechanical_result(
    acceptance_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    scenario = await configured_acceptance(acceptance_factory, tmp_path)
    _, author, verifier = bindings(scenario.payload)
    effects = EffectStore(
        acceptance_factory,
        management_catalog=scenario.plans.catalog,
        management_artifacts=scenario.artifacts,
        management_freshness=scenario.freshness,
    )
    candidate = VerificationResult(
        company_id=COMPANY,
        verification_id=uuid4(),
        action_id=scenario.action_id,
        verifier_id=verifier.actor_id,
        verdict="pass",
        criterion_ids=scenario.payload.plan.items[0].acceptance,
        evidence_ids=tuple(row.evidence_id for row in scenario.inputs.handles),
    )
    await effects.record_verification_candidate(
        scenario.author_lease, identity(author.actor_id), candidate
    )
    before = await saved_m1(acceptance_factory)
    with pytest.raises(ValueError):
        await scenario.store.publish_verified_result(
            scenario.verifier_lease,
            identity(verifier.actor_id),
            action_id=scenario.action_id,
            protected_result=scenario.inputs.source.artifact,
        )
    await no_acceptance(acceptance_factory)
    assert await saved_m1(acceptance_factory) == before

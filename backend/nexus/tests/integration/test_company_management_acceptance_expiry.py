"""Real time-only expiry and permission loss cannot cross the final immutable commit."""

import asyncio
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.brain.base import BrainReadScope
from nexus.company.management.acceptance_evidence import PreparedReportCheck
from nexus.harness.journal_models import CompanyControl
from nexus.tests.integration.management_acceptance_fixture import (
    acceptance_factory as acceptance_factory,
)
from nexus.tests.integration.management_acceptance_fixture import configured_acceptance, ledger
from nexus.tests.integration.management_acceptance_report_fixture import bindings
from nexus.tests.integration.test_company_brain_ingestion import RESOURCE, owner_scope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_management_acceptance_denials import no_acceptance


async def test_expired_registered_ttl_after_final_revalidator_denies_commit(
    acceptance_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = await configured_acceptance(acceptance_factory, tmp_path, result_ttl=1)
    verifier = bindings(scenario.payload)[2]
    original = scenario.store._resolver.revalidate

    async def delayed(
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        signed: VerifiedIdentity,
        prepared: PreparedReportCheck,
        now: datetime,
    ) -> None:
        await original(session, control, scope, signed, prepared, now)
        await asyncio.sleep(1.1)

    monkeypatch.setattr(scenario.store._resolver, "revalidate", delayed)
    with pytest.raises(ValueError):
        await scenario.store.publish_verified_result(
            scenario.verifier_lease,
            identity(verifier.actor_id),
            action_id=scenario.action_id,
            protected_result=scenario.protected_result,
        )
    await no_acceptance(acceptance_factory)


async def test_actual_input_resource_revocation_after_bytes_denies_commit(
    acceptance_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    scenario = await configured_acceptance(acceptance_factory, tmp_path)
    verifier = bindings(scenario.payload)[2]

    async def revoke() -> None:
        await ResourceAccessStore(acceptance_factory).change(
            owner_scope(),
            identity(OWNER),
            ResourceAccessChange(
                company_id=COMPANY,
                resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
                principal_id=verifier.actor_id,
                active=False,
                expected_generation=2,
            ),
        )

    scenario.inputs.after_load = revoke
    with pytest.raises(ValueError):
        await scenario.store.publish_verified_result(
            scenario.verifier_lease,
            identity(verifier.actor_id),
            action_id=scenario.action_id,
            protected_result=scenario.protected_result,
        )
    await no_acceptance(acceptance_factory)


async def test_expired_execute_lease_after_all_evidence_revalidation_denies_commit(
    acceptance_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = await configured_acceptance(acceptance_factory, tmp_path)
    verifier = bindings(scenario.payload)[2]
    await scenario.execution.release(scenario.verifier_lease, identity(verifier.actor_id))
    lease = await scenario.execution.claim(
        ledger(verifier),
        identity(verifier.actor_id),
        scenario.verifier_lease.worker_id,
        ttl_seconds=1,
    )
    original = scenario.store._resolver.revalidate

    async def delayed(
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        signed: VerifiedIdentity,
        prepared: PreparedReportCheck,
        now: datetime,
    ) -> None:
        await original(session, control, scope, signed, prepared, now)
        await asyncio.sleep(1.1)

    monkeypatch.setattr(scenario.store._resolver, "revalidate", delayed)
    with pytest.raises(ValueError):
        await scenario.store.publish_verified_result(
            lease,
            identity(verifier.actor_id),
            action_id=scenario.action_id,
            protected_result=scenario.protected_result,
        )
    await no_acceptance(acceptance_factory)

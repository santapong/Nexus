"""Actual public negative scope prevents waiting from hiding permanent fresh-action failures."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.control_store import CompanyControls
from nexus.company.directory_contracts import MembershipChange
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management.cancellation_contracts import CancellationCommand
from nexus.company.management.cancellation_store import WorkCancellationStore
from nexus.company.management.control_store import ManagementControlStore
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.execution.engineering_lease_recovery import (
    prior_live_deadline,
)
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import CostHold
from nexus.tests.engineering_fixture import engineering_scenario
from nexus.tests.engineering_immediate_fixture import (
    immediate_negative_factory as immediate_negative_factory,
)
from nexus.tests.engineering_pending_services import pending_services
from nexus.tests.integration.test_company_brain_ingestion import owner_scope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_engineering_worker_replay import actual_command


@pytest.mark.parametrize(
    "reason",
    ["pause", "cancel", "governance", "source", "member", "foreign", "segment", "credential"],
)
async def test_current_unissued_live_lease_preflight_denies_permanent_negative(
    immediate_negative_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    reason: str,
) -> None:
    # Keep this >50-line public fixture/negative together; no intent or lease is seeded.
    item = await engineering_scenario(
        immediate_negative_factory, tmp_path, reserve_native_dispatch=True, defer_verifier=True
    )
    command = await actual_command(immediate_negative_factory, item.verifier_spec.job.action_id)
    signed = identity(command.actor_id)
    scope = LedgerScope(
        company_id=COMPANY,
        principal_id=command.actor_id,
        task_id=command.task_id,
        trace_id=command.trace_id,
    )
    original = await item.runner.execution.claim(
        scope, signed, uuid4(), segment_id=command.segment_id, ttl_seconds=30
    )
    services = pending_services(item, credential_seconds=2 if reason == "credential" else 300)
    credential = await services.identities.current(item.verifier_binding)
    if reason == "pause":
        await CompanyControls(immediate_negative_factory).set_paused_registered(
            control(), identity(OWNER), True
        )
    elif reason == "cancel":
        await WorkCancellationStore(immediate_negative_factory).cancel(
            control(),
            identity(OWNER),
            CancellationCommand(
                company_id=COMPANY, target=item.verifier_binding, reason="Actual negative fixture"
            ),
        )
    elif reason == "governance":
        async with immediate_negative_factory() as session, session.begin():
            await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
            current = await ManagementPlanStore.current_binding(session, COMPANY, command.task_id)
            assert current is not None
            from nexus.company.management.acceptance_support import stored_plan
            from nexus.company.management.plan_models import ManagementPlanRevision

            revision = await session.get(
                ManagementPlanRevision, (COMPANY, current.plan.plan_revision_id)
            )
            assert revision is not None
            mandate = stored_plan(revision, COMPANY).mandate
        await ManagementControlStore(immediate_negative_factory).revoke_mandate(
            control(), identity(OWNER), mandate
        )
    elif reason == "source":
        from nexus.company.brain.access_models import BrainResourceAccess

        async with immediate_negative_factory() as session, session.begin():
            await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
            access = await session.get(
                BrainResourceAccess, (COMPANY, UUID(int=9501), command.actor_id)
            )
            assert access is not None
            generation = access.generation
        await ResourceAccessStore(immediate_negative_factory).change(
            owner_scope(),
            identity(OWNER),
            ResourceAccessChange(
                company_id=COMPANY,
                resource=ResourceRef(company_id=COMPANY, resource_id=UUID(int=9501)),
                principal_id=command.actor_id,
                active=False,
                expected_generation=generation,
            ),
        )
    elif reason == "member":
        await PersistentCompanyDirectory(immediate_negative_factory).set_membership(
            MembershipChange(
                company_id=COMPANY,
                principal_id=command.actor_id,
                role="member",
                membership_active=False,
            ),
            control(),
        )
    elif reason == "foreign":
        command = command.model_copy(update={"action_id": uuid4()})
    elif reason == "segment":
        command = command.model_copy(update={"segment_id": uuid4()})
    else:
        await asyncio.sleep(
            max(0, (credential.expires_at - datetime.now(UTC)).total_seconds()) + 0.03
        )
    with pytest.raises(ValueError):
        await prior_live_deadline(services, scope, credential, command)
    async with immediate_negative_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        work = await session.get(ExecutionWork, (COMPANY, item.verifier_binding.task_id))
        intent = await session.get(EffectIntent, (COMPANY, item.verifier_action.action_id))
        hold = await session.get(CostHold, item.verifier_action.action_id)
        assert (
            work is not None
            and work.fence == original.fence
            and work.worker_id == original.worker_id
        )
        assert work.tool_attempts_used == work.model_requests_used == 0 and intent is None
        assert (
            hold is not None
            and hold.state == "held"
            and hold.amount_usd > 0
            and hold.actual_usd is None
        )

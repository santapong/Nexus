"""Current authority/source changes stop new preparation/dispatch without deleting M1 truth."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

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
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.scheduling_contracts import EventWake
from nexus.execution.dispatch_models import SegmentDispatch
from nexus.harness.journal_models import JournalAction
from nexus.tests.integration.test_company_brain_ingestion import RESOURCE, owner_scope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_generated_artifact_lifecycle import revoke_source
from nexus.tests.integration.test_company_management_acceptance import saved_m1
from nexus.tests.operating_loop_support import configured_loop, decide_and_authorize
from nexus.tests.operating_loop_support import loop_factory as loop_factory


@pytest.mark.parametrize(
    "failure", ["paused", "cancelled", "member", "plan", "source", "grant_expiry"]
)
async def test_actual_changes_deny_fresh_author_dispatch_and_preserve_existing_hold(
    loop_factory: async_sessionmaker[AsyncSession], tmp_path: Path, failure: str
) -> None:
    loop, case = await configured_loop(loop_factory, tmp_path)
    pending = await loop.tick(control(), identity(OWNER))
    assert pending.pending is not None
    await decide_and_authorize(loop_factory, case, pending.pending)
    actor = case.payload.children[0].binding
    if failure == "paused":
        await CompanyControls(loop_factory).set_paused_registered(control(), identity(OWNER), True)
    elif failure == "cancelled":
        await WorkCancellationStore(loop_factory).cancel(
            control(),
            identity(OWNER),
            CancellationCommand(company_id=COMPANY, target=actor, reason="Permanent owner stop"),
        )
    elif failure == "member":
        await PersistentCompanyDirectory(loop_factory).set_membership(
            MembershipChange(
                company_id=COMPANY,
                principal_id=actor.actor_id,
                role="member",
                membership_active=False,
            ),
            control(),
        )
    elif failure == "plan":
        target = (
            await case.preparation.resolve_profile(
                control(), identity(OWNER), case.report_id, case.commitment_id, case.evidence_ids
            )
        ).selection.plan
        await ManagementPlanStore(loop_factory, case.preparation.catalog).revoke(
            control(),
            identity(OWNER),
            target.plan_revision_id,
            target.sha256,
            expected_current_revision_id=target.plan_revision_id,
        )
    elif failure == "source":
        await revoke_source(loop_factory, actor.actor_id)
    else:
        expiry = datetime.now(UTC) + timedelta(seconds=2)
        await ResourceAccessStore(loop_factory).change(
            owner_scope(),
            identity(OWNER),
            ResourceAccessChange(
                company_id=COMPANY,
                resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
                principal_id=actor.actor_id,
                active=True,
                expires_at=expiry,
                expected_generation=2,
            ),
        )
        await asyncio.sleep(2.1)
    before = await saved_m1(loop_factory)
    result = await loop.tick(control(), identity(OWNER))
    assert (
        result.state == "blocked" and result.scheduled is None and not result.preparation_performed
    )
    assert await saved_m1(loop_factory) == before
    async with loop_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.scalar(select(func.count()).select_from(SegmentDispatch)) == 0
        assert await session.scalar(select(func.count()).select_from(JournalAction)) == 1


@pytest.mark.parametrize(
    "kind", ["member", "missing_principal", "foreign_workspace", "missing_event"]
)
async def test_tick_needs_actual_current_signed_owner_and_actual_native_event(
    loop_factory: async_sessionmaker[AsyncSession], tmp_path: Path, kind: str
) -> None:
    loop, case = await configured_loop(loop_factory, tmp_path)
    signed = identity(OWNER)
    scope = control()
    event = None
    if kind == "member":
        signed = identity(case.payload.children[0].binding.actor_id)
        scope = scope.model_copy(update={"principal_id": signed.principal_id})
    elif kind == "missing_principal":
        signed = signed.model_copy(update={"principal_id": uuid4()})
        scope = scope.model_copy(update={"principal_id": signed.principal_id})
    elif kind == "foreign_workspace":
        signed = signed.model_copy(update={"workspace_id": uuid4()})
    else:
        event = EventWake(stream="brain", event_id=uuid4())
    before = await saved_m1(loop_factory)
    with pytest.raises(ValueError):
        await loop.tick(scope, signed, event=event)
    assert await saved_m1(loop_factory) == before

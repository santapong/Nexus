"""Original owner window around existing plan writes; no new plan/registration authority."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.control_support import db_clock
from nexus.company.management.nexus_coding_catalog import (
    configured_nexus_admission,
    select_configured_nexus_plan,
)
from nexus.company.management.plan_admission_capture import (
    CapturedPlanAdmission,
    _capture_plan_metadata_locked,
)
from nexus.company.management.plan_models import ManagementPlanHead, ManagementProcedure
from nexus.company.management.plan_support import validate_plan
from nexus.company.management.planning_native_facts import require_time
from nexus.company.management.plans import PlanPayload
from nexus.company.management.transactions import ManagementDeniedError
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.nexus_cycle_partition import require_nexus_owner_family_locked
from nexus.harness.journal_models import CompanyControl

if TYPE_CHECKING:
    from nexus.company.management.plan_store import ManagementPlanStore


@dataclass(frozen=True)
class NexusOwnerAdmission:
    captured: CapturedPlanAdmission
    objects: tuple[object, ...]
    end_us: int


def _objects(
    store: ManagementPlanStore, credential: AuthenticatedWorkerIdentity | None
) -> tuple[object, ...]:
    return store.factory, store.catalog, store.source_freshness, store.planning_reader, credential


async def capture_nexus_owner_locked(
    store: ManagementPlanStore,
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    payload: PlanPayload,
    credential: AuthenticatedWorkerIdentity | None,
    *,
    end_us: int,
) -> NexusOwnerAdmission | None:
    admission = configured_nexus_admission(store.catalog)
    if admission is None:
        return None
    require_time(end_us)
    stage = select_configured_nexus_plan(store.catalog, payload)
    if (
        not isinstance(credential, AuthenticatedWorkerIdentity)
        or credential.identity != identity
        or (
            identity.principal_id != control.owner_id
            or not isinstance(store.source_freshness, RegisteredSourceFreshness)
        )
    ):
        raise ManagementDeniedError("Nexus admission requires its genuine current owner witness")
    if stage == "execution" and (
        store.planning_reader is None
        or store.planning_reader.template.configured_admission != admission
    ):
        raise ManagementDeniedError("Nexus transition needs its exact protected planning mapper")
    credential.require_time(await db_clock(session))
    objects = _objects(store, credential)
    charters = await validate_plan(
        session, control, scope, identity, payload, store.catalog, store.source_freshness
    )
    window = await _capture_plan_metadata_locked(
        session,
        control,
        scope,
        identity,
        payload,
        store.catalog,
        charters,
        store.source_freshness,
        credential=credential,
    )
    procedure = await session.scalar(
        select(ManagementProcedure).where(
            ManagementProcedure.company_id == control.company_id,
            ManagementProcedure.goal_id == payload.goal.goal_id,
        )
    )
    head = await session.get(ManagementPlanHead, (control.company_id, payload.plan.plan_id))
    if procedure is not None:
        if head is None or head.state != "approved":
            raise ManagementDeniedError("Nexus cannot replace an existing goal procedure")
        await require_nexus_owner_family_locked(
            session, control, scope, identity, admission=admission, catalog=store.catalog
        )
    elif stage != "planning" or (head is not None and head.state != "proposed"):
        raise ManagementDeniedError("Nexus execution requires its actual registered bootstrap")
    if any(a is not b for a, b in zip(objects, _objects(store, credential), strict=True)):
        raise ManagementDeniedError("Nexus owner admission composition changed")
    window.require_time(await db_clock(session))
    require_time(end_us)
    return NexusOwnerAdmission(CapturedPlanAdmission(charters, window), objects, end_us)


async def finish_nexus_owner_locked(
    store: ManagementPlanStore,
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    payload: PlanPayload,
    credential: AuthenticatedWorkerIdentity | None,
    first: NexusOwnerAdmission | None,
) -> None:
    if first is None:
        if configured_nexus_admission(store.catalog) is not None:
            raise ManagementDeniedError("Nexus admission appeared after the original capture")
        return
    if any(a is not b for a, b in zip(first.objects, _objects(store, credential), strict=True)):
        raise ManagementDeniedError("Nexus owner admission composition changed")
    current = await capture_nexus_owner_locked(
        store, session, control, scope, identity, payload, credential, end_us=first.end_us
    )
    if current is None:
        raise ManagementDeniedError("Nexus original admission disappeared")
    first.captured.window.require_same_scope(current.captured.window)
    if canonical_sha256(store.catalog) != first.captured.window.catalog_sha256:
        raise ManagementDeniedError("Nexus complete catalog changed")
    final = await db_clock(session)
    first.captured.window.require_time(final)
    current.captured.window.require_time(final)
    require_time(first.end_us)


def require_nexus_exit(first: NexusOwnerAdmission | None) -> None:
    if first is not None:
        first.captured.window.require_time(datetime.now(UTC))
        require_time(first.end_us)

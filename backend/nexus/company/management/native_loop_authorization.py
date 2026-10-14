"""Consume an existing exact owner decision after complete current native admission."""

from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.management.generated_artifact_privacy import GeneratedProtection, protect_inputs
from nexus.company.management.native_loop_actions import require_loop_action
from nexus.company.management.native_loop_compiler import action_scope, compile_authorization
from nexus.company.management.native_loop_contracts import NativeOperatingRegistration
from nexus.company.management.native_profile_admission import control_scope, ledger_scope
from nexus.company.management.native_profile_lookup import load_profile
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plan_support import CurrentPlanBinding, validate_plan_profile
from nexus.company.management.plans import RunBinding
from nexus.company.management.transactions import ManagementDeniedError
from nexus.execution.management_checks import require_management_execution
from nexus.execution.native_report_services import NativeReportServices
from nexus.execution.runtime_support import db_now, execution_row, runtime_transaction
from nexus.harness.authorization_source import require_action_authority
from nexus.harness.journal_authorization import authorize_registered_pending_locked
from nexus.harness.journal_contracts import ActionRecord
from nexus.harness.journal_models import CompanyControl, JournalAction
from nexus.harness.journal_submission import pending_action_record


async def _current(
    session: AsyncSession,
    control: CompanyControl,
    native: NativeReportServices,
    registration: NativeOperatingRegistration,
    binding: RunBinding,
    signed: VerifiedIdentity,
    record: ActionRecord,
    phase: Literal["author", "verifier"],
) -> tuple[CurrentPlanBinding, GeneratedProtection]:
    scope = action_scope(binding, record)
    profile, _ = await load_profile(
        session,
        control,
        control_scope(scope),
        registration.profile,
        require_due=True,
        now=await db_now(session),
    )
    work = await execution_row(session, ledger_scope(binding))
    await require_management_execution(
        session,
        control,
        work,
        signed,
        native.publisher.catalog,
        native.artifacts,
        native.publisher.freshness,
        record.proposal,
        "tool_attempts",
    )
    bound = await ManagementPlanStore.current_binding(session, binding.company_id, binding.task_id)
    if bound is None or bound.child.binding != binding or bound.plan != profile.selection.plan:
        raise ManagementDeniedError("Native authorization exact plan binding is no longer current")
    rule = native.publisher.rules[record.proposal.tool]
    require_loop_action(registration, work, phase, record, rule)
    prepared = await compile_authorization(session, control, native, binding, signed, record, phase)
    protection = await protect_inputs(
        session,
        control,
        scope,
        signed,
        prepared,
        rule,
        native.artifacts,
        native.publisher.freshness,
    )
    return bound, protection


async def authorize_loop_action(
    native: NativeReportServices,
    registration: NativeOperatingRegistration,
    binding: RunBinding,
    phase: Literal["author", "verifier"],
) -> ActionRecord:
    """Same-CC current admission/hold/exact consumption/final clocks; no owner decision is made."""
    # Atomic authorization boundary: every native input/recipient/profile, actual
    # owner approval, cost hold and final post-flush clock must commit or roll back together.
    signed = native.identities.actor(binding)
    scope = ledger_scope(binding)
    async with runtime_transaction(native.factory, scope, signed) as (session, control, _):
        row = await session.get(JournalAction, registration.action_id(phase))
        if row is None:
            raise ManagementDeniedError("Native exact owner-approved action is unavailable")
        record = pending_action_record(row)
        first, first_protection = await _current(
            session, control, native, registration, binding, signed, record, phase
        )
        resources = await native.resources.current(session, binding, record.proposal, signed)
        approved = await authorize_registered_pending_locked(
            session, control, scope, signed, row.id, await db_now(session), resources
        )
        await session.flush()
        final, final_protection = await _current(
            session, control, native, registration, binding, signed, approved, phase
        )
        current_resources = await native.resources.current(
            session, binding, approved.proposal, signed
        )
        await require_action_authority(
            session, control, row, scope, signed, await db_now(session), current_resources
        )
        now = await db_now(session)
        first_protection.require_time(now)
        final_protection.require_time(now)
        validate_plan_profile(native.publisher.catalog, first.child, now)
        validate_plan_profile(native.publisher.catalog, final.child, now)
        if approved.approval is None or approved.approval.expires_at <= now:
            raise ManagementDeniedError("Exact owner approval expired during native authorization")
        return approved

"""Consume an existing exact owner decision with current native admission and sealed expiry."""

import asyncio
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.management.native_profile_admission import ledger_scope
from nexus.company.management.plans import RunBinding
from nexus.company.notifications.draft_store import owner_scope
from nexus.company.notifications.managed_admission import (
    ManagedNotificationAdmission,
    notification_action_id,
)
from nexus.company.notifications.managed_contracts import NativeNotificationSelection
from nexus.company.notifications.managed_preparation import ManagedNotificationPreparation
from nexus.company.notifications.native_facts import NotificationUnavailableError
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.execution.runtime_support import db_now, execution_row, runtime_transaction
from nexus.harness.authorization_source import require_action_authority
from nexus.harness.canonical import action_hash
from nexus.harness.journal_authorization import authorize_registered_pending_locked
from nexus.harness.journal_contracts import ActionRecord
from nexus.harness.journal_models import CompanyControl, JournalAction
from nexus.harness.journal_submission import pending_action_record


async def authorize_prepared_notification(
    preparation: ManagedNotificationPreparation,
    selection: NativeNotificationSelection,
    binding: RunBinding,
    credential: AuthenticatedWorkerIdentity,
) -> ActionRecord:
    """One company transaction rechecks the native action, hold, approval and final windows."""
    # Keep the exact admission/consumption/post-flush barrier together: splitting
    # this >50-line transaction must never turn partial checks into commit points.
    selection = NativeNotificationSelection.model_validate_json(selection.model_dump_json())
    binding = RunBinding.model_validate_json(binding.model_dump_json())
    if not isinstance(credential, AuthenticatedWorkerIdentity) or (
        selection.company_id != binding.company_id
        or selection.sender_task_id != binding.task_id
        or credential.identity.principal_id != binding.actor_id
        or credential.identity.workspace_id != binding.workspace_id
    ):
        raise NotificationUnavailableError("Notification authorization identity is unavailable")
    credential.require_time(datetime.now(UTC))
    signed, scope = credential.identity, ledger_scope(binding)
    action_id = notification_action_id(selection.plan, binding.task_id, selection.draft_id)
    async with (
        asyncio.timeout(30),
        runtime_transaction(preparation.factory, scope, signed) as (session, control, _),
    ):
        work = await execution_row(session, scope)
        row = await session.get(JournalAction, action_id)
        issued = await session.get(EffectIntent, (binding.company_id, action_id))
        if row is None or issued is not None:
            raise NotificationUnavailableError(
                "Notification authorization needs an unissued action"
            )
        record = pending_action_record(row)
        if record.approval is None or action_hash(record.proposal) != row.proposal_hash:
            raise NotificationUnavailableError("Notification exact owner decision is unavailable")
        first = await current_prepared_admission(
            preparation, session, control, work, signed, selection, binding, record
        )
        now = await db_now(session)
        credential.require_time(now)
        approved = await authorize_registered_pending_locked(
            session, control, scope, signed, action_id, now, ()
        )
        await session.flush()
        final = await current_prepared_admission(
            preparation, session, control, work, signed, selection, binding, approved
        )
        await require_action_authority(
            session, control, row, scope, signed, await db_now(session), ()
        )
        now = await db_now(session)
        preparation.drafts.recipients.require_current(final.draft.recipient_policy, now)
        first.require_time(preparation.catalog, now)
        final.require_time(preparation.catalog, now)
        credential.require_time(now)
        if approved.approval is None or not approved.approval.issued_at <= now < (
            approved.approval.expires_at
        ):
            raise NotificationUnavailableError("Notification exact decision expired")
        return approved


async def current_prepared_admission(
    preparation: ManagedNotificationPreparation,
    session: AsyncSession,
    control: CompanyControl,
    work: ExecutionWork,
    signed: VerifiedIdentity,
    selection: NativeNotificationSelection,
    binding: RunBinding,
    record: ActionRecord,
) -> ManagedNotificationAdmission:
    """Actual current draft and full binding must equal the configured deterministic proposal."""
    current = await preparation.admit(
        session,
        control,
        owner_scope(preparation_scope(binding, record), signed),
        signed,
        work,
        selection.draft_id,
        record.proposal,
    )
    expected = preparation._proposal(
        current.binding.plan,
        work,
        current.draft,
        control.policy_version,
        control.price_version,
    )
    if (
        current.binding.plan != selection.plan
        or current.binding.child.binding != binding
        or record.proposal != expected
    ):
        raise NotificationUnavailableError("Notification prepared action or current plan differs")
    return current


def preparation_scope(binding: RunBinding, record: ActionRecord) -> CompanyControlScope:
    """Build owner control metadata from exact native records; it grants no authority."""
    return CompanyControlScope(
        company_id=binding.company_id,
        principal_id=binding.actor_id,
        operation_id=record.proposal.action_id,
        trace_id=binding.trace_id,
    )

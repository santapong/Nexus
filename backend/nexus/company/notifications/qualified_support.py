"""Actual current owner/source/recipient pins shared by same-session publication and reads."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.native_fact_provenance import qualify_native_inputs
from nexus.company.brain.native_fact_services import NativeFactServices
from nexus.company.brain.scope_support import require_brain_scope
from nexus.company.management.operating_report_resources import report_resources
from nexus.company.notifications.contracts import (
    NotificationDraft,
    NotificationPolicy,
    OwnerRecipientPolicy,
)
from nexus.company.notifications.draft_store import owner_scope, require_draft_time
from nexus.company.notifications.native_facts import NotificationUnavailableError
from nexus.company.notifications.recipient_registry import RegisteredOwnerRecipients
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import CompanyControl


async def require_publication_scope(
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    recipient: OwnerRecipientPolicy,
    recipients: RegisteredOwnerRecipients,
) -> None:
    if (
        not session.in_transaction()
        or control.company_id != scope.company_id
        or recipient.owner_id != control.owner_id
    ):
        raise NotificationUnavailableError("Qualified notification owner context is unavailable")
    await require_owner_locked(session, control, scope, identity)
    recipients.require_current(recipient, await db_now(session))


async def require_owner_locked(
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
) -> None:
    if not session.in_transaction():
        raise NotificationUnavailableError("Qualified notification transaction is unavailable")
    actual = await session.scalar(
        select(CompanyControl)
        .where(CompanyControl.company_id == scope.company_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if actual is not control:
        raise NotificationUnavailableError("Qualified notification actual control is unavailable")
    await require_brain_scope(session, control, owner_scope(scope, identity), identity, owner=True)


def same_source(saved: NotificationDraft, current: NotificationDraft) -> None:
    if (
        saved.provenance != current.provenance
        or saved.recipient_policy != current.recipient_policy
        or (saved.policy_version, saved.template_version)
        != (current.policy_version, current.template_version)
        or (
            saved.signal.state_sha256,
            saved.trigger_sha256,
            saved.kind,
            saved.due_bucket,
            saved.scheduled_for,
        )
        != (
            current.signal.state_sha256,
            current.trigger_sha256,
            current.kind,
            current.due_bucket,
            current.scheduled_for,
        )
    ):
        raise NotificationUnavailableError("Qualified notification source snapshot changed")


def require_draft_policy(policy: NotificationPolicy, saved: NotificationDraft) -> None:
    if not policy.enabled or (policy.version, policy.template_version) != (
        saved.policy_version,
        saved.template_version,
    ):
        raise NotificationUnavailableError("Qualified notification policy is unavailable")


def require_batch_time(drafts: tuple[NotificationDraft, ...], now: datetime) -> None:
    for draft in drafts:
        require_draft_time(draft, now)


async def qualify_saved_inputs_locked(
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    services: NativeFactServices,
    saved: NotificationDraft,
) -> tuple[datetime, ...]:
    """Obsolete status cannot hide lost access or a changed contributor/source snapshot."""
    source_scope = owner_scope(scope, identity)
    required, deadlines = await qualify_native_inputs(
        session,
        control,
        source_scope,
        identity,
        services,
        saved.provenance.required_resource_ids,
        saved.provenance.artifacts,
    )
    _, _, heads = await report_resources(
        session, source_scope, required, saved.provenance.artifacts
    )
    if required != saved.provenance.required_resource_ids or heads != saved.provenance.source_heads:
        raise NotificationUnavailableError("Qualified notification source snapshot changed")
    return tuple(
        sorted(
            {
                *deadlines,
                *saved.provenance.protection_deadlines,
                saved.recipient_policy.expires_at,
            }
        )
    )


def require_protection_time(deadlines: tuple[datetime, ...], now: datetime) -> None:
    if any(deadline <= now for deadline in deadlines):
        raise NotificationUnavailableError("Qualified notification license expired")

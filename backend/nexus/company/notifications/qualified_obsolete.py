"""Body-free obsolete wakes still require actual historical subject and complete current READ."""

from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.event_store import read_event
from nexus.company.brain.events import OutboxEvent
from nexus.company.brain.native_fact_contracts import DigestSelector
from nexus.company.brain.native_fact_inputs import (
    receipt_references,
    source_references,
    work_resources,
)
from nexus.company.brain.native_fact_resolution import action_resource
from nexus.company.brain.native_fact_services import NativeFactServices
from nexus.company.brain.native_fact_wake import event_selector
from nexus.company.brain.obsolete_native_provenance import qualify_obsolete_native_inputs
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.operating_report_inputs import author_input_references
from nexus.company.management.operating_report_store import stored_report
from nexus.company.management.operation_models import ManagementReportSnapshot
from nexus.company.notifications.contracts import OwnerRecipientPolicy
from nexus.company.notifications.draft_store import owner_scope
from nexus.company.notifications.native_facts import NotificationUnavailableError
from nexus.company.notifications.qualified_contracts import DraftPublication
from nexus.company.notifications.qualified_support import (
    require_protection_time,
    require_publication_scope,
)
from nexus.company.notifications.recipient_registry import RegisteredOwnerRecipients
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import CompanyControl


async def obsolete_publication_locked(
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    event: OutboxEvent,
    services: NativeFactServices,
    recipient: OwnerRecipientPolicy,
    recipients: RegisteredOwnerRecipients,
) -> DraftPublication:
    deadlines = await qualify_obsolete_event_locked(
        session, control, owner_scope(scope, identity), identity, event, services
    )
    await require_publication_scope(session, control, scope, identity, recipient, recipients)
    require_protection_time(deadlines, await db_now(session))
    return DraftPublication(
        company_id=scope.company_id,
        event_id=event.event_id,
        state="obsolete",
        reason="obsolete_native_state",
        protection_deadlines=deadlines,
    )


async def qualify_obsolete_event_locked(
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    event: OutboxEvent,
    services: NativeFactServices,
) -> tuple[datetime, ...]:
    """A stale status is no license to acknowledge an unsupported/private subject."""
    actual = await read_event(session, scope.company_id, event.event_id)
    if actual is None or actual != event:
        raise NotificationUnavailableError("Native notification event is unavailable")
    selector = event_selector(actual, services)
    if selector is None:
        raise NotificationUnavailableError("Native notification configuration is unavailable")
    extra_deadlines: tuple[datetime, ...] = ()
    if isinstance(selector, DigestSelector):
        resources, references, extra_deadlines = await _digest_inputs(
            session, control, scope, identity, selector, services
        )
    else:
        resources = (event.resource.resource_id,)
        if (
            event.action_id is not None
            and await action_resource(session, scope, event.action_id, services) != event.resource
        ):
            raise NotificationUnavailableError("Native notification action resource changed")
        if event.task_id is not None:
            resources = tuple(
                sorted(
                    set(resources)
                    | set(await work_resources(session, scope, event.task_id, services))
                )
            )
        references = await source_references(session, scope, resources)
        if event.task_id is not None:
            references = _unique(
                (*references, *await receipt_references(session, scope, event.task_id))
            )
    _, deadlines = await qualify_obsolete_native_inputs(
        session, control, scope, identity, services, resources, references
    )
    return tuple(sorted({*deadlines, *extra_deadlines}))


async def _digest_inputs(
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    selector: DigestSelector,
    services: NativeFactServices,
) -> tuple[tuple[UUID, ...], tuple[ArtifactRevisionRef, ...], tuple[datetime, ...]]:
    registered = next((row for row in services.digests if row.schedule == selector.schedule), None)
    now = await db_now(session)
    if registered is None or not registered.registered_at <= now < registered.expires_at:
        raise NotificationUnavailableError("Native digest configuration is unavailable")
    row = await session.get(ManagementReportSnapshot, (scope.company_id, registered.report_id))
    if row is None:
        raise NotificationUnavailableError("Native digest report is unavailable")
    saved = stored_report(row)
    if saved.created_by != control.owner_id:
        raise NotificationUnavailableError("Native digest report owner changed")
    references = await author_input_references(
        session, control, scope, identity, saved, services.artifacts, services.freshness
    )
    resources = tuple(
        sorted(set(saved.data.required_resource_ids) | {registered.resource.resource_id})
    )
    return resources, references, (registered.expires_at,)


def _unique(references: tuple[ArtifactRevisionRef, ...]) -> tuple[ArtifactRevisionRef, ...]:
    result: dict[UUID, ArtifactRevisionRef] = {}
    for reference in references:
        previous = result.get(reference.artifact_revision_id)
        if previous is not None and previous != reference:
            raise NotificationUnavailableError("Native obsolete input revisions conflict")
        result[reference.artifact_revision_id] = reference
    return tuple(result[key] for key in sorted(result))

"""Actual current owner publications, head CAS and audit commit together without new work."""

from typing import Literal
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.contracts.company import CompanyMandate, DepartmentCharter
from nexus.company.management.base import RevisionRef
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.control_events import (
    CharterSubject,
    ManagementControlEvent,
    MandateSubject,
    append_control_event,
    find_control_event,
)
from nexus.company.management.control_support import (
    ManagementConflictError,
    charter_record,
    charter_ref,
    current_charter,
    current_mandate,
    db_clock,
    mandate_record,
    mandate_ref,
    require_cas,
    require_member,
    same_mandate,
    validate_mandate,
)
from nexus.company.management.governance import CharterRevision, CharterRevisionRef, MandateRevision
from nexus.company.management.governance_models import (
    ManagementCharterHead,
    ManagementCharterRevision,
    ManagementMandateHead,
    ManagementMandateRevision,
)
from nexus.company.management.transactions import (
    ManagementDeniedError,
    management_owner_transaction,
)


class ManagementControlStore:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self.factory = factory

    async def publish_mandate(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        data: CompanyMandate,
        *,
        expected_revision_id: UUID | None,
    ) -> MandateRevision:
        data = CompanyMandate.model_validate_json(data.model_dump_json())
        async with management_owner_transaction(self.factory, scope, identity) as (
            session,
            control,
            now,
        ):
            validate_mandate(data, control)
            previous = await session.scalar(
                select(ManagementMandateRevision).where(
                    ManagementMandateRevision.company_id == scope.company_id,
                    ManagementMandateRevision.version == data.version,
                )
            )
            if previous is not None:
                record = mandate_record(previous)
                same_mandate(record, data)
                return record  # Historical replay cannot restore limits/head/activity or dates.
            head = await session.get(ManagementMandateHead, scope.company_id)
            require_cas(head.current_revision_id if head else None, expected_revision_id)
            old = (
                await session.get(
                    ManagementMandateRevision, (scope.company_id, head.current_revision_id)
                )
                if head
                else None
            )
            digest = canonical_sha256(data)
            record = MandateRevision(
                company_id=scope.company_id,
                revision_id=uuid5(scope.company_id, f"mandate:{data.version}:{digest}"),
                version=data.version,
                sha256=digest,
                mandate=data,
                recorded_by=control.owner_id,
                recorded_at=now,
            )
            session.add(
                ManagementMandateRevision(
                    company_id=scope.company_id,
                    revision_id=record.revision_id,
                    version=record.version,
                    owner_id=control.owner_id,
                    sha256=digest,
                    payload_json=data.model_dump_json(),
                    recorded_by=control.owner_id,
                    recorded_at=now,
                )
            )
            await session.flush()
            if head is None:
                head = ManagementMandateHead(
                    company_id=scope.company_id, current_revision_id=record.revision_id, active=True
                )
                session.add(head)
            else:
                head.current_revision_id = record.revision_id
            # Current actual-owner authority changes caps, preserving every hold/spend/counter.
            if head.active:
                control.daily_cap_usd, control.work_cap_usd = data.daily_cap_usd, data.work_cap_usd
            await session.flush()
            await append_control_event(
                session,
                scope,
                control,
                "publish",
                MandateSubject(
                    current=mandate_ref(record),
                    previous=mandate_ref(mandate_record(old)) if old else None,
                ),
                await db_clock(session),
            )
            return record

    async def publish_charter(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        data: DepartmentCharter,
        *,
        mandate: RevisionRef,
        expected_revision_id: UUID | None,
    ) -> CharterRevision:
        data = DepartmentCharter.model_validate_json(data.model_dump_json())
        if data.company_id != scope.company_id:
            raise ManagementDeniedError("Management charter scope is unavailable")
        async with management_owner_transaction(self.factory, scope, identity) as (
            session,
            control,
            now,
        ):
            await current_mandate(session, scope, mandate)
            await require_member(session, control, data.verifier_id)
            prior = await session.scalar(
                select(ManagementCharterRevision).where(
                    ManagementCharterRevision.company_id == scope.company_id,
                    ManagementCharterRevision.department_id == data.department_id,
                    ManagementCharterRevision.version == data.version,
                )
            )
            if prior is not None:
                record = await charter_record(session, prior)
                if record.sha256 != canonical_sha256(data) or record.mandate != mandate:
                    raise ManagementConflictError("Management charter version cannot be rebound")
                return record
            head = await session.get(ManagementCharterHead, (scope.company_id, data.department_id))
            require_cas(head.current_revision_id if head else None, expected_revision_id)
            old = (
                await session.get(
                    ManagementCharterRevision, (scope.company_id, head.current_revision_id)
                )
                if head
                else None
            )
            digest = canonical_sha256(data)
            record = CharterRevision(
                company_id=scope.company_id,
                revision_id=uuid5(
                    data.department_id, f"charter:{data.version}:{digest}:{mandate.revision_id}"
                ),
                department_id=data.department_id,
                version=data.version,
                sha256=digest,
                charter=data,
                mandate=mandate,
                recorded_by=control.owner_id,
                recorded_at=now,
            )
            session.add(
                ManagementCharterRevision(
                    company_id=scope.company_id,
                    revision_id=record.revision_id,
                    department_id=data.department_id,
                    version=data.version,
                    mandate_revision_id=mandate.revision_id,
                    sha256=digest,
                    payload_json=data.model_dump_json(),
                    recorded_by=control.owner_id,
                    recorded_at=now,
                )
            )
            await session.flush()
            if head is None:
                session.add(
                    ManagementCharterHead(
                        company_id=scope.company_id,
                        department_id=data.department_id,
                        current_revision_id=record.revision_id,
                        active=True,
                    )
                )
            else:
                head.current_revision_id = record.revision_id
            await session.flush()
            await append_control_event(
                session,
                scope,
                control,
                "publish",
                CharterSubject(
                    current=charter_ref(record),
                    previous=charter_ref(await charter_record(session, old)) if old else None,
                ),
                await db_clock(session),
            )
            return record

    async def revoke_mandate(
        self, scope: CompanyControlScope, identity: VerifiedIdentity, reference: RevisionRef
    ) -> ManagementControlEvent:
        return await self._mandate_activity(scope, identity, reference, active=False)

    async def reactivate_mandate(
        self, scope: CompanyControlScope, identity: VerifiedIdentity, reference: RevisionRef
    ) -> ManagementControlEvent:
        return await self._mandate_activity(scope, identity, reference, active=True)

    async def _mandate_activity(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        reference: RevisionRef,
        *,
        active: bool,
    ) -> ManagementControlEvent:
        async with management_owner_transaction(
            self.factory, scope, identity, allow_paused=not active
        ) as (session, control, _):
            record = await current_mandate(session, scope, reference, active=False)
            subject = MandateSubject(current=mandate_ref(record), previous=mandate_ref(record))
            kind: Literal["reactivate", "revoke"] = "reactivate" if active else "revoke"
            previous = await find_control_event(session, scope, kind, subject)
            if previous is not None:
                return previous  # An old maintenance replay cannot reverse a later decision.
            if active:
                validate_mandate(record.mandate, control)
                control.daily_cap_usd = record.mandate.daily_cap_usd
                control.work_cap_usd = record.mandate.work_cap_usd
            head = await session.get(ManagementMandateHead, scope.company_id)
            assert head is not None
            head.active = active
            await session.flush()
            return await append_control_event(
                session, scope, control, kind, subject, await db_clock(session)
            )

    async def revoke_charter(
        self, scope: CompanyControlScope, identity: VerifiedIdentity, reference: CharterRevisionRef
    ) -> ManagementControlEvent:
        return await self._charter_activity(scope, identity, reference, active=False)

    async def reactivate_charter(
        self, scope: CompanyControlScope, identity: VerifiedIdentity, reference: CharterRevisionRef
    ) -> ManagementControlEvent:
        return await self._charter_activity(scope, identity, reference, active=True)

    async def _charter_activity(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        reference: CharterRevisionRef,
        *,
        active: bool,
    ) -> ManagementControlEvent:
        async with management_owner_transaction(
            self.factory, scope, identity, allow_paused=not active
        ) as (session, control, _):
            record = await current_charter(session, scope, reference, active=False)
            subject = CharterSubject(current=charter_ref(record), previous=charter_ref(record))
            kind: Literal["reactivate", "revoke"] = "reactivate" if active else "revoke"
            previous = await find_control_event(session, scope, kind, subject)
            if previous is not None:
                return previous
            if active:
                await current_mandate(session, scope, record.mandate)
                await require_member(session, control, record.charter.verifier_id)
            head = await session.get(
                ManagementCharterHead, (scope.company_id, reference.department_id)
            )
            assert head is not None
            head.active = active
            await session.flush()
            return await append_control_event(
                session, scope, control, kind, subject, await db_clock(session)
            )
